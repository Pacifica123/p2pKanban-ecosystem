pub mod device_link;
pub mod ring;
use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use chacha20poly1305::{
    aead::{Aead, KeyInit},
    XChaCha20Poly1305, XNonce,
};
use hmac::{Hmac, Mac};
use nostr_sdk::prelude::*;
use p2p_kanban_sync_core::{
    sign_envelope, validate_envelope, verify_envelope, SignedSyncEnvelope, SyncEnvelope,
};
use rand::{rngs::OsRng, RngCore};
use serde::{Deserialize, Serialize};
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

const CIPHERTEXT_VERSION: u8 = 1;
const WORKSPACE_KEY_DOMAIN: &[u8] = b"p2p-kanban:workspace-key:v1";
const ROAMING_BOARD_KEY_DOMAIN: &[u8] = b"p2p-kanban:roaming-board-key:v1";
const BOARD_TAG_DOMAIN: &[u8] = b"p2p-kanban:board-tag:v1";
pub const ROAMING_PROTOCOL_VERSION: &str = "p2p-kanban-roaming/1";
pub const ROAMING_EVENT_KIND_OFFSET: u16 = 1;
pub const DEVICE_CATALOG_KIND_OFFSET: u16 = 2;
pub const DEVICE_CATALOG_PROTOCOL: &str = "p2p-kanban-device-catalog/1";

