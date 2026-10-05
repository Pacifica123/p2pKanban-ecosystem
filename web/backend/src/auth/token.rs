use std::time::{SystemTime, UNIX_EPOCH};

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use hmac::{Hmac, Mac};
use rand::{rngs::OsRng, RngCore};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::error::{AppError, AppResult};

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AccessTokenClaims {
    pub sub: String,
    pub sid: String,
    pub did: Option<String>,
    pub exp: u64,
}

#[derive(Debug, Clone)]
pub struct TokenPair {
    pub access_token: String,
    pub refresh_token: String,
}

impl AccessTokenClaims {
    pub fn user_id(&self) -> AppResult<Uuid> {
        Uuid::parse_str(&self.sub)
            .map_err(|_| AppError::unauthorized("Invalid access token subject"))
    }

    pub fn session_id(&self) -> AppResult<Uuid> {
        Uuid::parse_str(&self.sid)
            .map_err(|_| AppError::unauthorized("Invalid access token session"))
    }

    pub fn device_id(&self) -> AppResult<Option<Uuid>> {
        self.did
            .as_deref()
            .map(Uuid::parse_str)
            .transpose()
            .map_err(|_| AppError::unauthorized("Invalid access token device"))
    }
}

fn now_unix_seconds() -> AppResult<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| AppError::internal())
}

pub fn access_token_expiry_epoch(ttl_minutes: i64) -> AppResult<u64> {
    let now = now_unix_seconds()?;
    let ttl_seconds = (ttl_minutes.max(1) as u64) * 60;
    Ok(now + ttl_seconds)
}

pub fn sign_access_token(secret: &str, claims: &AccessTokenClaims) -> AppResult<String> {
    let payload = serde_json::to_vec(claims).map_err(|_| AppError::internal())?;
    let payload_b64 = URL_SAFE_NO_PAD.encode(payload);

    let mut mac =
        HmacSha256::new_from_slice(secret.as_bytes()).map_err(|_| AppError::internal())?;
    mac.update(payload_b64.as_bytes());
    let signature = mac.finalize().into_bytes();
    let signature_b64 = URL_SAFE_NO_PAD.encode(signature);

    Ok(format!("v1.{payload_b64}.{signature_b64}"))
}

pub fn verify_access_token(
    token: &str,
    current_secret: &str,
    previous_secrets: &[String],
) -> AppResult<AccessTokenClaims> {
    let mut parts = token.split('.');
    let version = parts
        .next()
        .ok_or_else(|| AppError::unauthorized("Access token is missing version"))?;
    let payload_b64 = parts
        .next()
        .ok_or_else(|| AppError::unauthorized("Access token payload missing"))?;
    let signature_b64 = parts
        .next()
        .ok_or_else(|| AppError::unauthorized("Access token signature missing"))?;

    if version != "v1" || parts.next().is_some() {
        return Err(AppError::unauthorized("Access token format is invalid"));
    }

    let signature = URL_SAFE_NO_PAD
        .decode(signature_b64)
        .map_err(|_| AppError::unauthorized("Access token signature is invalid"))?;

    let mut secrets =
        std::iter::once(current_secret).chain(previous_secrets.iter().map(String::as_str));
    let valid_signature = secrets.any(|secret| {
        let Ok(mut mac) = HmacSha256::new_from_slice(secret.as_bytes()) else {
            return false;
        };
        mac.update(payload_b64.as_bytes());
        mac.verify_slice(&signature).is_ok()
    });

    if !valid_signature {
        return Err(AppError::unauthorized("Access token signature mismatch"));
    }

    let payload = URL_SAFE_NO_PAD
        .decode(payload_b64)
        .map_err(|_| AppError::unauthorized("Access token payload is invalid"))?;
    let claims: AccessTokenClaims = serde_json::from_slice(&payload)
        .map_err(|_| AppError::unauthorized("Access token claims are invalid"))?;

    if claims.exp <= now_unix_seconds()? {
        return Err(AppError::unauthorized("Access token expired"));
    }

    Ok(claims)
}

pub fn generate_refresh_token() -> String {
    let mut bytes = [0_u8; 32];
    OsRng.fill_bytes(&mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}

pub fn hash_opaque_token(token: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(token.as_bytes());
    format!("{:x}", hasher.finalize())
}
