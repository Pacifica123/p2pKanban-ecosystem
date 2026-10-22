//! Adding a device by QR through a relay mailbox: `p2p-kanban-rendezvous/1`.
//!
//! Pure protocol code that follows `contracts/rendezvous/1/SPEC.md`; the
//! executable reference is `tools/ecosystem/contract_ref.py`, and
//! `tests/ring_contract_vectors.rs` requires the same QR, derived values and
//! decrypted messages for every published vector.
use std::collections::BTreeMap;
use std::time::Duration;

use anyhow::{anyhow, bail, ensure, Context, Result};
use chacha20poly1305::{
    aead::{Aead, KeyInit, Payload},
    XChaCha20Poly1305, XNonce,
};
use hmac::{Hmac, Mac};
use nostr_sdk::prelude::*;
use rand::{rngs::OsRng, RngCore};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::ring::{self, b64url, canonical, unb64url};

pub const KIND_MAILBOX: u16 = 1991;
pub const QR_PREFIX: &str = "p2pkanban:rv1:";
/// A QR and its secret live at most this long after being shown.
pub const MAX_LIFETIME_SECS: u64 = 600;
/// Messages larger than this are split into parts.
pub const PART_BYTES: usize = 48 * 1024;
const MAILBOX_TAG: &str = "p2pkanban-rendezvous";

/// Refusal reasons, as written on the wire.
pub const REASONS: [&str; 10] = [
    "declined", "expired", "contested", "session-used", "ring-merge-unsupported",
    "key-removed", "sponsor-not-admin", "sponsor-stale", "joiner-outdated", "welcome-invalid",
];

/// Encode QR content as `p2pkanban:rv1:` + base64url(canonical JSON).
pub fn qr_encode(qr: &Value) -> String {
    format!("{QR_PREFIX}{}", b64url(canonical(qr).as_bytes()))
}

/// Decode and validate a scanned QR. A newer `rvN:` prefix is reported as such.
pub fn qr_decode(text: &str) -> Result<Value> {
    let text = text.trim();
    if let Some(rest) = text.strip_prefix("p2pkanban:rv") {
        if !text.starts_with(QR_PREFIX) && rest.split(':').next().is_some_and(|v| v.parse::<u32>().is_ok_and(|v| v > 1)) {
            bail!("QR от более новой версии приложения: обновите это устройство");
        }
    }
    let body = text.strip_prefix(QR_PREFIX).context("это не QR встречи p2pKanban")?;
    let qr: Value = serde_json::from_slice(&unb64url(body)?).context("QR повреждён")?;
    check_qr(&qr)?;
    Ok(qr)
}

fn hex64_ok(value: Option<&Value>) -> bool {
    value.and_then(Value::as_str).is_some_and(|k| k.len() == 64 && k.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')))
}

/// The shape rules of qr.schema.json.
pub fn check_qr(qr: &Value) -> Result<()> {
    ensure!(qr["v"] == 1, "QR другой версии");
    ensure!(matches!(qr["m"].as_str(), Some("invite" | "join")), "неизвестный режим QR");
    ensure!(hex64_ok(qr.get("k")), "в QR нет ключа устройства");
    let secret = unb64url(qr["s"].as_str().unwrap_or_default()).context("в QR нет секрета встречи")?;
    ensure!(secret.len() == 32, "секрет встречи — 32 байта");
    let relays = qr["r"].as_array().context("в QR нет relay")?;
    ensure!((1..=3).contains(&relays.len()), "в QR от 1 до 3 relay");
    ensure!(relays.iter().all(|r| r.as_str().is_some_and(|u| u.starts_with("wss://") && u.chars().count() <= 256)), "relay встречи — только wss://");
    let name = qr["n"].as_str().unwrap_or_default();
    ensure!((1..=64).contains(&name.chars().count()), "имя устройства в QR — от 1 до 64 символов");
    ensure!(matches!(qr["t"].as_str(), Some("web" | "android" | "arch")), "неизвестный вид устройства в QR");
    ensure!(qr["x"].as_u64().is_some(), "в QR нет срока действия");
    Ok(())
}

fn hmac_sha256(key: &[u8], data: &[u8]) -> [u8; 32] {
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key).expect("HMAC takes any key");
    mac.update(data);
    mac.finalize().into_bytes().into()
}