fn default_capability_epoch() -> i64 {
    1
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RoamingCapabilityMaterial {
    pub protocol_version: String,
    pub board_tag: String,
    pub board_key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RoamingBoardEvent {
    pub protocol_version: String,
    pub event_id: String,
    pub workspace_id: String,
    pub board_id: String,
    #[serde(default = "default_capability_epoch")]
    pub capability_epoch: i64,
    pub replica_id: String,
    pub replica_seq: i64,
    pub logical_clock: i64,
    pub entity_type: String,
    pub entity_id: String,
    pub operation: String,
    #[serde(default)]
    pub field_mask: Vec<String>,
    #[serde(default)]
    pub payload: serde_json::Value,
    pub occurred_at: String,
}

#[derive(Debug, Clone)]
pub struct RecoveredRoamingEvent {
    pub nostr_event_id: String,
    pub signed_at: u64,
    pub author_public_key: String,
    pub event: RoamingBoardEvent,
}

#[derive(Debug, Clone)]
pub struct RecoveredDeviceCatalog {
    pub nostr_event_id: String,
    pub signed_at: u64,
    pub author_public_key: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, Deserialize)]
struct DeviceCatalogEnvelope {
    protocol: String,
    recipient: String,
    parts: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct NostrTransportConfig {
    pub relays: Vec<String>,
    pub secret_key: String,
    pub master_key: Vec<u8>,
    pub event_kind: u16,
    pub fetch_timeout: Duration,
    pub min_relay_acks: usize,
}

impl NostrTransportConfig {
    pub fn validate(&self) -> Result<()> {
        if self.relays.is_empty() {
            bail!("at least one Nostr relay is required");
        }
        if self
            .relays
            .iter()
            .any(|relay| !(relay.starts_with("wss://") || relay.starts_with("ws://")))
        {
            bail!("Nostr relay URLs must use ws:// or wss://");
        }
        if self.secret_key.trim().is_empty() {
            bail!("Nostr secret key is required");
        }
        if self.master_key.len() != 32 {
            bail!("Nostr shadow master key must contain exactly 32 bytes");
        }
        if self.min_relay_acks == 0 || self.min_relay_acks > self.relays.len() {
            bail!("minimum relay acknowledgements must be between 1 and the relay count");
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CiphertextRecord {
    version: u8,
    board_tag: String,
    nonce: String,
    ciphertext: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NostrDeliveryReceipt {
    pub nostr_event_id: String,
    pub configured_relays: usize,
    pub accepted_relays: Vec<String>,
    pub failed_relays: Vec<String>,
    pub board_tag: String,
}

#[derive(Debug, Clone)]
pub struct NostrCodec {
    master_key: Vec<u8>,
}

impl NostrCodec {
    pub fn new(master_key: Vec<u8>) -> Result<Self> {
        if master_key.len() != 32 {
            bail!("Nostr shadow master key must contain exactly 32 bytes");
        }
        Ok(Self { master_key })
    }

    pub fn board_tag(&self, workspace_id: &str) -> Result<String> {
        derive_tag(&self.master_key, BOARD_TAG_DOMAIN, workspace_id)
    }

    pub fn roaming_board_tag(&self, board_id: &str) -> Result<String> {
        derive_tag(
            &self.roaming_board_key(board_id)?,
            BOARD_TAG_DOMAIN,
            board_id,
        )
    }

    pub fn roaming_capability(&self, board_id: &str) -> Result<RoamingCapabilityMaterial> {
        Ok(RoamingCapabilityMaterial {
            protocol_version: ROAMING_PROTOCOL_VERSION.to_string(),
            board_tag: self.roaming_board_tag(board_id)?,
            board_key: URL_SAFE_NO_PAD.encode(self.roaming_board_key(board_id)?),
        })
    }

    pub fn random_roaming_capability(board_id: &str) -> Result<RoamingCapabilityMaterial> {
        let mut board_key = [0u8; 32];
        OsRng.fill_bytes(&mut board_key);
        Ok(RoamingCapabilityMaterial {
            protocol_version: ROAMING_PROTOCOL_VERSION.to_string(),
            board_tag: roaming_board_tag_from_key(&board_key, board_id)?,
            board_key: URL_SAFE_NO_PAD.encode(board_key),
        })
    }

    pub fn roaming_capability_from_board_key(
        board_id: &str,
        board_key: &str,
    ) -> Result<RoamingCapabilityMaterial> {
        let board_key = decode_roaming_board_key(board_key)?;
        Ok(RoamingCapabilityMaterial {
            protocol_version: ROAMING_PROTOCOL_VERSION.to_string(),
            board_tag: roaming_board_tag_from_key(&board_key, board_id)?,
            board_key: URL_SAFE_NO_PAD.encode(board_key),
        })
    }

    pub fn seal_roaming(&self, event: &RoamingBoardEvent) -> Result<String> {
        let board_key = self.roaming_board_key(&event.board_id)?;
        Self::seal_roaming_with_key(event, &board_key)
    }

    pub fn seal_roaming_with_board_key(
        event: &RoamingBoardEvent,
        board_key: &str,
    ) -> Result<String> {
        let board_key = decode_roaming_board_key(board_key)?;
        Self::seal_roaming_with_key(event, &board_key)
    }

    fn seal_roaming_with_key(event: &RoamingBoardEvent, board_key: &[u8; 32]) -> Result<String> {
        if event.protocol_version != ROAMING_PROTOCOL_VERSION {
            bail!("unsupported roaming protocol version");
        }
        if event.replica_seq < 1 || event.logical_clock < 1 {
            bail!("roaming event counters must be positive");
        }
        let plaintext = serde_json::to_vec(event).context("could not serialize roaming event")?;
        let cipher = XChaCha20Poly1305::new_from_slice(board_key)
            .map_err(|_| anyhow!("could not initialize XChaCha20-Poly1305"))?;
        let mut nonce_bytes = [0u8; 24];
        OsRng.fill_bytes(&mut nonce_bytes);
        let ciphertext = cipher
            .encrypt(XNonce::from_slice(&nonce_bytes), plaintext.as_ref())
            .map_err(|_| anyhow!("could not encrypt roaming event"))?;

        serde_json::to_string(&CiphertextRecord {
            version: CIPHERTEXT_VERSION,
            board_tag: roaming_board_tag_from_key(board_key, &event.board_id)?,
            nonce: URL_SAFE_NO_PAD.encode(nonce_bytes),
            ciphertext: URL_SAFE_NO_PAD.encode(ciphertext),
        })
        .context("could not serialize roaming ciphertext record")
    }

    pub fn open_roaming(&self, board_id: &str, content: &str) -> Result<RoamingBoardEvent> {
        let board_key = self.roaming_board_key(board_id)?;
        Self::open_roaming_with_key(board_id, content, &board_key)
    }

    pub fn open_roaming_with_board_key(
        board_id: &str,
        content: &str,
        board_key: &str,
    ) -> Result<RoamingBoardEvent> {
        let board_key = decode_roaming_board_key(board_key)?;
        Self::open_roaming_with_key(board_id, content, &board_key)
    }

    fn open_roaming_with_key(
        board_id: &str,
        content: &str,
        board_key: &[u8; 32],
    ) -> Result<RoamingBoardEvent> {
        let record: CiphertextRecord = serde_json::from_str(content)
            .context("Nostr event content is not a ciphertext record")?;
        if record.version != CIPHERTEXT_VERSION {
            bail!("unsupported roaming ciphertext version");
        }
        if record.board_tag != roaming_board_tag_from_key(board_key, board_id)? {
            bail!("roaming event belongs to another board");
        }
        let nonce = URL_SAFE_NO_PAD
            .decode(record.nonce)
            .context("roaming nonce is not valid base64url")?;
        if nonce.len() != 24 {
            bail!("roaming nonce must contain 24 bytes");
        }
        let ciphertext = URL_SAFE_NO_PAD
            .decode(record.ciphertext)
            .context("roaming ciphertext is not valid base64url")?;
        let plaintext = XChaCha20Poly1305::new_from_slice(board_key)
            .map_err(|_| anyhow!("could not initialize XChaCha20-Poly1305"))?
            .decrypt(XNonce::from_slice(&nonce), ciphertext.as_ref())
            .map_err(|_| anyhow!("roaming ciphertext authentication failed"))?;
        let event: RoamingBoardEvent =
            serde_json::from_slice(&plaintext).context("decrypted roaming payload is invalid")?;
        if event.protocol_version != ROAMING_PROTOCOL_VERSION || event.board_id != board_id {
            bail!("decrypted roaming event has incompatible scope");
        }
        Ok(event)
    }

    fn workspace_key(&self, workspace_id: &str) -> Result<[u8; 32]> {
        derive_key(&self.master_key, WORKSPACE_KEY_DOMAIN, workspace_id)
    }

    fn roaming_board_key(&self, board_id: &str) -> Result<[u8; 32]> {
        derive_key(&self.master_key, ROAMING_BOARD_KEY_DOMAIN, board_id)
    }

    pub fn seal(&self, envelope: SyncEnvelope) -> Result<String> {
        validate_envelope(&envelope).context("refusing to mirror invalid sync envelope")?;
        let workspace_id = envelope.workspace_id.clone();
        let workspace_key = self.workspace_key(&workspace_id)?;
        let signed = sign_envelope(envelope, "nostr-shadow-workspace-v1", &workspace_key)
            .context("could not authenticate sync envelope")?;
        let plaintext =
            serde_json::to_vec(&signed).context("could not serialize signed sync envelope")?;

        let cipher = XChaCha20Poly1305::new_from_slice(&workspace_key)
            .map_err(|_| anyhow!("could not initialize XChaCha20-Poly1305"))?;
        let mut nonce_bytes = [0u8; 24];
        OsRng.fill_bytes(&mut nonce_bytes);
        let ciphertext = cipher
            .encrypt(XNonce::from_slice(&nonce_bytes), plaintext.as_ref())
            .map_err(|_| anyhow!("could not encrypt sync envelope"))?;

        serde_json::to_string(&CiphertextRecord {
            version: CIPHERTEXT_VERSION,
            board_tag: self.board_tag(&workspace_id)?,
            nonce: URL_SAFE_NO_PAD.encode(nonce_bytes),
            ciphertext: URL_SAFE_NO_PAD.encode(ciphertext),
        })
        .context("could not serialize Nostr ciphertext record")
    }

    pub fn open_for_workspace(
        &self,
        workspace_id: &str,
        content: &str,
    ) -> Result<SignedSyncEnvelope> {
        let record: CiphertextRecord = serde_json::from_str(content)
            .context("Nostr event content is not a ciphertext record")?;
        if record.version != CIPHERTEXT_VERSION {
            bail!("unsupported Nostr ciphertext version {}", record.version);
        }
        if record.board_tag != self.board_tag(workspace_id)? {
            bail!("Nostr event belongs to another workspace");
        }

        let nonce = URL_SAFE_NO_PAD
            .decode(record.nonce)
            .context("Nostr ciphertext nonce is not valid base64url")?;
        if nonce.len() != 24 {
            bail!("Nostr ciphertext nonce must contain 24 bytes");
        }
        let ciphertext = URL_SAFE_NO_PAD
            .decode(record.ciphertext)
            .context("Nostr ciphertext is not valid base64url")?;
        let workspace_key = self.workspace_key(workspace_id)?;
        let cipher = XChaCha20Poly1305::new_from_slice(&workspace_key)
            .map_err(|_| anyhow!("could not initialize XChaCha20-Poly1305"))?;
        let plaintext = cipher
            .decrypt(XNonce::from_slice(&nonce), ciphertext.as_ref())
            .map_err(|_| anyhow!("Nostr ciphertext authentication failed"))?;
        let signed: SignedSyncEnvelope = serde_json::from_slice(&plaintext)
            .context("decrypted Nostr payload is not a signed envelope")?;
        verify_envelope(&signed, &workspace_key)
            .context("decrypted sync envelope signature is invalid")?;
        validate_envelope(&signed.envelope).context("decrypted sync envelope is invalid")?;
        if signed.envelope.workspace_id != workspace_id {
            bail!("decrypted sync envelope belongs to another workspace");
        }
        Ok(signed)
    }
}

#[derive(Clone)]
pub struct NostrTransport {
    client: Client,
    keys: Keys,
    codec: NostrCodec,
    config: NostrTransportConfig,
}

impl NostrTransport {
    pub async fn connect(config: NostrTransportConfig) -> Result<Self> {
        config.validate()?;
        let keys = Keys::parse(config.secret_key.trim()).context("invalid Nostr secret key")?;
        let client = Client::new(keys.clone());
        for relay in &config.relays {
            client
                .add_relay(relay)
                .await
                .with_context(|| format!("could not add Nostr relay {relay}"))?;
        }
        client.connect().await;
        client.wait_for_connection(Duration::from_secs(5)).await;

        Ok(Self {
            client,
            keys,
            codec: NostrCodec::new(config.master_key.clone())?,
            config,
        })
    }

    pub fn author_public_key(&self) -> String {
        self.keys.public_key().to_string()
    }

    pub async fn publish(&self, envelope: SyncEnvelope) -> Result<NostrDeliveryReceipt> {
        let board_tag = self.codec.board_tag(&envelope.workspace_id)?;
        let content = self.codec.seal(envelope)?;
        let builder = EventBuilder::new(Kind::Custom(self.config.event_kind), content);
        let output = self
            .client
            .send_event_builder(builder)
            .await
            .context("Nostr relays did not accept the shadow event")?;
        if output.success.len() < self.config.min_relay_acks {
            bail!(
                "Nostr shadow event reached only {}/{} required relays; failures: {:?}",
                output.success.len(),
                self.config.min_relay_acks,
                output.failed
            );
        }

        Ok(NostrDeliveryReceipt {
            nostr_event_id: output.val.to_string(),
            configured_relays: self.config.relays.len(),
            accepted_relays: output.success.iter().map(ToString::to_string).collect(),
            failed_relays: output.failed.keys().map(ToString::to_string).collect(),
            board_tag,
        })
    }


    pub async fn publish_device_catalog(
        &self,
        recipient: &str,
        payload: &serde_json::Value,
    ) -> Result<NostrDeliveryReceipt> {
        let recipient_key = PublicKey::from_hex(recipient)?;
        let parts = device_link::encrypt(&self.config.secret_key, recipient, payload)?;
        let content = serde_json::to_string(&serde_json::json!({
            "protocol": DEVICE_CATALOG_PROTOCOL,
            "recipient": recipient,
            "parts": parts,
        }))?;
        let builder = EventBuilder::new(
            Kind::Custom(self.config.event_kind.saturating_add(DEVICE_CATALOG_KIND_OFFSET)),
            content,
        ).tags([Tag::public_key(recipient_key), Tag::hashtag("p2pkanban-device-catalog")]);
        let output = self.client.send_event_builder(builder).await
            .context("Nostr relays did not accept the device catalog")?;
        if output.success.len() < self.config.min_relay_acks {
            bail!("device catalog reached only {}/{} required relays",output.success.len(),self.config.min_relay_acks);
        }
        Ok(NostrDeliveryReceipt {
            nostr_event_id: output.val.to_string(), configured_relays:self.config.relays.len(),
            accepted_relays:output.success.iter().map(ToString::to_string).collect(),
            failed_relays:output.failed.keys().map(ToString::to_string).collect(),
            board_tag:recipient.to_string(),
        })
    }

    pub async fn recover_device_catalogs(&self) -> Result<Vec<RecoveredDeviceCatalog>> {
        let recipient = self.keys.public_key().to_string();
        let filter = Filter::new().kind(Kind::Custom(
            self.config
                .event_kind
                .saturating_add(DEVICE_CATALOG_KIND_OFFSET),
        )).pubkey(self.keys.public_key());
        let events = self
            .client
            .fetch_events(filter, self.config.fetch_timeout)
            .await
            .context("could not fetch device catalogs")?;
        let mut recovered = Vec::new();
        for event in events.iter() {
            let envelope: DeviceCatalogEnvelope = match serde_json::from_str(&event.content) {
                Ok(value) => value,
                Err(_) => continue,
            };
            if envelope.protocol != DEVICE_CATALOG_PROTOCOL || envelope.recipient != recipient {
                continue;
            }
            let sender = event.pubkey.to_string();
            if let Ok(payload) =
                device_link::decrypt(&self.config.secret_key, &sender, &envelope.parts)
            {
                recovered.push(RecoveredDeviceCatalog {
                    nostr_event_id: event.id.to_string(),
                    signed_at: event.created_at.as_secs(),
                    author_public_key: sender,
                    payload,
                });
            }
        }
        recovered.sort_by(|left, right| {
            left.signed_at
                .cmp(&right.signed_at)
                .then_with(|| left.nostr_event_id.cmp(&right.nostr_event_id))
        });
        recovered.dedup_by(|left, right| left.nostr_event_id == right.nostr_event_id);
        Ok(recovered)
    }
    pub async fn publish_roaming(&self, event: &RoamingBoardEvent) -> Result<NostrDeliveryReceipt> {
        let board_tag = self.codec.roaming_board_tag(&event.board_id)?;
        let content = self.codec.seal_roaming(event)?;
        self.publish_roaming_content(board_tag, content).await
    }

    pub async fn publish_roaming_with_board_key(
        &self,
        event: &RoamingBoardEvent,
        board_key: &str,
    ) -> Result<NostrDeliveryReceipt> {
        let material = NostrCodec::roaming_capability_from_board_key(&event.board_id, board_key)?;
        let content = NostrCodec::seal_roaming_with_board_key(event, board_key)?;
        self.publish_roaming_content(material.board_tag, content)
            .await
    }

    async fn publish_roaming_content(
        &self,
        board_tag: String,
        content: String,
    ) -> Result<NostrDeliveryReceipt> {
        let identifier = Tag::identifier(board_tag.clone());
        let marker = Tag::hashtag("p2pkanban-roaming");
        let builder = EventBuilder::new(
            Kind::Custom(
                self.config
                    .event_kind
                    .saturating_add(ROAMING_EVENT_KIND_OFFSET),
            ),
            content,
        )
        .tags([identifier, marker]);
        let output = self
            .client
            .send_event_builder(builder)
            .await
            .context("Nostr relays did not accept the roaming event")?;
        if output.success.len() < self.config.min_relay_acks {
            bail!(
                "roaming event reached only {}/{} required relays",
                output.success.len(),
                self.config.min_relay_acks
            );
        }
        Ok(NostrDeliveryReceipt {
            nostr_event_id: output.val.to_string(),
            configured_relays: self.config.relays.len(),
            accepted_relays: output.success.iter().map(ToString::to_string).collect(),
            failed_relays: output.failed.keys().map(ToString::to_string).collect(),
            board_tag,
        })
    }

    pub async fn recover_roaming(&self, board_id: &str) -> Result<Vec<RecoveredRoamingEvent>> {
        let expected_tag = self.codec.roaming_board_tag(board_id)?;
        self.recover_roaming_records(board_id, expected_tag, None)
            .await
    }

    pub async fn recover_roaming_with_board_key(
        &self,
        board_id: &str,
        board_key: &str,
    ) -> Result<Vec<RecoveredRoamingEvent>> {
        let material = NostrCodec::roaming_capability_from_board_key(board_id, board_key)?;
        self.recover_roaming_records(board_id, material.board_tag, Some(board_key))
            .await
    }

    async fn recover_roaming_records(
        &self,
        board_id: &str,
        expected_tag: String,
        board_key: Option<&str>,
    ) -> Result<Vec<RecoveredRoamingEvent>> {
        let filter = Filter::new()
            .kind(Kind::Custom(
                self.config
                    .event_kind
                    .saturating_add(ROAMING_EVENT_KIND_OFFSET),
            ))
            .identifier(expected_tag.clone());
        let events = self
            .client
            .fetch_events(filter, self.config.fetch_timeout)
            .await
            .context("could not fetch roaming Nostr events")?;
        let mut recovered = Vec::new();
        for nostr_event in events.iter() {
            let record = match serde_json::from_str::<CiphertextRecord>(&nostr_event.content) {
                Ok(record) if record.board_tag == expected_tag => record,
                _ => continue,
            };
            let content = serde_json::to_string(&record)?;
            let opened = match board_key {
                Some(board_key) => {
                    NostrCodec::open_roaming_with_board_key(board_id, &content, board_key)
                }
                None => self.codec.open_roaming(board_id, &content),
            };
            if let Ok(event) = opened {
                recovered.push(RecoveredRoamingEvent {
                    nostr_event_id: nostr_event.id.to_string(),
                    signed_at: nostr_event.created_at.as_secs(),
                    author_public_key: nostr_event.pubkey.to_string(),
                    event,
                });
            }
        }
        recovered.sort_by(|left, right| {
            left.event
                .logical_clock
                .cmp(&right.event.logical_clock)
                .then_with(|| left.event.replica_id.cmp(&right.event.replica_id))
                .then_with(|| left.event.event_id.cmp(&right.event.event_id))
        });
        recovered.dedup_by(|left, right| left.event.event_id == right.event.event_id);
        Ok(recovered)
    }

    pub async fn recover_workspace(&self, workspace_id: &str) -> Result<Vec<SignedSyncEnvelope>> {
        let filter = Filter::new()
            .author(self.keys.public_key())
            .kind(Kind::Custom(self.config.event_kind));
        let events = self
            .client
            .fetch_events(filter, self.config.fetch_timeout)
            .await
            .context("could not fetch Nostr shadow events")?;

        let expected_tag = self.codec.board_tag(workspace_id)?;
        let mut recovered = Vec::new();
        for event in events.iter() {
            let record = match serde_json::from_str::<CiphertextRecord>(&event.content) {
                Ok(record) if record.board_tag == expected_tag => record,
                _ => continue,
            };
            let content = serde_json::to_string(&record)?;
            if let Ok(envelope) = self.codec.open_for_workspace(workspace_id, &content) {
                recovered.push(envelope);
            }
        }

        recovered.sort_by(|left, right| {
            left.envelope
                .event
                .server_order
                .cmp(&right.envelope.event.server_order)
                .then_with(|| {
                    left.envelope
                        .event
                        .replica_id
                        .cmp(&right.envelope.event.replica_id)
                })
                .then_with(|| left.envelope.envelope_id.cmp(&right.envelope.envelope_id))
        });
        recovered.dedup_by(|left, right| left.envelope.envelope_id == right.envelope.envelope_id);
        Ok(recovered)
    }

    pub async fn shutdown(&self) {
        self.client.shutdown().await;
    }
}

fn derive_key(master_key: &[u8], domain: &[u8], workspace_id: &str) -> Result<[u8; 32]> {
    let mut mac = <HmacSha256 as Mac>::new_from_slice(master_key)
        .map_err(|_| anyhow!("invalid master key"))?;
    mac.update(domain);
    mac.update(&[0]);
    mac.update(workspace_id.as_bytes());
    let bytes = mac.finalize().into_bytes();
    let mut key = [0u8; 32];
    key.copy_from_slice(&bytes);
    Ok(key)
}

fn derive_tag(master_key: &[u8], domain: &[u8], workspace_id: &str) -> Result<String> {
    Ok(URL_SAFE_NO_PAD.encode(derive_key(master_key, domain, workspace_id)?))
}

fn decode_roaming_board_key(value: &str) -> Result<[u8; 32]> {
    let bytes = URL_SAFE_NO_PAD
        .decode(value.trim())
        .context("roaming board key is not valid base64url")?;
    bytes
        .try_into()
        .map_err(|_| anyhow!("roaming board key must contain exactly 32 bytes"))
}

fn roaming_board_tag_from_key(board_key: &[u8; 32], board_id: &str) -> Result<String> {
    derive_tag(board_key, BOARD_TAG_DOMAIN, board_id)
}

#[cfg(test)]
mod tests {
    use p2p_kanban_sync_core::{ServerChangeEvent, SyncEnvelope};
    use serde_json::json;

    use super::*;

    fn envelope() -> SyncEnvelope {
        let mut envelope = SyncEnvelope::new(
            "018f22e2-355a-7ba2-8ef0-d7bc788ceec8",
            ServerChangeEvent {
                event_id: "018f22e2-1d58-7f08-9a36-1f96bd9854b1".to_string(),
                replica_id: "018f22e2-29cc-7ad6-aa57-b61d74a14e52".to_string(),
                replica_seq: 1,
                entity_type: "card".to_string(),
                entity_id: "018f22e2-355a-7ba2-8ef0-d7bc788ceec8".to_string(),
                operation: "update".to_string(),
                field_mask: vec!["title".to_string()],
                logical_clock: 7,
                base_server_order: Some(3),
                payload: json!({"title": "relay copy"}),
                metadata: json!({}),
                server_order: 4,
                accepted_at: "2026-07-25T20:00:00Z".to_string(),
                actor_user_id: None,
                actor_device_id: None,
            },
        );
        envelope.emitted_at = "2026-07-25T20:00:00Z".to_string();
        envelope
    }

    fn roaming_event() -> RoamingBoardEvent {
        RoamingBoardEvent {
            protocol_version: ROAMING_PROTOCOL_VERSION.to_string(),
            event_id: "018f22e2-1d58-7f08-9a36-1f96bd9854b1".to_string(),
            workspace_id: "018f22e2-355a-7ba2-8ef0-d7bc788ceec8".to_string(),
            board_id: "018f22e2-355a-7ba2-8ef0-d7bc788ceec9".to_string(),
            capability_epoch: 1,
            replica_id: "018f22e2-29cc-7ad6-aa57-b61d74a14e52".to_string(),
            replica_seq: 1,
            logical_clock: 7,
            entity_type: "card".to_string(),
            entity_id: "018f22e2-355a-7ba2-8ef0-d7bc788ceeca".to_string(),
            operation: "card.put".to_string(),
            field_mask: vec!["title".to_string()],
            payload: json!({"card": {"title": "relay copy"}}),
            occurred_at: "2026-07-28T12:00:00.000Z".to_string(),
        }
    }

    #[test]
    fn encrypted_record_round_trips_and_hides_workspace_id() {
        let codec = NostrCodec::new(vec![7; 32]).unwrap();
        let original = envelope();
        let content = codec.seal(original.clone()).unwrap();
        assert!(!content.contains(&original.workspace_id));
        assert!(!content.contains("relay copy"));

        let opened = codec
            .open_for_workspace(&original.workspace_id, &content)
            .unwrap();
        assert_eq!(opened.envelope, original);
    }

    #[test]
    fn wrong_workspace_cannot_open_record() {
        let codec = NostrCodec::new(vec![7; 32]).unwrap();
        let content = codec.seal(envelope()).unwrap();
        assert!(codec
            .open_for_workspace("018f22e2-aaaa-7aaa-8aaa-aaaaaaaaaaaa", &content)
            .is_err());
    }

    #[test]
    fn roaming_record_is_scoped_to_one_board() {
        let codec = NostrCodec::new(vec![7; 32]).unwrap();
        let original = roaming_event();
        let content = codec.seal_roaming(&original).unwrap();
        assert!(!content.contains(&original.board_id));
        assert!(!content.contains("relay copy"));
        assert_eq!(
            codec.open_roaming(&original.board_id, &content).unwrap(),
            original
        );
        assert!(codec
            .open_roaming("018f22e2-aaaa-7aaa-8aaa-aaaaaaaaaaaa", &content)
            .is_err());
    }

    #[test]
    fn imported_roaming_key_round_trips_across_node_master_keys() {
        let source = NostrCodec::new(vec![7; 32]).unwrap();
        let destination = NostrCodec::new(vec![9; 32]).unwrap();
        let original = roaming_event();
        let capability = source.roaming_capability(&original.board_id).unwrap();
        let content =
            NostrCodec::seal_roaming_with_board_key(&original, &capability.board_key).unwrap();

        assert!(destination
            .open_roaming(&original.board_id, &content)
            .is_err());
        assert_eq!(
            NostrCodec::open_roaming_with_board_key(
                &original.board_id,
                &content,
                &capability.board_key,
            )
            .unwrap(),
            original
        );
    }
    #[test]
    fn sql_frozen_event_roundtrip() {
        let original: RoamingBoardEvent = serde_json::from_str(include_str!("../../../tests/regression/fixtures/frozen-card.json")).unwrap();
        let material = NostrCodec::random_roaming_capability(&original.board_id).unwrap();
        let wire = NostrCodec::seal_roaming_with_board_key(&original,&material.board_key).unwrap();
        assert_eq!(NostrCodec::open_roaming_with_board_key(&original.board_id,&wire,&material.board_key).unwrap(), original);
    }

}
