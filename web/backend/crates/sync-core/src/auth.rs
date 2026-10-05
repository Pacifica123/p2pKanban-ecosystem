use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{SignedSyncEnvelope, SyncEnvelope};

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Error)]
pub enum AuthenticationError {
    #[error("could not serialize sync envelope: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("signing key must not be empty")]
    EmptyKey,
    #[error("signature is not valid base64url")]
    InvalidEncoding,
    #[error("sync envelope signature is invalid")]
    InvalidSignature,
    #[error("sync envelope digest does not match")]
    DigestMismatch,
    #[error("unsupported signature algorithm: {0}")]
    UnsupportedAlgorithm(String),
}

fn digest(bytes: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(bytes))
}

pub fn sign_envelope(
    envelope: SyncEnvelope,
    signer_key_id: impl Into<String>,
    key: &[u8],
) -> Result<SignedSyncEnvelope, AuthenticationError> {
    if key.is_empty() {
        return Err(AuthenticationError::EmptyKey);
    }
    let bytes = envelope.canonical_bytes()?;
    let mut mac = HmacSha256::new_from_slice(key).map_err(|_| AuthenticationError::EmptyKey)?;
    mac.update(&bytes);

    Ok(SignedSyncEnvelope {
        envelope,
        signer_key_id: signer_key_id.into(),
        algorithm: "hmac-sha256".to_string(),
        signature: URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes()),
        digest: digest(&bytes),
    })
}

pub fn verify_envelope(signed: &SignedSyncEnvelope, key: &[u8]) -> Result<(), AuthenticationError> {
    if signed.algorithm != "hmac-sha256" {
        return Err(AuthenticationError::UnsupportedAlgorithm(
            signed.algorithm.clone(),
        ));
    }
    if key.is_empty() {
        return Err(AuthenticationError::EmptyKey);
    }

    let bytes = signed.envelope.canonical_bytes()?;
    if signed.digest != digest(&bytes) {
        return Err(AuthenticationError::DigestMismatch);
    }

    let signature = URL_SAFE_NO_PAD
        .decode(&signed.signature)
        .map_err(|_| AuthenticationError::InvalidEncoding)?;
    let mut mac = HmacSha256::new_from_slice(key).map_err(|_| AuthenticationError::EmptyKey)?;
    mac.update(&bytes);
    mac.verify_slice(&signature)
        .map_err(|_| AuthenticationError::InvalidSignature)
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use crate::{ServerChangeEvent, SyncEnvelope};

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
                logical_clock: 2,
                base_server_order: Some(1),
                payload: json!({"title": "changed"}),
                metadata: json!({}),
                server_order: 2,
                accepted_at: "2026-07-25T20:00:00Z".to_string(),
                actor_user_id: None,
                actor_device_id: None,
            },
        );
        envelope.emitted_at = "2026-07-25T20:00:00Z".to_string();
        envelope
    }

    #[test]
    fn signature_round_trip_and_tamper_detection() {
        let mut signed = sign_envelope(envelope(), "workspace-key-v1", b"test board key").unwrap();
        verify_envelope(&signed, b"test board key").unwrap();

        signed.envelope.event.payload = json!({"title": "tampered"});
        assert!(matches!(
            verify_envelope(&signed, b"test board key"),
            Err(AuthenticationError::DigestMismatch)
        ));
    }
}