pub fn session_id(secret: &[u8]) -> String {
    b64url(&hmac_sha256(secret, b"p2p-kanban:rendezvous-id:v1"))
}

/// HKDF-SHA256(ikm = s, salt, info = "session-key"), 32 bytes: one expand block.
pub fn session_key(secret: &[u8]) -> [u8; 32] {
    let prk = hmac_sha256(b"p2p-kanban:rendezvous:v1", secret);
    hmac_sha256(&prk, b"session-key\x01")
}

/// Six digits both screens show, "ddd ddd".
pub fn confirm_code(session: &str, joiner: &str) -> String {
    let digest = Sha256::digest(format!("p2p-kanban:rendezvous-confirm:v1|{session}|{joiner}").as_bytes());
    let n = u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]) % 1_000_000;
    format!("{:03} {:03}", n / 1000, n % 1000)
}

fn aad(session: &str, sender: &str, part: usize, parts: usize) -> Vec<u8> {
    format!("p2p-kanban:rendezvous:v1|{session}|{sender}|{part}/{parts}").into_bytes()
}

/// A new QR: fresh 32-byte secret, `x` = now + lifetime (at most 10 minutes).
pub fn new_qr(mode: &str, shower: &str, name: &str, kind: &str, relays: &[String], now: u64, lifetime: u64) -> Result<(Value, Vec<u8>)> {
    let mut secret = [0u8; 32];
    OsRng.fill_bytes(&mut secret);
    let relays: Vec<&String> = relays.iter().filter(|r| r.starts_with("wss://")).take(3).collect();
    let qr = json!({"v": 1, "m": mode, "k": shower, "s": b64url(&secret), "r": relays,
        "n": name.chars().take(64).collect::<String>(), "t": kind, "x": now + lifetime.min(MAX_LIFETIME_SECS)});
    check_qr(&qr)?;
    Ok((qr, secret.to_vec()))
}

/// Signed mailbox events (`kind 1991`) carrying one message, split into parts when large.
pub fn mailbox_events(keys: &Keys, secret: &[u8], message: &Value, created_at: u64, expires_at: u64) -> Result<Vec<Value>> {
    let session = session_id(secret);
    ensure!(message["sessionId"] == session.as_str(), "message of another session");
    let cipher = XChaCha20Poly1305::new_from_slice(&session_key(secret)).map_err(|e| anyhow!("{e}"))?;
    let sender = keys.public_key().to_hex();
    let plain = canonical(message).into_bytes();
    let chunks: Vec<&[u8]> = if plain.is_empty() { vec![&plain[..]] } else { plain.chunks(PART_BYTES).collect() };
    let parts = chunks.len();
    let mut events = Vec::with_capacity(parts);
    for (index, chunk) in chunks.into_iter().enumerate() {
        let part = index + 1;
        let mut nonce = [0u8; 24];
        OsRng.fill_bytes(&mut nonce);
        let ciphertext = cipher
            .encrypt(XNonce::from_slice(&nonce), Payload { msg: chunk, aad: &aad(&session, &sender, part, parts) })
            .map_err(|_| anyhow!("could not seal the mailbox message"))?;
        let content = canonical(&json!({"version": 1, "nonce": b64url(&nonce), "ciphertext": b64url(&ciphertext)}));
        let tags = [
            Tag::parse(["s", session.as_str()])?,
            Tag::parse(["t", MAILBOX_TAG])?,
            Tag::parse(["part", &part.to_string(), &parts.to_string()])?,
            Tag::parse(["expiration", &expires_at.to_string()])?,
        ];
        let event = EventBuilder::new(Kind::Custom(KIND_MAILBOX), content)
            .tags(tags)
            .custom_created_at(Timestamp::from(created_at))
            .sign_with_keys(keys)?;
        events.push(serde_json::to_value(&event)?);
    }
    Ok(events)
}

/// A decrypted mailbox message and who signed it.
#[derive(Debug, Clone, PartialEq)]
pub struct Mail {
    pub sender: String,
    pub created_at: u64,
    pub message: Value,
}

fn tag_values<'a>(event: &'a Event, name: &str) -> Option<&'a [String]> {
    event.tags.iter().map(|t| t.as_slice()).find(|t| t.first().map(String::as_str) == Some(name)).map(|t| &t[1..])
}

