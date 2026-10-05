use std::str::FromStr;

use anyhow::{anyhow, bail, Context, Result};
use iroh::{endpoint::presets, Endpoint, EndpointAddr, PublicKey, RelayUrl};
use p2p_kanban_sync_core::{validate_envelope, SignedSyncEnvelope};
use serde::{Deserialize, Serialize};

pub const P2P_KANBAN_ALPN: &[u8] = b"p2p-kanban/sync/1";
pub const MAX_FRAME_BYTES: usize = 4 * 1024 * 1024;

#[derive(Debug, Clone)]
pub struct IrohTransportConfig {
    pub peers: Vec<IrohPeerConfig>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IrohPeerConfig {
    pub endpoint_id: String,
    #[serde(default)]
    pub relay_url: Option<String>,
    #[serde(default)]
    pub direct_addresses: Vec<String>,
}

impl IrohPeerConfig {
    pub fn endpoint_addr(&self) -> Result<EndpointAddr> {
        let endpoint_id = PublicKey::from_str(&self.endpoint_id)
            .with_context(|| format!("invalid Iroh endpoint id: {}", self.endpoint_id))?;
        let mut address = EndpointAddr::new(endpoint_id);
        if let Some(relay_url) = self.relay_url.as_deref() {
            address = address.with_relay_url(
                RelayUrl::from_str(relay_url)
                    .with_context(|| format!("invalid Iroh relay URL: {relay_url}"))?,
            );
        }
        for direct_address in &self.direct_addresses {
            address = address.with_ip_addr(
                direct_address
                    .parse()
                    .with_context(|| format!("invalid Iroh direct address: {direct_address}"))?,
            );
        }
        Ok(address)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IrohDeliveryReceipt {
    pub attempted_peers: usize,
    pub delivered_peers: usize,
    pub failed_peers: Vec<String>,
}

#[derive(Clone)]
pub struct IrohTransport {
    endpoint: Endpoint,
    peers: Vec<EndpointAddr>,
}

impl IrohTransport {
    pub async fn bind(config: IrohTransportConfig) -> Result<Self> {
        let peers = config
            .peers
            .iter()
            .map(IrohPeerConfig::endpoint_addr)
            .collect::<Result<Vec<_>>>()?;
        let endpoint = Endpoint::builder(presets::N0)
            .alpns(vec![P2P_KANBAN_ALPN.to_vec()])
            .bind()
            .await
            .context("could not bind Iroh endpoint")?;
        Ok(Self { endpoint, peers })
    }

    pub async fn send(&self, envelope: &SignedSyncEnvelope) -> Result<IrohDeliveryReceipt> {
        validate_envelope(&envelope.envelope).context("refusing to send invalid sync envelope")?;
        let frame = encode_frame(envelope)?;
        let mut delivered_peers = 0;
        let mut failed_peers = Vec::new();

        for peer in &self.peers {
            match self.send_to_peer(peer.clone(), &frame).await {
                Ok(()) => delivered_peers += 1,
                Err(error) => failed_peers.push(format!("{peer:?}: {error:#}")),
            }
        }

        Ok(IrohDeliveryReceipt {
            attempted_peers: self.peers.len(),
            delivered_peers,
            failed_peers,
        })
    }

    async fn send_to_peer(&self, peer: EndpointAddr, frame: &[u8]) -> Result<()> {
        let connection = self
            .endpoint
            .connect(peer, P2P_KANBAN_ALPN)
            .await
            .context("could not connect to Iroh peer")?;
        let mut stream = connection
            .open_uni()
            .await
            .context("could not open Iroh unidirectional stream")?;
        stream
            .write_all(frame)
            .await
            .context("could not write Iroh sync frame")?;
        stream
            .finish()
            .context("could not finish Iroh sync stream")?;
        Ok(())
    }

    pub async fn accept_one(&self) -> Result<SignedSyncEnvelope> {
        let incoming = self
            .endpoint
            .accept()
            .await
            .ok_or_else(|| anyhow!("Iroh endpoint has been closed"))?;
        let connection = incoming.await.context("incoming Iroh connection failed")?;
        let mut stream = connection
            .accept_uni()
            .await
            .context("could not accept Iroh sync stream")?;
        let bytes = stream
            .read_to_end(MAX_FRAME_BYTES + 4)
            .await
            .context("could not read Iroh sync frame")?;
        decode_frame(&bytes)
    }

    pub async fn close(&self) {
        self.endpoint.close().await;
    }
}

pub fn encode_frame(envelope: &SignedSyncEnvelope) -> Result<Vec<u8>> {
    let payload = serde_json::to_vec(envelope).context("could not serialize Iroh sync envelope")?;
    if payload.len() > MAX_FRAME_BYTES {
        bail!("Iroh sync frame exceeds {MAX_FRAME_BYTES} bytes");
    }

    let length = u32::try_from(payload.len()).context("Iroh sync frame length overflow")?;
    let mut frame = Vec::with_capacity(4 + payload.len());
    frame.extend_from_slice(&length.to_be_bytes());
    frame.extend_from_slice(&payload);
    Ok(frame)
}

pub fn decode_frame(frame: &[u8]) -> Result<SignedSyncEnvelope> {
    if frame.len() < 4 {
        bail!("Iroh sync frame is shorter than its length prefix");
    }
    let length =
        u32::from_be_bytes(frame[..4].try_into().expect("checked four-byte prefix")) as usize;
    if length > MAX_FRAME_BYTES {
        bail!("Iroh sync frame exceeds {MAX_FRAME_BYTES} bytes");
    }
    if frame.len() != length + 4 {
        bail!("Iroh sync frame length does not match payload");
    }

    let envelope: SignedSyncEnvelope =
        serde_json::from_slice(&frame[4..]).context("Iroh sync frame contains invalid JSON")?;
    validate_envelope(&envelope.envelope)
        .context("Iroh sync frame contains an invalid envelope")?;
    Ok(envelope)
}

#[cfg(test)]
mod tests {
    use p2p_kanban_sync_core::{sign_envelope, ServerChangeEvent, SyncEnvelope};
    use serde_json::json;

    use super::*;

    fn signed_envelope() -> SignedSyncEnvelope {
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
                logical_clock: 4,
                base_server_order: Some(8),
                payload: json!({"title": "direct path"}),
                metadata: json!({}),
                server_order: 9,
                accepted_at: "2026-07-25T20:00:00Z".to_string(),
                actor_user_id: None,
                actor_device_id: None,
            },
        );
        envelope.emitted_at = "2026-07-25T20:00:00Z".to_string();
        sign_envelope(envelope, "test", b"test-key").unwrap()
    }

    #[test]
    fn frame_round_trip_is_transport_only() {
        let original = signed_envelope();
        let frame = encode_frame(&original).unwrap();
        let decoded = decode_frame(&frame).unwrap();
        assert_eq!(decoded, original);
    }

    #[test]
    fn rejects_truncated_frame() {
        let mut frame = encode_frame(&signed_envelope()).unwrap();
        frame.pop();
        assert!(decode_frame(&frame).is_err());
    }
}
