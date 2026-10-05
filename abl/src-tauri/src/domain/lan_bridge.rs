use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use chacha20poly1305::{
    aead::{Aead, KeyInit, Payload},
    XChaCha20Poly1305, XNonce,
};
use serde::{Deserialize, Serialize};

pub const LAN_BRIDGE_PROTOCOL: &str = "p2p-kanban-lan-bridge/1";
pub const LAN_PROVISION_PROTOCOL: &str = "p2p-kanban-lan-provision/1";
pub const LAN_BRIDGE_PATH: &str = "/v1/p2pkanban/pair";
pub const LAN_BRIDGE_AAD: &[u8] = b"p2p-kanban-lan-bridge/1\0POST\0/v1/p2pkanban/pair";
pub const LAN_BRIDGE_TOKEN_BYTES: usize = 32;
pub const LAN_BRIDGE_NONCE_BYTES: usize = 24;
pub const LAN_BRIDGE_MIN_TTL_SECS: u64 = 30;
pub const LAN_BRIDGE_DEFAULT_TTL_SECS: u64 = 300;
pub const LAN_BRIDGE_MAX_TTL_SECS: u64 = 600;
pub const LAN_BRIDGE_MAX_PLAINTEXT_BYTES: usize = 8 * 1024 * 1024;
pub const LAN_BRIDGE_MAX_HTTP_BODY_BYTES: usize = 12 * 1024 * 1024;
pub const LAN_BRIDGE_MAX_HEADER_BYTES: usize = 8 * 1024;
pub const LAN_BRIDGE_MAX_ATTEMPTS: u32 = 8;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LanBridgeValidationError {
    InvalidBindAddress,
    InvalidTtl,
    InvalidEnvelope,
    WrongProtocol,
    InvalidNonce,
    InvalidCiphertext,
    AuthenticationFailed,
    Oversized,
    InvalidProvisionPackage,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LanBridgeLifecycle {
    Stopped,
    Listening,
    Completed,
    Expired,
    Failed,
}

impl LanBridgeLifecycle {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Stopped => "stopped",
            Self::Listening => "listening",
            Self::Completed => "completed",
            Self::Expired => "expired",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LanBridgeStatus {
    pub lifecycle: LanBridgeLifecycle,
    pub bind_address: Option<String>,
    pub endpoint: Option<String>,
    pub expires_at_unix: Option<i64>,
    pub attempts: u32,
    pub last_result: Option<String>,
}

impl Default for LanBridgeStatus {
    fn default() -> Self {
        Self {
            lifecycle: LanBridgeLifecycle::Stopped,
            bind_address: None,
            endpoint: None,
            expires_at_unix: None,
            attempts: 0,
            last_result: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LanBridgeStartRequest {
    pub bind_address: String,
    pub ttl_secs: u64,
}

impl LanBridgeStartRequest {
    pub fn validated(bind_address: &str, ttl_secs: u64) -> Result<Self, LanBridgeValidationError> {
        let bind_address = bind_address.trim();
        if bind_address.is_empty() || bind_address.len() > 64 || bind_address.bytes().any(|byte| byte.is_ascii_control()) {
            return Err(LanBridgeValidationError::InvalidBindAddress);
        }
        if !(LAN_BRIDGE_MIN_TTL_SECS..=LAN_BRIDGE_MAX_TTL_SECS).contains(&ttl_secs) {
            return Err(LanBridgeValidationError::InvalidTtl);
        }
        Ok(Self {
            bind_address: bind_address.to_owned(),
            ttl_secs,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct LanBridgeEnvelopeV1 {
    protocol: String,
    nonce: String,
    ciphertext: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LanProvisionPackageV1 {
    pub protocol: String,
    pub kind: String,
    pub grant: serde_json::Value,
    pub portable_bundle: serde_json::Value,
    pub board_id: String,
    pub board_key: String,
}

impl LanProvisionPackageV1 {
    pub fn parse(raw: &[u8]) -> Result<Self, LanBridgeValidationError> {
        if raw.is_empty() || raw.len() > LAN_BRIDGE_MAX_PLAINTEXT_BYTES {
            return Err(LanBridgeValidationError::Oversized);
        }
        let package: Self = serde_json::from_slice(raw)
            .map_err(|_| LanBridgeValidationError::InvalidProvisionPackage)?;
        if package.protocol != LAN_PROVISION_PROTOCOL || package.kind != "device-link-v2-provision" {
            return Err(LanBridgeValidationError::WrongProtocol);
        }
        if package.board_id.trim().is_empty() {
            return Err(LanBridgeValidationError::InvalidProvisionPackage);
        }
        Ok(package)
    }

    pub fn decode_board_key(&self) -> Result<Vec<u8>, LanBridgeValidationError> {
        decode_exact_32(&self.board_key)
    }
}

fn decode_exact_32(value: &str) -> Result<Vec<u8>, LanBridgeValidationError> {
    let bytes = URL_SAFE_NO_PAD
        .decode(value)
        .map_err(|_| LanBridgeValidationError::InvalidProvisionPackage)?;
    if bytes.len() != 32 {
        return Err(LanBridgeValidationError::InvalidProvisionPackage);
    }
    Ok(bytes)
}

pub fn encode_capability_token(token: &[u8; LAN_BRIDGE_TOKEN_BYTES]) -> String {
    URL_SAFE_NO_PAD.encode(token)
}

pub fn open_lan_bridge_envelope(
    raw: &[u8],
    token: &[u8; LAN_BRIDGE_TOKEN_BYTES],
) -> Result<Vec<u8>, LanBridgeValidationError> {
    if raw.is_empty() || raw.len() > LAN_BRIDGE_MAX_HTTP_BODY_BYTES {
        return Err(LanBridgeValidationError::Oversized);
    }
    let envelope: LanBridgeEnvelopeV1 = serde_json::from_slice(raw)
        .map_err(|_| LanBridgeValidationError::InvalidEnvelope)?;
    if envelope.protocol != LAN_BRIDGE_PROTOCOL {
        return Err(LanBridgeValidationError::WrongProtocol);
    }
    let nonce = URL_SAFE_NO_PAD
        .decode(envelope.nonce)
        .map_err(|_| LanBridgeValidationError::InvalidNonce)?;
    if nonce.len() != LAN_BRIDGE_NONCE_BYTES {
        return Err(LanBridgeValidationError::InvalidNonce);
    }
    let ciphertext = URL_SAFE_NO_PAD
        .decode(envelope.ciphertext)
        .map_err(|_| LanBridgeValidationError::InvalidCiphertext)?;
    if ciphertext.len() > LAN_BRIDGE_MAX_PLAINTEXT_BYTES + 32 {
        return Err(LanBridgeValidationError::Oversized);
    }
    let cipher = XChaCha20Poly1305::new_from_slice(token)
        .map_err(|_| LanBridgeValidationError::AuthenticationFailed)?;
    cipher
        .decrypt(
            XNonce::from_slice(&nonce),
            Payload {
                msg: &ciphertext,
                aad: LAN_BRIDGE_AAD,
            },
        )
        .map_err(|_| LanBridgeValidationError::AuthenticationFailed)
        .and_then(|plaintext| {
            if plaintext.len() > LAN_BRIDGE_MAX_PLAINTEXT_BYTES {
                Err(LanBridgeValidationError::Oversized)
            } else {
                Ok(plaintext)
            }
        })
}

/// Native-only helper used by the A14 host probe and Rust tests. It is not
/// registered as a Tauri command and never exposes the bridge key to WebView
/// beyond the explicit one-time capability returned when the user starts it.
pub fn seal_lan_bridge_payload(
    plaintext: &[u8],
    token: &[u8; LAN_BRIDGE_TOKEN_BYTES],
    nonce: &[u8; LAN_BRIDGE_NONCE_BYTES],
) -> Result<Vec<u8>, LanBridgeValidationError> {
    if plaintext.is_empty() || plaintext.len() > LAN_BRIDGE_MAX_PLAINTEXT_BYTES {
        return Err(LanBridgeValidationError::Oversized);
    }
    let cipher = XChaCha20Poly1305::new_from_slice(token)
        .map_err(|_| LanBridgeValidationError::AuthenticationFailed)?;
    let ciphertext = cipher
        .encrypt(
            XNonce::from_slice(nonce),
            Payload {
                msg: plaintext,
                aad: LAN_BRIDGE_AAD,
            },
        )
        .map_err(|_| LanBridgeValidationError::AuthenticationFailed)?;
    serde_json::to_vec(&LanBridgeEnvelopeV1 {
        protocol: LAN_BRIDGE_PROTOCOL.to_owned(),
        nonce: URL_SAFE_NO_PAD.encode(nonce),
        ciphertext: URL_SAFE_NO_PAD.encode(ciphertext),
    })
    .map_err(|_| LanBridgeValidationError::InvalidEnvelope)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a14_envelope_is_confidential_authenticated_bounded_and_versioned() {
        let token = [7_u8; LAN_BRIDGE_TOKEN_BYTES];
        let nonce = [9_u8; LAN_BRIDGE_NONCE_BYTES];
        let plaintext = br#"{"kind":"probe"}"#;
        let envelope = seal_lan_bridge_payload(plaintext, &token, &nonce).unwrap();
        assert_eq!(open_lan_bridge_envelope(&envelope, &token).unwrap(), plaintext);

        let mut wrong = token;
        wrong[0] ^= 1;
        assert_eq!(
            open_lan_bridge_envelope(&envelope, &wrong),
            Err(LanBridgeValidationError::AuthenticationFailed)
        );
    }

    #[test]
    fn a14_ttl_and_provision_shape_fail_closed() {
        assert!(LanBridgeStartRequest::validated("192.168.1.2", 30).is_ok());
        assert_eq!(
            LanBridgeStartRequest::validated("192.168.1.2", 29),
            Err(LanBridgeValidationError::InvalidTtl)
        );
        assert_eq!(
            LanBridgeStartRequest::validated("192.168.1.2", 601),
            Err(LanBridgeValidationError::InvalidTtl)
        );
        assert!(LanProvisionPackageV1::parse(br#"{"protocol":"wrong"}"#).is_err());
        let smuggled = br#"{"protocol":"p2p-kanban-lan-provision/1","kind":"device-link-v2-provision","grant":{},"portableBundle":{},"boardId":"018f0000-0000-7000-8000-000000000002","boardKey":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","devicePrivateKey":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}"#;
        assert!(LanProvisionPackageV1::parse(smuggled).is_err());
    }

    #[test]
    fn a14_golden_vector_is_stable_and_unknown_version_rejected() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../fixtures/protocol/lan-bridge-v1-golden.json"
        ))
        .unwrap();
        let token_vec = URL_SAFE_NO_PAD.decode(fixture["token"].as_str().unwrap()).unwrap();
        let nonce_vec = URL_SAFE_NO_PAD.decode(fixture["nonce"].as_str().unwrap()).unwrap();
        let token: [u8; LAN_BRIDGE_TOKEN_BYTES] = token_vec.try_into().unwrap();
        let nonce: [u8; LAN_BRIDGE_NONCE_BYTES] = nonce_vec.try_into().unwrap();
        let plaintext = fixture["plaintextUtf8"].as_str().unwrap().as_bytes();
        let envelope = seal_lan_bridge_payload(plaintext, &token, &nonce).unwrap();
        assert_eq!(
            String::from_utf8(envelope.clone()).unwrap(),
            fixture["envelopeJson"].as_str().unwrap()
        );
        assert_eq!(open_lan_bridge_envelope(&envelope, &token).unwrap(), plaintext);

        let mut unknown: serde_json::Value = serde_json::from_slice(&envelope).unwrap();
        unknown["protocol"] = serde_json::Value::String("p2p-kanban-lan-bridge/2".into());
        assert_eq!(
            open_lan_bridge_envelope(&serde_json::to_vec(&unknown).unwrap(), &token),
            Err(LanBridgeValidationError::WrongProtocol)
        );
    }

}