/// Verify, decrypt and reassemble every message of this session. Foreign,
/// forged or incomplete events are skipped; the result is ordered by time and sender.
pub fn open_mailbox(events: &[Value], secret: &[u8]) -> Vec<Mail> {
    let session = session_id(secret);
    let Ok(cipher) = XChaCha20Poly1305::new_from_slice(&session_key(secret)) else { return Vec::new() };
    // (sender, created_at, parts) -> part -> bytes
    let mut groups: BTreeMap<(String, u64, usize), BTreeMap<usize, Vec<u8>>> = BTreeMap::new();
    for raw in events {
        let Ok(event) = serde_json::from_value::<Event>(raw.clone()) else { continue };
        if event.kind.as_u16() != KIND_MAILBOX || !event.verify_id() || !event.verify_signature() {
            continue;
        }
        if tag_values(&event, "s") != Some(&[session.clone()][..]) {
            continue;
        }
        let (part, parts) = match tag_values(&event, "part") {
            Some([i, n]) => match (i.parse::<usize>(), n.parse::<usize>()) {
                (Ok(i), Ok(n)) if i >= 1 && i <= n && n <= 64 => (i, n),
                _ => continue,
            },
            _ => (1, 1),
        };
        let sender = event.pubkey.to_hex();
        let Ok(body) = serde_json::from_str::<Value>(&event.content) else { continue };
        if body["version"] != 1 {
            continue;
        }
        let (Some(nonce), Some(ciphertext)) = (body["nonce"].as_str().and_then(|n| unb64url(n).ok()), body["ciphertext"].as_str().and_then(|c| unb64url(c).ok())) else { continue };
        if nonce.len() != 24 {
            continue;
        }
        let Ok(plain) = cipher.decrypt(XNonce::from_slice(&nonce), Payload { msg: &ciphertext, aad: &aad(&session, &sender, part, parts) }) else { continue };
        groups.entry((sender, event.created_at.as_secs(), parts)).or_default().insert(part, plain);
    }
    let mut mails: Vec<Mail> = groups.into_iter().filter_map(|((sender, created_at, parts), chunks)| {
        if chunks.len() != parts {
            return None;
        }
        let bytes: Vec<u8> = chunks.into_values().flatten().collect();
        let message: Value = serde_json::from_slice(&bytes).ok()?;
        (message["sessionId"] == session.as_str() && message["type"].is_string()).then_some(Mail { sender, created_at, message })
    }).collect();
    mails.sort_by(|a, b| (a.created_at, &a.sender).cmp(&(b.created_at, &b.sender)));
    mails
}

/// A refusal the sponsor (or joiner) sends, with an explanation for a person.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refusal {
    pub reason: &'static str,
    pub detail: String,
}

impl Refusal {
    fn new(reason: &'static str, detail: impl Into<String>) -> Self {
        Self { reason, detail: detail.into() }
    }

    pub fn message(&self, session: &str) -> Value {
        json!({"type": "refuse", "sessionId": session, "reason": self.reason, "detail": self.detail.chars().take(500).collect::<String>()})
    }
}

