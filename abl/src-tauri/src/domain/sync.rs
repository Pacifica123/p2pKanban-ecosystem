use std::{cmp::Ordering, collections::{BTreeMap, BTreeSet}};

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use chacha20poly1305::{
    aead::{Aead, KeyInit},
    XChaCha20Poly1305, XNonce,
};
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::domain::planner::VersionStamp;

pub const SYNC_PROTOCOL_VERSION: &str = "p2p-kanban-sync/1";
pub const ROAMING_PROTOCOL_VERSION: &str = "p2p-kanban-roaming/1";
pub const ROAMING_RECORD_VERSION: u8 = 1;
const BOARD_TAG_DOMAIN: &[u8] = b"p2p-kanban:board-tag:v1";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SyncCoreError {
    UnsupportedProtocolVersion,
    UnsupportedOperation,
    InvalidUuid,
    InvalidSequence,
    InvalidLogicalClock,
    InvalidCapabilityEpoch,
    ScopeMismatch,
    InvalidFieldMask,
    InvalidEnvelope,
    InvalidBoardKey,
    InvalidNonce,
    InvalidCiphertext,
    Serialization,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ServerChangeEvent {
    pub event_id: String,
    pub replica_id: String,
    pub replica_seq: i64,
    pub entity_type: String,
    pub entity_id: String,
    pub operation: String,
    pub field_mask: Vec<String>,
    pub logical_clock: i64,
    pub base_server_order: Option<i64>,
    pub payload: Value,
    pub metadata: Value,
    pub server_order: i64,
    pub accepted_at: String,
    pub actor_user_id: Option<String>,
    pub actor_device_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SyncEnvelope {
    pub protocol_version: String,
    pub envelope_id: String,
    pub workspace_id: String,
    pub event: ServerChangeEvent,
    #[serde(default)]
    pub parents: Vec<String>,
    pub emitted_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RoamingBoardEvent {
    pub protocol_version: String,
    pub event_id: String,
    pub workspace_id: String,
    pub board_id: String,
    pub capability_epoch: u64,
    pub replica_id: String,
    pub replica_seq: u64,
    pub logical_clock: u64,
    pub entity_type: String,
    pub entity_id: String,
    pub operation: String,
    pub field_mask: Vec<String>,
    pub payload: Value,
    pub occurred_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RoamingCiphertextRecord {
    pub version: u8,
    pub board_tag: String,
    pub nonce: String,
    pub ciphertext: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RoamingScope {
    pub workspace_id: String,
    pub board_id: String,
    pub capability_epoch: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MergeDisposition {
    Duplicate,
    Stale,
    BlockedByTombstone,
    Delete,
    ApplyFields(Vec<String>),
}

#[derive(Debug, Clone, Default)]
pub struct RoamingMergeState {
    seen_event_ids: BTreeSet<String>,
    field_versions: BTreeMap<(String, String), VersionStamp>,
    tombstones: BTreeMap<String, VersionStamp>,
}

fn validate_nonempty(value: &str) -> bool {
    !value.trim().is_empty() && value.len() <= 4096 && !value.as_bytes().contains(&0)
}

fn valid_field_mask(fields: &[String]) -> bool {
    if fields.is_empty() {
        return false;
    }
    let mut normalized = fields.iter().map(|field| field.trim()).collect::<Vec<_>>();
    if normalized.iter().any(|field| field.is_empty()) {
        return false;
    }
    normalized.sort_unstable();
    !normalized.windows(2).any(|pair| pair[0] == pair[1])
}

fn sync_operation_supported(value: &str) -> bool {
    matches!(
        value,
        "create" | "update" | "move" | "complete" | "delete" | "restore" | "reorder"
            | "add" | "remove" | "archive" | "unarchive"
    )
}

pub fn validate_sync_envelope(envelope: &SyncEnvelope) -> Result<(), SyncCoreError> {
    if envelope.protocol_version != SYNC_PROTOCOL_VERSION {
        return Err(SyncCoreError::UnsupportedProtocolVersion);
    }
    if envelope.envelope_id != envelope.event.event_id {
        return Err(SyncCoreError::InvalidEnvelope);
    }
    for value in [
        envelope.workspace_id.as_str(),
        envelope.event.event_id.as_str(),
        envelope.event.replica_id.as_str(),
        envelope.event.entity_id.as_str(),
    ] {
        Uuid::parse_str(value).map_err(|_| SyncCoreError::InvalidUuid)?;
    }
    if envelope.event.replica_seq < 1 {
        return Err(SyncCoreError::InvalidSequence);
    }
    if envelope.event.logical_clock < 1 {
        return Err(SyncCoreError::InvalidLogicalClock);
    }
    if envelope.event.base_server_order.is_some_and(|value| value < 0) {
        return Err(SyncCoreError::InvalidEnvelope);
    }
    if !sync_operation_supported(&envelope.event.operation) {
        return Err(SyncCoreError::UnsupportedOperation);
    }
    if !valid_field_mask(&envelope.event.field_mask) {
        return Err(SyncCoreError::InvalidFieldMask);
    }
    Ok(())
}

pub fn validate_roaming_event(
    event: &RoamingBoardEvent,
    scope: &RoamingScope,
) -> Result<(), SyncCoreError> {
    if event.protocol_version != ROAMING_PROTOCOL_VERSION {
        return Err(SyncCoreError::UnsupportedProtocolVersion);
    }
    if event.workspace_id != scope.workspace_id || event.board_id != scope.board_id {
        return Err(SyncCoreError::ScopeMismatch);
    }
    if event.capability_epoch == 0 || event.capability_epoch != scope.capability_epoch {
        return Err(SyncCoreError::InvalidCapabilityEpoch);
    }
    if event.replica_seq == 0 {
        return Err(SyncCoreError::InvalidSequence);
    }
    if event.logical_clock == 0 {
        return Err(SyncCoreError::InvalidLogicalClock);
    }
    if ![
        event.event_id.as_str(),
        event.replica_id.as_str(),
        event.entity_id.as_str(),
        event.occurred_at.as_str(),
    ]
    .into_iter()
    .all(validate_nonempty)
    {
        return Err(SyncCoreError::InvalidEnvelope);
    }
    if !valid_field_mask(&event.field_mask) {
        return Err(SyncCoreError::InvalidFieldMask);
    }
    match (event.entity_type.as_str(), event.operation.as_str()) {
        ("board", "board.snapshot" | "board.appearance.put") => {
            if event.entity_id != scope.board_id {
                Err(SyncCoreError::ScopeMismatch)
            } else {
                Ok(())
            }
        }
        ("card", "card.put" | "card.delete") => Ok(()),
        _ => Err(SyncCoreError::UnsupportedOperation),
    }
}

pub fn stamp_of(event: &RoamingBoardEvent) -> Result<VersionStamp, SyncCoreError> {
    VersionStamp::new(
        event.logical_clock,
        event.replica_id.clone(),
        event.event_id.clone(),
    )
    .map_err(|_| SyncCoreError::InvalidEnvelope)
}

pub fn compare_version(left: &VersionStamp, right: &VersionStamp) -> Ordering {
    left.cmp(right)
}

impl RoamingMergeState {
    pub fn seen(&self, event_id: &str) -> bool {
        self.seen_event_ids.contains(event_id)
    }

    pub fn tombstone(&self, entity_id: &str) -> Option<&VersionStamp> {
        self.tombstones.get(entity_id)
    }

    pub fn field_version(&self, entity_id: &str, field: &str) -> Option<&VersionStamp> {
        self.field_versions
            .get(&(entity_id.to_owned(), field.to_owned()))
    }

    pub fn plan_card_event(
        &mut self,
        event: &RoamingBoardEvent,
    ) -> Result<MergeDisposition, SyncCoreError> {
        if self.seen_event_ids.contains(&event.event_id) {
            return Ok(MergeDisposition::Duplicate);
        }
        self.seen_event_ids.insert(event.event_id.clone());
        let candidate = stamp_of(event)?;

        if event.operation == "card.delete" {
            let should_replace = self
                .tombstones
                .get(&event.entity_id)
                .is_none_or(|current| candidate > *current);
            if should_replace {
                self.tombstones
                    .insert(event.entity_id.clone(), candidate.clone());
                self.field_versions.insert(
                    (event.entity_id.clone(), "__lifecycle".to_owned()),
                    candidate,
                );
                return Ok(MergeDisposition::Delete);
            }
            return Ok(MergeDisposition::Stale);
        }

        if event.operation != "card.put" {
            return Err(SyncCoreError::UnsupportedOperation);
        }
        if self.tombstones.contains_key(&event.entity_id) {
            return Ok(MergeDisposition::BlockedByTombstone);
        }

        let mut winners = Vec::new();
        for field in &event.field_mask {
            let key = (event.entity_id.clone(), field.clone());
            let wins = self
                .field_versions
                .get(&key)
                .is_none_or(|current| candidate > *current);
            if wins {
                self.field_versions.insert(key, candidate.clone());
                winners.push(field.clone());
            }
        }
        if winners.is_empty() {
            Ok(MergeDisposition::Stale)
        } else {
            Ok(MergeDisposition::ApplyFields(winners))
        }
    }
}

pub fn derive_board_tag(board_key: &[u8], board_id: &str) -> Result<String, SyncCoreError> {
    if board_key.len() != 32 {
        return Err(SyncCoreError::InvalidBoardKey);
    }
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(board_key)
        .map_err(|_| SyncCoreError::InvalidBoardKey)?;
    mac.update(BOARD_TAG_DOMAIN);
    mac.update(&[0]);
    mac.update(board_id.as_bytes());
    Ok(URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes()))
}

pub fn seal_roaming_event(
    event: &RoamingBoardEvent,
    board_key: &[u8],
    board_tag: &str,
    nonce: &[u8],
) -> Result<RoamingCiphertextRecord, SyncCoreError> {
    if board_key.len() != 32 {
        return Err(SyncCoreError::InvalidBoardKey);
    }
    if nonce.len() != 24 {
        return Err(SyncCoreError::InvalidNonce);
    }
    if event.protocol_version != ROAMING_PROTOCOL_VERSION {
        return Err(SyncCoreError::UnsupportedProtocolVersion);
    }
    let cipher = XChaCha20Poly1305::new_from_slice(board_key)
        .map_err(|_| SyncCoreError::InvalidBoardKey)?;
    let plaintext = serde_json::to_vec(event).map_err(|_| SyncCoreError::Serialization)?;
    let ciphertext = cipher
        .encrypt(XNonce::from_slice(nonce), plaintext.as_ref())
        .map_err(|_| SyncCoreError::InvalidCiphertext)?;
    Ok(RoamingCiphertextRecord {
        version: ROAMING_RECORD_VERSION,
        board_tag: board_tag.to_owned(),
        nonce: URL_SAFE_NO_PAD.encode(nonce),
        ciphertext: URL_SAFE_NO_PAD.encode(ciphertext),
    })
}

pub fn open_roaming_event(
    record: &RoamingCiphertextRecord,
    board_key: &[u8],
    expected_board_tag: &str,
) -> Result<RoamingBoardEvent, SyncCoreError> {
    if record.version != ROAMING_RECORD_VERSION || record.board_tag != expected_board_tag {
        return Err(SyncCoreError::InvalidCiphertext);
    }
    if board_key.len() != 32 {
        return Err(SyncCoreError::InvalidBoardKey);
    }
    let nonce = URL_SAFE_NO_PAD
        .decode(&record.nonce)
        .map_err(|_| SyncCoreError::InvalidNonce)?;
    if nonce.len() != 24 {
        return Err(SyncCoreError::InvalidNonce);
    }
    let ciphertext = URL_SAFE_NO_PAD
        .decode(&record.ciphertext)
        .map_err(|_| SyncCoreError::InvalidCiphertext)?;
    let cipher = XChaCha20Poly1305::new_from_slice(board_key)
        .map_err(|_| SyncCoreError::InvalidBoardKey)?;
    let plaintext = cipher
        .decrypt(XNonce::from_slice(&nonce), ciphertext.as_ref())
        .map_err(|_| SyncCoreError::InvalidCiphertext)?;
    let event: RoamingBoardEvent =
        serde_json::from_slice(&plaintext).map_err(|_| SyncCoreError::Serialization)?;
    if event.protocol_version != ROAMING_PROTOCOL_VERSION {
        return Err(SyncCoreError::UnsupportedProtocolVersion);
    }
    Ok(event)
}

pub fn canonical_event_digest(event: &RoamingBoardEvent) -> Result<String, SyncCoreError> {
    let bytes = serde_json::to_vec(event).map_err(|_| SyncCoreError::Serialization)?;
    let digest = Sha256::digest(bytes);
    Ok(format!("{digest:x}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Deserialize)]
    #[serde(rename_all = "camelCase")]
    struct CryptoFixture {
        synthetic_board_key: String,
        event: RoamingBoardEvent,
        expected_board_tag: String,
        nonce: String,
        expected_ciphertext: String,
    }

    #[test]
    fn a10_sync_fixture_is_accepted_by_legacy_sync1_rules() {
        let fixture: SyncEnvelope = serde_json::from_str(include_str!(
            "../../../fixtures/protocol/sync-envelope-v1.json"
        ))
        .unwrap();
        assert_eq!(fixture.event.operation, "update");
        validate_sync_envelope(&fixture).unwrap();
    }

    #[test]
    fn a10_android_roaming_crypto_vector_matches_exactly() {
        let fixture: CryptoFixture = serde_json::from_str(include_str!(
            "../../../fixtures/protocol/roaming-crypto-vector-v1.json"
        ))
        .unwrap();
        let key = URL_SAFE_NO_PAD.decode(&fixture.synthetic_board_key).unwrap();
        let nonce = URL_SAFE_NO_PAD.decode(&fixture.nonce).unwrap();
        let tag = derive_board_tag(&key, &fixture.event.board_id).unwrap();
        assert_eq!(tag, fixture.expected_board_tag);
        let sealed = seal_roaming_event(&fixture.event, &key, &tag, &nonce).unwrap();
        assert_eq!(sealed.ciphertext, fixture.expected_ciphertext);
        assert_eq!(open_roaming_event(&sealed, &key, &tag).unwrap(), fixture.event);
    }

    #[test]
    fn a10_reorder_replay_and_tombstone_merge_is_deterministic() {
        let scope = RoamingScope {
            workspace_id: "workspace-a".into(),
            board_id: "board-a".into(),
            capability_epoch: 3,
        };
        let event = |id: &str, replica: &str, clock: u64, operation: &str, title: &str| {
            RoamingBoardEvent {
                protocol_version: ROAMING_PROTOCOL_VERSION.into(),
                event_id: id.into(),
                workspace_id: scope.workspace_id.clone(),
                board_id: scope.board_id.clone(),
                capability_epoch: 3,
                replica_id: replica.into(),
                replica_seq: clock,
                logical_clock: clock,
                entity_type: "card".into(),
                entity_id: "card-a".into(),
                operation: operation.into(),
                field_mask: if operation == "card.delete" {
                    vec!["__lifecycle".into()]
                } else {
                    vec!["title".into()]
                },
                payload: serde_json::json!({"card": {"title": title}}),
                occurred_at: "2026-09-13T00:00:00Z".into(),
            }
        };
        let old = event("event-a", "replica-z", 7, "card.put", "old");
        let newer = event("event-b", "replica-a", 8, "card.put", "newer");
        let delete = event("event-c", "replica-a", 9, "card.delete", "");
        for item in [&old, &newer, &delete] {
            validate_roaming_event(item, &scope).unwrap();
        }
        let mut state = RoamingMergeState::default();
        let mut shuffled = vec![delete.clone(), old.clone(), newer.clone(), newer.clone()];
        shuffled.sort_by_key(|item| stamp_of(item).unwrap());
        let results = shuffled
            .iter()
            .map(|item| state.plan_card_event(item).unwrap())
            .collect::<Vec<_>>();
        assert!(results.contains(&MergeDisposition::Delete));
        assert_eq!(state.tombstone("card-a").unwrap().event_id, "event-c");
        assert_eq!(state.plan_card_event(&old).unwrap(), MergeDisposition::Duplicate);
        let post_delete = event("event-d", "replica-z", 10, "card.put", "resurrect");
        assert_eq!(
            state.plan_card_event(&post_delete).unwrap(),
            MergeDisposition::BlockedByTombstone
        );
    }

    #[test]
    fn a10_capability_epoch_and_unknown_protocol_fail_closed() {
        let scope = RoamingScope {
            workspace_id: "workspace-a".into(),
            board_id: "board-a".into(),
            capability_epoch: 4,
        };
        let mut event: RoamingBoardEvent = serde_json::from_str(include_str!(
            "../../../fixtures/protocol/roaming-card-put-v1.json"
        ))
        .unwrap();
        event.workspace_id = scope.workspace_id.clone();
        event.board_id = scope.board_id.clone();
        event.capability_epoch = 3;
        assert_eq!(
            validate_roaming_event(&event, &scope),
            Err(SyncCoreError::InvalidCapabilityEpoch)
        );
        event.capability_epoch = 4;
        event.protocol_version = "p2p-kanban-roaming/2".into();
        assert_eq!(
            validate_roaming_event(&event, &scope),
            Err(SyncCoreError::UnsupportedProtocolVersion)
        );
    }
}
