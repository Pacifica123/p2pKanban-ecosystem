//! Public device-bound owner delegation and encrypted node-link transfer.
use anyhow::{ensure, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use nostr_sdk::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
pub const PROTOCOL: &str = "p2p-kanban-device-link/2";
pub const GRANT_KIND: u16 = 27780;
pub const REQUEST_KIND: u16 = 27781;
pub const RESPONSE_KIND: u16 = 27782;
pub const MAX_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_DEPTH: usize = 8;
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Grant {
    pub protocol: String,
    pub workspace_id: String,
    pub board_id: String,
    pub user_id: String,
    pub epoch: i64,
    pub subject: String,
    pub can_delegate: bool,
    pub parent_id: Option<String>,
    pub expires_at: u64,
}
pub fn now() -> u64 {
    Timestamp::now().as_secs()
}
pub fn public_key(secret: &str) -> Result<String> {
    Ok(Keys::parse(secret)?.public_key().to_hex())
}
pub fn sign(secret: &str, kind: u16, content: &Value) -> Result<Value> {
    Ok(serde_json::to_value(
        EventBuilder::new(Kind::Custom(kind), serde_json::to_string(content)?)
            .sign_with_keys(&Keys::parse(secret)?)?,
    )?)
}
pub fn checked_event(raw: &Value, kind: u16) -> Result<(String, String, Value)> {
    let e: Event = serde_json::from_value(raw.clone())?;
    ensure!(e.kind == Kind::Custom(kind), "wrong event kind");
    e.verify()?;
    ensure!(e.created_at.as_secs() <= now() + 60, "event from future");
    Ok((
        e.pubkey.to_hex(),
        e.id.to_hex(),
        serde_json::from_str(&e.content)?,
    ))
}
pub fn verify_chain(chain: &[Value], subject: &str, at: u64) -> Result<(String, Grant)> {
    ensure!(
        !chain.is_empty() && chain.len() <= MAX_DEPTH,
        "invalid delegation depth"
    );
    let mut parent: Option<(String, Grant)> = None;
    let mut root = String::new();
    for raw in chain {
        let (signer, id, content) = checked_event(raw, GRANT_KIND)?;
        ensure!(raw.get("created_at").and_then(Value::as_u64).is_some_and(|issued| issued <= at), "delegation issued after event");
        let g: Grant = serde_json::from_value(content)?;
        ensure!(
            g.protocol == PROTOCOL && g.epoch > 0 && g.expires_at > at,
            "expired or invalid delegation"
        );
        PublicKey::from_hex(&g.subject)?;
        if let Some((pid, p)) = &parent {
            ensure!(
                p.can_delegate && signer == p.subject && g.parent_id.as_ref() == Some(pid),
                "issuer cannot delegate"
            );
            ensure!(
                g.board_id == p.board_id
                    && g.workspace_id == p.workspace_id
                    && g.user_id == p.user_id
                    && g.epoch == p.epoch
                    && g.expires_at <= p.expires_at,
                "delegation escalates scope"
            );
        } else {
            ensure!(g.parent_id.is_none(), "root has a parent");
            root = signer;
        }
        parent = Some((id, g));
    }
    let (_, g) = parent.unwrap();
    ensure!(g.subject == subject, "grant belongs to another device");
    Ok((root, g))
}
/// Existing epoch membership survives invitation expiry; new enrollment does not.
pub fn verify_replication_chain(chain: &[Value], subject: &str, signed_at: u64) -> Result<(String, Grant)> {
    let enrolled = chain.last().and_then(|v| v.get("created_at")).and_then(Value::as_u64);
    ensure!(enrolled.is_some_and(|at| at <= signed_at), "event predates enrollment");
    verify_chain(chain, subject, enrolled.unwrap())
}
pub fn extend(secret: &str, chain: &[Value], subject: &str) -> Result<Vec<Value>> {
    let (_, mut g) = verify_chain(chain, &public_key(secret)?, now())?;
    ensure!(g.can_delegate && chain.len() < MAX_DEPTH, "cannot delegate");
    g.subject = subject.into();
    g.parent_id = Some(chain.last().unwrap()["id"].as_str().unwrap().into());
    let mut c = chain.to_vec();
    c.push(sign(secret, GRANT_KIND, &serde_json::to_value(g)?)?);
    Ok(c)
}
// The signature binds the complete ordered ciphertext list. Each NIP-44 message stays below 64 KiB.
pub fn encrypt(secret: &str, recipient: &str, payload: &Value) -> Result<Vec<String>> {
    let bytes = serde_json::to_vec(payload)?;
    ensure!(bytes.len() <= MAX_BYTES, "snapshot exceeds 8 MiB");
    let k = Keys::parse(secret)?;
    let p = PublicKey::from_hex(recipient)?;
    bytes
        .chunks(24000)
        .map(|b| {
            Ok(nip44::encrypt(
                k.secret_key(),
                &p,
                STANDARD.encode(b),
                nip44::Version::V2,
            )?)
        })
        .collect()
}
pub fn decrypt(secret: &str, sender: &str, parts: &[String]) -> Result<Value> {
    ensure!(
        !parts.is_empty() && parts.len() <= 350,
        "invalid chunk count"
    );
    let k = Keys::parse(secret)?;
    let p = PublicKey::from_hex(sender)?;
    let mut bytes = Vec::new();
    for part in parts {
        ensure!(part.len() < 66000, "chunk too large");
        bytes.extend(STANDARD.decode(nip44::decrypt(k.secret_key(), &p, part)?)?);
        ensure!(bytes.len() <= MAX_BYTES, "snapshot too large");
    }
    Ok(serde_json::from_slice(&bytes)?)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn key(n: u8) -> String {
        format!("{n:064x}")
    }
    #[test]
    fn scope_and_device_bound() {
        let a = key(1);
        let b = key(2);
        let c = key(3);
        let g = Grant {
            protocol: PROTOCOL.into(),
            workspace_id: "w".into(),
            board_id: "b".into(),
            user_id: "u".into(),
            epoch: 2,
            subject: public_key(&b).unwrap(),
            can_delegate: true,
            parent_id: None,
            expires_at: now() + 3600,
        };
        let root = vec![sign(&a, GRANT_KIND, &serde_json::to_value(g).unwrap()).unwrap()];
        let chain = extend(&b, &root, &public_key(&c).unwrap()).unwrap();
        assert!(verify_chain(&chain, &public_key(&c).unwrap(), now()).is_ok());
        assert!(verify_chain(&chain, &public_key(&b).unwrap(), now()).is_err());
        assert!(verify_chain(&chain, &public_key(&c).unwrap(), now() + 4000).is_err());
        assert!(verify_replication_chain(&chain, &public_key(&c).unwrap(), now()+4000).is_ok());
        assert!(verify_replication_chain(&chain, &public_key(&c).unwrap(), 0).is_err());
        let mut bad = chain.clone();
        bad[1]["content"] = Value::String("{}".into());
        assert!(verify_chain(&bad, &public_key(&c).unwrap(), now()).is_err());
        assert!(extend(&c, &root, &public_key(&a).unwrap()).is_err());
    }
    #[test]
    fn encryption_roundtrip() {
        let payload = serde_json::json!({"text":"Привет 🌍".repeat(16000)});
        let c = encrypt(&key(1), &public_key(&key(2)).unwrap(), &payload).unwrap();
        assert!(c.len() > 1);
        assert_eq!(
            decrypt(&key(2), &public_key(&key(1)).unwrap(), &c).unwrap(),
            payload
        );
        assert!(decrypt(&key(3), &public_key(&key(1)).unwrap(), &c).is_err());
    }
}