/// The joiner's hello this sponsor may answer, or why it must refuse.
///
/// `mails` is the opened mailbox, `qr` what was shown or scanned, `state` the
/// sponsor's folded ring, `fresh` whether its keyring matches the ring heads.
/// `Ok(None)` means there is nothing to answer yet.
pub fn sponsor_review(qr: &Value, mails: &[Mail], sponsor: &str, state: &Value, fresh: bool, now: u64) -> std::result::Result<Option<Value>, Refusal> {
    if qr["x"].as_u64().is_some_and(|x| now > x) {
        return Err(Refusal::new("expired", "Срок QR истёк (10 минут). Покажите новый код."));
    }
    let joiner_key = (qr["m"] == "join").then(|| qr["k"].as_str().unwrap_or_default());
    let hellos: Vec<&Mail> = mails.iter()
        .filter(|m| m.sender != sponsor && m.message["type"] == "hello")
        // In join mode the hello must come from the key in the QR; anything else is ignored.
        .filter(|m| joiner_key.is_none_or(|k| m.sender == k))
        .filter(|m| m.message["device"]["publicKey"] == m.sender.as_str())
        .collect();
    let senders: std::collections::BTreeSet<&str> = hellos.iter().map(|m| m.sender.as_str()).collect();
    if senders.len() > 1 {
        return Err(Refusal::new("contested", "В почтовый ящик пришли два разных устройства: QR мог увидеть кто-то ещё. Покажите новый код."));
    }
    let Some(hello) = hellos.last() else { return Ok(None) };
    let hello = &hello.message;
    let member = state["members"].as_array().into_iter().flatten().find(|m| m["publicKey"] == sponsor);
    if member.is_none_or(|m| m["role"] != "admin") {
        return Err(Refusal::new("sponsor-not-admin", "Добавлять устройства может только устройство кольца с ролью admin."));
    }
    if !fresh {
        return Err(Refusal::new("sponsor-stale", "Связка ключей этого устройства отстаёт от журнала кольца. Синхронизируйте кольцо и повторите."));
    }
    let joiner = hello["device"]["publicKey"].as_str().unwrap_or_default();
    if state["removed"].as_array().into_iter().flatten().any(|r| r["publicKey"] == joiner) {
        return Err(Refusal::new("key-removed", "Этот ключ устройства удалён из кольца. Удалённое устройство возвращается с новым ключом."));
    }
    let members = hello["ring"]["members"].as_u64().unwrap_or(0);
    let other = hello["ring"]["accountId"].as_str().is_some_and(|a| Some(a) != state["accountId"].as_str());
    if !hello["ring"].is_null() && members > 1 && other {
        let name = hello["device"]["name"].as_str().unwrap_or("Устройство");
        return Err(Refusal::new("ring-merge-unsupported",
            format!("{name} уже состоит в другом кольце из {members} устройств. Слияние колец пока не поддерживается.")));
    }
    let known: Vec<&str> = hello["software"]["protocols"].as_array().into_iter().flatten().filter_map(Value::as_str).collect();
    let missing: Vec<&str> = [ring::RING, ring::KEYRING, ring::RENDEZVOUS].into_iter().filter(|p| !known.contains(p)).collect();
    if !missing.is_empty() {
        return Err(Refusal::new("joiner-outdated", format!("Входящее устройство не знает {}: обновите его.", missing.join(", "))));
    }
    Ok(Some(hello.clone()))
}

/// What a joiner checks in `welcome` before adopting the ring. Returns the folded state.
pub fn verify_welcome(welcome: &Mail, qr: &Value, joiner: &str) -> std::result::Result<Value, Refusal> {
    let bad = |detail: &str| Refusal::new("welcome-invalid", detail.to_string());
    if qr["m"] == "invite" && qr["k"].as_str() != Some(welcome.sender.as_str()) {
        return Err(bad("welcome подписан не тем устройством, чей QR сканировали"));
    }
    let message = &welcome.message;
    let account = message["accountId"].as_str().ok_or_else(|| bad("в welcome нет accountId"))?;
    let entries = message["entries"].as_array().filter(|e| !e.is_empty() && e.len() <= ring::MAX_ENTRIES)
        .ok_or_else(|| bad("в welcome нет журнала кольца"))?;
    let state = ring::fold_ring(entries, Some(account)).map_err(|_| bad("журнал из welcome не сворачивается"))?;
    let role_of = |key: &str| state["members"].as_array().into_iter().flatten().find(|m| m["publicKey"] == key).map(|m| m["role"].clone());
    if role_of(joiner).is_none() {
        return Err(bad("этого устройства нет среди участников кольца из welcome"));
    }
    if role_of(&welcome.sender) != Some(json!("admin")) {
        return Err(bad("поручитель не admin кольца из welcome"));
    }
    let keyring = &message["keyring"];
    if keyring["protocol"] != ring::KEYRING || keyring["accountId"] != account || !keyring["items"].is_array() {
        return Err(bad("связка ключей из welcome другого аккаунта или повреждена"));
    }
    Ok(state)
}

// ---------------------------------------------------------------- relay

/// With the `memory-relay` feature, `wss://memory.invalid` is an in-process
/// mailbox, so the backend's meeting can be tested end to end without a relay.
#[cfg(feature = "memory-relay")]
pub mod memory {
    use std::sync::Mutex;

    use serde_json::Value;

    pub const URL: &str = "wss://memory.invalid";
    static EVENTS: Mutex<Vec<Value>> = Mutex::new(Vec::new());

    pub fn post(events: &[Value]) {
        EVENTS.lock().unwrap().extend(events.iter().cloned());
    }

    pub fn fetch(session: &str) -> Vec<Value> {
        EVENTS.lock().unwrap().iter()
            .filter(|e| e["tags"].as_array().into_iter().flatten().any(|t| t[0] == "s" && t[1] == session))
            .cloned().collect()
    }
}

/// Publish mailbox events; returns the relays that accepted at least one and the errors.
pub async fn post(secret_key: &str, relays: &[String], events: &[Value], timeout: Duration) -> Result<(Vec<String>, Vec<String>)> {
    #[cfg(feature = "memory-relay")]
    if relays == [memory::URL] {
        memory::post(events);
        return Ok((vec![memory::URL.into()], Vec::new()));
    }
    let client = Client::new(Keys::parse(secret_key.trim())?);
    for relay in relays {
        client.add_relay(relay).await.with_context(|| format!("could not add relay {relay}"))?;
    }
    client.connect().await;
    client.wait_for_connection(timeout.min(Duration::from_secs(5))).await;
    let mut accepted = std::collections::BTreeSet::new();
    let mut errors = Vec::new();
    for raw in events {
        let event: Event = serde_json::from_value(raw.clone())?;
        match client.send_event(&event).await {
            Ok(output) => {
                accepted.extend(output.success.iter().map(ToString::to_string));
                errors.extend(output.failed.iter().map(|(url, why)| format!("{url}: {why}")));
            }
            Err(error) => errors.push(error.to_string()),
        }
    }
    client.shutdown().await;
    Ok((accepted.into_iter().collect(), errors))
}

/// Fetch every mailbox event of a session.
pub async fn fetch(relays: &[String], session: &str, timeout: Duration) -> Result<Vec<Value>> {
    #[cfg(feature = "memory-relay")]
    if relays == [memory::URL] {
        return Ok(memory::fetch(session));
    }
    let client = Client::default();
    for relay in relays {
        client.add_relay(relay).await.with_context(|| format!("could not add relay {relay}"))?;
    }
    client.connect().await;
    client.wait_for_connection(timeout.min(Duration::from_secs(5))).await;
    let filter = Filter::new()
        .kind(Kind::Custom(KIND_MAILBOX))
        .custom_tag(SingleLetterTag::lowercase(Alphabet::S), session);
    let events = client.fetch_events(filter, timeout).await;
    client.shutdown().await;
    Ok(events?.iter().map(|e| serde_json::to_value(e).unwrap_or(Value::Null)).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn keys(n: u8) -> Keys {
        Keys::parse(&format!("{n:064x}")).unwrap()
    }

    #[test]
    fn large_welcome_is_split_and_reassembled() {
        let sponsor = keys(1);
        let secret = [9u8; 32];
        let session = session_id(&secret);
        let big = "я".repeat(70_000);
        let message = json!({"type": "welcome", "sessionId": session, "padding": big});
        let events = mailbox_events(&sponsor, &secret, &message, 1_791_244_900, 1_791_245_400).unwrap();
        assert_eq!(events.len(), 3, "140 KB of UTF-8 in 48 KiB parts");
        let mut shuffled = events.clone();
        shuffled.reverse();
        let mails = open_mailbox(&shuffled, &secret);
        assert_eq!(mails.len(), 1);
        assert_eq!(mails[0].message, message);
        assert!(open_mailbox(&events[..2], &secret).is_empty(), "an incomplete message is not delivered");
        assert!(open_mailbox(&events, &[8u8; 32]).is_empty(), "another session sees nothing");
    }

    #[test]
    fn new_qr_roundtrips_and_newer_prefix_is_named() {
        let (qr, secret) = new_qr("invite", &keys(1).public_key().to_hex(), "Узел", "web",
            &["wss://a.example".into(), "ws://plain.example".into()], 1_000, 3_600).unwrap();
        assert_eq!(qr["x"], 1_600, "never longer than ten minutes");
        assert_eq!(qr["r"], json!(["wss://a.example"]));
        assert_eq!(qr_decode(&qr_encode(&qr)).unwrap(), qr);
        assert_eq!(unb64url(qr["s"].as_str().unwrap()).unwrap(), secret);
        let newer = qr_decode("p2pkanban:rv2:abc").unwrap_err().to_string();
        assert!(newer.contains("более новой версии"), "{newer}");
        assert!(qr_decode("https://example.com").is_err());
    }
}
