//! Account ring of devices: `p2p-kanban-account-ring/1` and `p2p-kanban-keyring/1`.
//!
//! Pure protocol code that follows `contracts/account-ring/1/SPEC.md` and
//! `contracts/keyring/1/SPEC.md`. The executable reference is
//! `tools/ecosystem/contract_ref.py`; `tests/ring_contract_vectors.rs` requires
//! the same results for every published vector.
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::time::Duration;

use anyhow::{anyhow, bail, ensure, Context, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use chacha20poly1305::{
    aead::{Aead, KeyInit, Payload},
    XChaCha20Poly1305, XNonce,
};
use hmac::{Hmac, Mac};
use nostr_sdk::prelude::*;
use rand::{rngs::OsRng, RngCore};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

/// Device key type, re-exported so the backend does not depend on nostr-sdk directly.
pub use nostr_sdk::prelude::Keys as DeviceKeys;

pub const RING: &str = "p2p-kanban-account-ring/1";
pub const KEYRING: &str = "p2p-kanban-keyring/1";
pub const RENDEZVOUS: &str = "p2p-kanban-rendezvous/1";
pub const ROAMING: &str = "p2p-kanban-roaming/1";
pub const KIND_RING_ENTRY: u16 = 27790;
pub const KIND_RING_LOG: u16 = 31990;
pub const KIND_KEYRING: u16 = 31991;
pub const KIND_PRESENCE: u16 = 31992;
pub const MAX_ENTRIES: usize = 1024;
pub const MAX_ENTRY_CONTENT: usize = 16 * 1024;
pub const MAX_PARENTS: usize = 16;
pub const MAX_RECIPIENTS: usize = 64;
const ENTRY_TYPES: [&str; 5] = ["genesis", "add", "remove", "rename", "relays"];
const RING_PROTOCOLS: [&str; 3] = [RING, KEYRING, RENDEZVOUS];

/// Canonical JSON: sorted keys, no whitespace, UTF-8 as is.
pub fn canonical(value: &Value) -> String {
    fn write(value: &Value, out: &mut String) {
        match value {
            Value::Object(map) => {
                out.push('{');
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort();
                for (index, key) in keys.into_iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    out.push_str(&Value::String(key.clone()).to_string());
                    out.push(':');
                    write(&map[key], out);
                }
                out.push('}');
            }
            Value::Array(items) => {
                out.push('[');
                for (index, item) in items.iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    write(item, out);
                }
                out.push(']');
            }
            other => out.push_str(&other.to_string()),
        }
    }
    let mut out = String::new();
    write(value, &mut out);
    out
}

pub fn b64url(bytes: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(bytes)
}

pub fn unb64url(text: &str) -> Result<Vec<u8>> {
    ensure!(!text.contains('='), "base64url without padding expected");
    Ok(URL_SAFE_NO_PAD.decode(text)?)
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes).iter().map(|b| format!("{b:02x}")).collect()
}

pub fn account_tag(account_id: &str) -> Result<String> {
    let key: Vec<u8> = (0..account_id.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(account_id.get(i..i + 2).unwrap_or("zz"), 16))
        .collect::<std::result::Result<_, _>>()
        .context("account id must be hex")?;
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(&key).map_err(|e| anyhow!("{e}"))?;
    mac.update(b"p2p-kanban:account-tag:v1");
    Ok(b64url(&mac.finalize().into_bytes()))
}

fn event_value(event: &Event) -> Value {
    json!({
        "id": event.id.to_hex(), "pubkey": event.pubkey.to_hex(),
        "created_at": event.created_at.as_secs(), "kind": event.kind.as_u16(),
        "tags": event.tags.iter().map(|t| t.as_slice().to_vec()).collect::<Vec<_>>(),
        "content": event.content, "sig": event.sig.to_string(),
    })
}

/// Sign a ring entry (`kind 27790`, no tags). `protocol` is added when absent.
pub fn make_entry(keys: &Keys, mut body: Map<String, Value>, created_at: u64) -> Result<Value> {
    body.entry("protocol").or_insert_with(|| Value::String(RING.into()));
    let event = EventBuilder::new(Kind::Custom(KIND_RING_ENTRY), canonical(&Value::Object(body)))
        .custom_created_at(Timestamp::from(created_at))
        .sign_with_keys(keys)?;
    Ok(event_value(&event))
}

/// Reason a raw event is rejected, or the parsed event.
fn verify_raw(raw: &Value, kind: u16) -> std::result::Result<Event, &'static str> {
    let Some(object) = raw.as_object() else { return Err("malformed-event") };
    if object.get("kind").and_then(Value::as_u64) != Some(kind as u64) {
        return Err(if object.contains_key("kind") { "wrong-kind" } else { "malformed-event" });
    }
    let event: Event = serde_json::from_value(raw.clone()).map_err(|_| "malformed-event")?;
    if !event.verify_id() {
        return Err("bad-id");
    }
    if !event.verify_signature() {
        return Err("bad-signature");
    }
    Ok(event)
}

fn parse_entry(raw: &Value) -> std::result::Result<(Event, Map<String, Value>), &'static str> {
    let event = verify_raw(raw, KIND_RING_ENTRY)?;
    if event.content.len() > MAX_ENTRY_CONTENT {
        return Err("too-large");
    }
    let content: Value = serde_json::from_str(&event.content).map_err(|_| "malformed-content")?;
    let Value::Object(content) = content else { return Err("malformed-content") };
    if !content.get("type").is_some_and(Value::is_string) {
        return Err("malformed-content");
    }
    if content.get("protocol").and_then(Value::as_str) != Some(RING) {
        return Err("foreign-protocol");
    }
    let Some(parents) = content.get("parents").and_then(Value::as_array) else { return Err("bad-parents") };
    let unique: HashSet<&str> = parents.iter().filter_map(Value::as_str).collect();
    if parents.len() > MAX_PARENTS || unique.len() != parents.len() {
        return Err("bad-parents");
    }
    let genesis = content["type"] == "genesis";
    if genesis != parents.is_empty() {
        return Err("bad-parents");
    }
    Ok((event, content))
}

fn device_ok(device: Option<&Value>) -> bool {
    let Some(d) = device.and_then(Value::as_object) else { return false };
    let key_ok = d.get("publicKey").and_then(Value::as_str).is_some_and(|k| {
        k.len() == 64 && k.bytes().all(|b| b.is_ascii_hexdigit()) && PublicKey::from_hex(k).is_ok()
    });
    let name_ok = d.get("name").and_then(Value::as_str).is_some_and(|n| (1..=64).contains(&n.chars().count()));
    key_ok
        && name_ok
        && matches!(d.get("kind").and_then(Value::as_str), Some("web" | "android" | "arch"))
        && matches!(d.get("role").and_then(Value::as_str), Some("admin" | "member"))
}

fn relays_ok(relays: Option<&Value>) -> bool {
    let Some(r) = relays.and_then(Value::as_object) else { return false };
    let Some(urls) = r.get("urls").and_then(Value::as_array) else { return false };
    let unique: HashSet<String> = urls.iter().map(Value::to_string).collect();
    let urls_ok = (1..=16).contains(&urls.len())
        && unique.len() == urls.len()
        && urls.iter().all(|u| u.as_str().is_some_and(|s| s.starts_with("wss://") && s.chars().count() <= 256));
    let acks_ok = r.get("minAcks").and_then(Value::as_u64).is_some_and(|n| n >= 1 && n as usize <= urls.len());
    urls_ok && acks_ok
}

#[derive(Clone, Default)]
struct State {
    members: BTreeMap<String, Map<String, Value>>,
    removed: BTreeMap<String, String>,
    relays: Option<Value>,
}

impl State {
    fn admins(&self) -> BTreeSet<&String> {
        self.members.iter().filter(|(_, d)| d["role"] == "admin").map(|(k, _)| k).collect()
    }
}

fn member_record(device: &Value, added_by: Value, entry: &str) -> Map<String, Value> {
    let mut record = Map::new();
    for key in ["publicKey", "name", "kind", "role"] {
        record.insert(key.into(), device[key].clone());
    }
    record.insert("addedBy".into(), added_by);
    record.insert("addEntry".into(), Value::String(entry.into()));
    record
}

fn apply(state: &mut State, content: &Map<String, Value>, signer: &str, id: &str) {
    let key = |field: &str| content.get(field).and_then(Value::as_str).unwrap_or_default().to_string();
    match content["type"].as_str().unwrap_or_default() {
        "genesis" => {
            let d = &content["device"];
            state.members.insert(key_of(d), member_record(d, Value::Null, id));
            state.relays = content.get("relays").cloned();
        }
        "add" => {
            let d = &content["device"];
            let target = key_of(d);
            if !state.removed.contains_key(&target) && !state.members.contains_key(&target) {
                state.members.insert(target, member_record(d, Value::String(signer.into()), id));
            }
        }
        "remove" => {
            let target = key("publicKey");
            state.removed.entry(target.clone()).or_insert_with(|| id.to_string());
            state.members.remove(&target);
        }
        "rename" => {
            if let Some(member) = state.members.get_mut(&key("publicKey")) {
                member.insert("name".into(), content["name"].clone());
            }
        }
        "relays" => state.relays = content.get("relays").cloned(),
        _ => {}
    }
}

fn key_of(device: &Value) -> String {
    device["publicKey"].as_str().unwrap_or_default().to_string()
}

fn authorize(past: &State, content: &Map<String, Value>, signer: &str) -> Option<&'static str> {
    let kind = content["type"].as_str().unwrap_or_default();
    if kind == "genesis" {
        return Some("duplicate-genesis");
    }
    let Some(member) = past.members.get(signer) else {
        return Some(if past.removed.contains_key(signer) { "signer-removed" } else { "signer-not-member" });
    };
    let admin = member["role"] == "admin";
    let target = content.get("publicKey").and_then(Value::as_str);
    match kind {
        "add" => {
            if !admin {
                return Some("signer-not-admin");
            }
            let via = content.get("via").and_then(Value::as_str);
            if !device_ok(content.get("device")) || !matches!(via, Some("rendezvous" | "migration")) {
                return Some("malformed-content");
            }
            let target = key_of(&content["device"]);
            if past.removed.contains_key(&target) {
                return Some("key-was-removed");
            }
            if past.members.contains_key(&target) {
                return Some("already-member");
            }
            None
        }
        "remove" => {
            let Some(target) = target.filter(|t| past.members.contains_key(*t)) else { return Some("unknown-target") };
            if !admin && target != signer {
                return Some("signer-not-admin");
            }
            let admins = past.admins();
            if admins.len() == 1 && admins.contains(&target.to_string()) {
                return Some("last-admin");
            }
            None
        }
        "rename" => {
            let Some(target) = target.filter(|t| past.members.contains_key(*t)) else { return Some("unknown-target") };
            if !admin && target != signer {
                return Some("signer-not-admin");
            }
            let name_ok = content.get("name").and_then(Value::as_str).is_some_and(|n| (1..=64).contains(&n.chars().count()));
            (!name_ok).then_some("malformed-content")
        }
        "relays" => {
            if !admin {
                return Some("signer-not-admin");
            }
            (!relays_ok(content.get("relays"))).then_some("malformed-content")
        }
        _ => None,
    }
}

/// Fold the ring log into state. Input order does not matter.
///
/// `account_id` is the genesis id; without it the log must contain exactly one genesis.
pub fn fold_ring(entries: &[Value], account_id: Option<&str>) -> Result<Value> {
    ensure!(entries.len() <= MAX_ENTRIES, "ring log longer than 1024 entries");
    let mut rejected: BTreeMap<String, String> = BTreeMap::new();
    let mut outdated: BTreeSet<String> = BTreeSet::new();
    let mut parsed: HashMap<String, (Event, Map<String, Value>)> = HashMap::new();
    for raw in entries {
        let id = raw.get("id").and_then(Value::as_str).map(str::to_string);
        if id.as_ref().is_some_and(|id| parsed.contains_key(id)) {
            continue;
        }
        match parse_entry(raw) {
            Ok((event, content)) => {
                parsed.insert(event.id.to_hex(), (event, content));
            }
            Err(reason) => {
                if reason == "foreign-protocol" {
                    let protocol = raw.get("content").and_then(Value::as_str)
                        .and_then(|c| serde_json::from_str::<Value>(c).ok())
                        .and_then(|c| c.get("protocol").and_then(Value::as_str).map(str::to_string));
                    if let Some(protocol) = protocol.filter(|p| p.starts_with("p2p-kanban-account-ring/")) {
                        outdated.insert(format!("protocol:{protocol}"));
                    }
                }
                rejected.insert(id.unwrap_or_else(|| "None".into()), reason.into());
            }
        }
    }

    let geneses: BTreeSet<String> = parsed.iter().filter(|(_, (_, c))| c["type"] == "genesis").map(|(id, _)| id.clone()).collect();
    let genesis = match account_id {
        Some(account) => geneses.contains(account).then(|| account.to_string()),
        None => (geneses.len() == 1).then(|| geneses.iter().next().cloned()).flatten(),
    }
    .ok_or_else(|| anyhow!("the log has no single genesis of this account"))?;
    {
        let (event, content) = &parsed[&genesis];
        let device = content.get("device");
        let nonce_ok = content.get("nonce").and_then(Value::as_str).is_some_and(|n| n.chars().count() >= 22);
        if !device_ok(device)
            || device.and_then(|d| d.get("role")) != Some(&json!("admin"))
            || device.and_then(|d| d.get("publicKey")).and_then(Value::as_str) != Some(event.pubkey.to_hex().as_str())
            || !relays_ok(content.get("relays"))
            || !nonce_ok
        {
            bail!("genesis is malformed");
        }
    }
    let ids: Vec<String> = parsed.keys().cloned().collect();
    for id in ids {
        if id == genesis {
            continue;
        }
        let content = &parsed[&id].1;
        if content["type"] == "genesis" || content.get("accountId").and_then(Value::as_str) != Some(genesis.as_str()) {
            let reason = if content["type"] == "genesis" { "duplicate-genesis" } else { "foreign-account" };
            rejected.insert(id.clone(), reason.into());
            parsed.remove(&id);
        }
    }

    let parents_of = |content: &Map<String, Value>| -> Vec<String> {
        content["parents"].as_array().map(|a| a.iter().map(|p| p.as_str().map(str::to_string).unwrap_or_else(|| p.to_string())).collect()).unwrap_or_default()
    };
    // Entries with unknown parents wait; waiting is inherited.
    let mut pending: BTreeMap<String, Vec<String>> = BTreeMap::new();
    loop {
        let waiting: Vec<(String, Vec<String>)> = parsed.iter()
            .filter_map(|(id, (_, c))| {
                let mut missing: Vec<String> = parents_of(c).into_iter().filter(|p| !parsed.contains_key(p)).collect();
                missing.sort();
                (!missing.is_empty()).then(|| (id.clone(), missing))
            })
            .collect();
        if waiting.is_empty() {
            break;
        }
        for (id, missing) in waiting {
            parsed.remove(&id);
            pending.insert(id, missing);
        }
    }

    // Kahn's order; among ready entries the smaller id goes first.
    let mut children: HashMap<&str, Vec<&str>> = parsed.keys().map(|id| (id.as_str(), Vec::new())).collect();
    let mut indegree: HashMap<&str, usize> = HashMap::new();
    let parent_lists: HashMap<&str, Vec<String>> = parsed.iter().map(|(id, (_, c))| (id.as_str(), parents_of(c))).collect();
    for (id, parents) in &parent_lists {
        indegree.insert(id, parents.len());
        for parent in parents {
            children.get_mut(parent.as_str()).expect("parent is parsed").push(id);
        }
    }
    let mut ready: BTreeSet<&str> = indegree.iter().filter(|(_, d)| **d == 0).map(|(id, _)| *id).collect();
    let mut order: Vec<String> = Vec::new();
    while let Some(id) = ready.pop_first() {
        order.push(id.to_string());
        for child in &children[id] {
            let degree = indegree.get_mut(child).expect("child has degree");
            *degree -= 1;
            if *degree == 0 {
                ready.insert(child);
            }
        }
    }
    let position: HashMap<&str, usize> = order.iter().enumerate().map(|(i, id)| (id.as_str(), i)).collect();
    let mut ancestors: HashMap<String, HashSet<String>> = HashMap::new();
    for id in &order {
        let mut acc = HashSet::new();
        for parent in &parent_lists[id.as_str()] {
            acc.insert(parent.clone());
            acc.extend(ancestors[parent].iter().cloned());
        }
        ancestors.insert(id.clone(), acc);
    }

    let past_state = |id: &str, valid: &HashSet<String>| -> State {
        let mut past: Vec<&String> = ancestors[id].iter().filter(|a| valid.contains(*a)).collect();
        past.sort_by_key(|a| position[a.as_str()]);
        let mut state = State::default();
        for a in past {
            let (event, content) = &parsed[a];
            apply(&mut state, content, &event.pubkey.to_hex(), a);
        }
        state
    };
    let run = |frozen: &HashSet<String>, forced: &HashSet<String>| -> (HashSet<String>, BTreeMap<String, String>) {
        let mut valid = HashSet::new();
        let mut reasons = BTreeMap::new();
        for id in &order {
            let (event, content) = &parsed[id];
            if *id == genesis || (forced.contains(id) && !frozen.contains(id)) {
                valid.insert(id.clone());
            } else if frozen.contains(id) {
                reasons.insert(id.clone(), "frozen-by-remove".to_string());
            } else if let Some(why) = authorize(&past_state(id, &valid), content, &event.pubkey.to_hex()) {
                reasons.insert(id.clone(), why.to_string());
            } else {
                valid.insert(id.clone());
            }
        }
        (valid, reasons)
    };

    // Phase A: rights in the causal past.
    let (valid_a, _) = run(&HashSet::new(), &HashSet::new());
    let removes: Vec<&String> = valid_a.iter().filter(|id| parsed[*id].1["type"] == "remove").collect();
    // Phase B: a removal freezes what the removed device did behind the remover's back.
    let mut frozen = HashSet::new();
    for id in &valid_a {
        let (event, content) = &parsed[id];
        if matches!(content["type"].as_str(), Some("remove" | "genesis")) {
            continue;
        }
        let signer = event.pubkey.to_hex();
        let against: Vec<&&String> = removes.iter().filter(|r| parsed[**r].1.get("publicKey").and_then(Value::as_str) == Some(signer.as_str())).collect();
        if !against.is_empty() && !against.iter().any(|r| ancestors[r.as_str()].contains(id)) {
            frozen.insert(id.clone());
        }
    }
    // Phase C: cascade; removals valid in their own past always stand.
    let forced: HashSet<String> = removes.into_iter().cloned().collect();
    let (valid, reasons) = run(&frozen, &forced);

    let mut state = State::default();
    let mut unknown = Vec::new();
    for id in &order {
        if !valid.contains(id) {
            continue;
        }
        let (event, content) = &parsed[id];
        apply(&mut state, content, &event.pubkey.to_hex(), id);
        let kind = content["type"].as_str().unwrap_or_default();
        if !ENTRY_TYPES.contains(&kind) {
            unknown.push(json!({"id": id, "type": kind}));
            outdated.insert(format!("type:{kind}"));
        }
    }
    rejected.extend(reasons);
    let referenced: HashSet<&String> = order.iter().flat_map(|id| parent_lists[id.as_str()].iter()).collect();
    let heads: BTreeSet<&String> = order.iter().filter(|id| !referenced.contains(id)).collect();
    Ok(json!({
        "accountId": genesis,
        "accountTag": account_tag(&genesis)?,
        "members": state.members.values().cloned().map(Value::Object).collect::<Vec<_>>(),
        "removed": state.removed.iter().map(|(k, e)| json!({"publicKey": k, "removeEntry": e})).collect::<Vec<_>>(),
        "relays": state.relays.unwrap_or(Value::Null),
        "heads": heads.into_iter().collect::<Vec<_>>(),
        "order": order,
        "rejected": rejected.iter().map(|(id, why)| json!({"id": id, "reason": why})).collect::<Vec<_>>(),
        "pending": pending.iter().map(|(id, miss)| json!({"id": id, "missing": miss})).collect::<Vec<_>>(),
        "unknown": unknown,
        "readerOutdated": outdated.into_iter().collect::<Vec<_>>(),
    }))
}

/// Which presences lag behind: unknown ring protocols or an old view of the log.
pub fn presence_skew(presences: &[Value], ring_heads: &[String]) -> Vec<Value> {
    let mut sorted: Vec<&Value> = presences.iter().collect();
    sorted.sort_by_key(|p| p["publicKey"].as_str().unwrap_or_default().to_string());
    let mut heads = ring_heads.to_vec();
    heads.sort();
    sorted.into_iter().filter_map(|p| {
        let known: HashSet<&str> = p["software"]["protocols"].as_array().map(|a| a.iter().filter_map(Value::as_str).collect()).unwrap_or_default();
        let missing: Vec<&str> = RING_PROTOCOLS.iter().copied().filter(|proto| !known.contains(proto)).collect();
        let mut seen: Vec<String> = p["ringHeads"].as_array().map(|a| a.iter().filter_map(Value::as_str).map(str::to_string).collect()).unwrap_or_default();
        seen.sort();
        let stale = seen != heads;
        (!missing.is_empty() || stale).then(|| json!({"publicKey": p["publicKey"], "missingProtocols": missing, "staleRing": stale}))
    }).collect()
}

// ---------------------------------------------------------------- keyring

fn item_rank(item: &Value) -> (i64, i64, String) {
    let epoch = item.get("roaming").filter(|r| r.is_object()).and_then(|r| r.get("epoch")).and_then(Value::as_i64).unwrap_or(0);
    let rev = item.get("rev").and_then(Value::as_i64).unwrap_or(0);
    (epoch, rev, sha256_hex(canonical(item).as_bytes()))
}

/// Merge keyring copies: (epoch, rev, sha256) wins; deletion is irreversible.
pub fn merge_keyrings(copies: &[Value]) -> Vec<Value> {
    let mut best: BTreeMap<(String, String), Value> = BTreeMap::new();
    let mut deleted: HashSet<(String, String)> = HashSet::new();
    for copy in copies {
        for item in copy.get("items").and_then(Value::as_array).into_iter().flatten() {
            let key = (item["kind"].as_str().unwrap_or_default().to_string(), item["id"].as_str().unwrap_or_default().to_string());
            if item.get("deleted") == Some(&Value::Bool(true)) {
                deleted.insert(key.clone());
            }
            if best.get(&key).is_none_or(|current| item_rank(item) > item_rank(current)) {
                best.insert(key, item.clone());
            }
        }
    }
    best.into_iter().map(|(key, mut item)| {
        if deleted.contains(&key) && item.get("deleted") != Some(&Value::Bool(true)) {
            if let Some(map) = item.as_object_mut() {
                map.remove("roaming");
                map.insert("deleted".into(), Value::Bool(true));
            }
        }
        item
    }).collect()
}

pub fn keyring_digest(items: &[Value]) -> String {
    let mut sorted: Vec<&Value> = items.iter().collect();
    sorted.sort_by_key(|i| (i["kind"].as_str().unwrap_or_default().to_string(), i["id"].as_str().unwrap_or_default().to_string()));
    sha256_hex(canonical(&Value::Array(sorted.into_iter().cloned().collect())).as_bytes())
}

// ---------------------------------------------------------------- sealed records

pub fn sealed_kind(record_type: &str) -> Result<u16> {
    Ok(match record_type {
        "ring-log" => KIND_RING_LOG,
        "keyring" => KIND_KEYRING,
        "presence" => KIND_PRESENCE,
        other => bail!("unknown sealed record type {other}"),
    })
}

fn seal_aad(record_type: &str, tag: &str) -> Vec<u8> {
    format!("p2p-kanban:seal:v1|{record_type}|{tag}").into_bytes()
}

/// Seal plaintext once; wrap the content key for every recipient with NIP-44 v2.
pub fn seal(keys: &Keys, recipients: &[String], record_type: &str, tag: &str, plaintext: &Value) -> Result<Value> {
    let unique: BTreeSet<&String> = recipients.iter().collect();
    ensure!((1..=MAX_RECIPIENTS).contains(&unique.len()), "1..64 recipients required");
    let mut cek = [0u8; 32];
    let mut nonce = [0u8; 24];
    OsRng.fill_bytes(&mut cek);
    OsRng.fill_bytes(&mut nonce);
    let cipher = XChaCha20Poly1305::new_from_slice(&cek).map_err(|e| anyhow!("{e}"))?;
    let aad = seal_aad(record_type, tag);
    let ciphertext = cipher
        .encrypt(XNonce::from_slice(&nonce), Payload { msg: canonical(plaintext).as_bytes(), aad: &aad })
        .map_err(|_| anyhow!("could not seal the record"))?;
    let mut wrapped = Vec::new();
    for recipient in unique {
        let public = PublicKey::from_hex(recipient)?;
        wrapped.push(nip44::encrypt(keys.secret_key(), &public, b64url(&cek), nip44::Version::V2)?);
    }
    wrapped.sort();
    Ok(json!({"version": 1, "type": record_type, "nonce": b64url(&nonce), "ciphertext": b64url(&ciphertext), "recipients": wrapped}))
}

/// Open a sealed record with this device's key. Err if it was not sealed for us.
pub fn unseal(keys: &Keys, sender: &str, tag: &str, sealed: &Value) -> Result<Value> {
    let sender = PublicKey::from_hex(sender)?;
    let record_type = sealed["type"].as_str().context("sealed record without type")?;
    let nonce = unb64url(sealed["nonce"].as_str().context("sealed record without nonce")?)?;
    let ciphertext = unb64url(sealed["ciphertext"].as_str().context("sealed record without ciphertext")?)?;
    ensure!(nonce.len() == 24, "nonce must be 24 bytes");
    let conversation = nip44::v2::ConversationKey::derive(keys.secret_key(), &sender)?;
    for wrapped in sealed["recipients"].as_array().into_iter().flatten().filter_map(Value::as_str) {
        let Ok(payload) = base64::engine::general_purpose::STANDARD.decode(wrapped) else { continue };
        let Ok(cek) = nip44::v2::decrypt_to_bytes(&conversation, &payload) else { continue };
        let cek = unb64url(std::str::from_utf8(&cek)?)?;
        let cipher = XChaCha20Poly1305::new_from_slice(&cek).map_err(|e| anyhow!("{e}"))?;
        let plain = cipher
            .decrypt(XNonce::from_slice(&nonce), Payload { msg: &ciphertext, aad: &seal_aad(record_type, tag) })
            .map_err(|_| anyhow!("AEAD: tampered record or foreign key"))?;
        return Ok(serde_json::from_slice(&plain)?);
    }
    bail!("the record is not sealed for this device")
}

/// A signed replaceable event carrying a sealed record under the account tag.
pub fn sealed_event(keys: &Keys, record_type: &str, account_id: &str, recipients: &[String], plaintext: &Value, created_at: u64) -> Result<Value> {
    let tag = account_tag(account_id)?;
    let content = seal(keys, recipients, record_type, &tag, plaintext)?;
    let tags = [
        Tag::parse(["d", tag.as_str()])?,
        Tag::parse(["t", "p2pkanban-ring"])?,
        Tag::parse(["v", "1"])?,
    ];
    let event = EventBuilder::new(Kind::Custom(sealed_kind(record_type)?), canonical(&content))
        .tags(tags)
        .custom_created_at(Timestamp::from(created_at))
        .sign_with_keys(keys)?;
    Ok(event_value(&event))
}

/// Verify and open a sealed event fetched from a relay: (sender, record type, plaintext).
pub fn open_sealed_event(keys: &Keys, raw: &Value, account_id: &str) -> Result<(String, String, Value)> {
    let kind = raw.get("kind").and_then(Value::as_u64).context("event without kind")? as u16;
    let event = verify_raw(raw, kind).map_err(|reason| anyhow!("{reason}"))?;
    let tag = account_tag(account_id)?;
    ensure!(event.tags.iter().any(|t| t.as_slice() == ["d", tag.as_str()]), "event of another account");
    let sealed: Value = serde_json::from_str(&event.content)?;
    let record_type = sealed["type"].as_str().context("sealed record without type")?.to_string();
    ensure!(sealed_kind(&record_type)? == kind, "kind does not match the record type");
    let sender = event.pubkey.to_hex();
    let plain = unseal(keys, &sender, &tag, &sealed)?;
    Ok((sender, record_type, plain))
}

// ---------------------------------------------------------------- relay exchange

#[derive(Debug, Default, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RelayExchange {
    pub published: Vec<PublishedRecord>,
    pub fetched: Vec<Value>,
    pub errors: Vec<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PublishedRecord {
    pub record_type: String,
    pub event_id: String,
    pub accepted: Vec<String>,
    pub failed: Vec<String>,
}

/// Publish this device's sealed copies and, when `fetch`, fetch every copy under the account tag.
pub async fn exchange(secret_key: &str, relays: &[String], account_id: &str, events: &[Value], fetch: bool, timeout: Duration) -> Result<RelayExchange> {
    let keys = Keys::parse(secret_key.trim())?;
    let client = Client::new(keys);
    for relay in relays {
        client.add_relay(relay).await.with_context(|| format!("could not add relay {relay}"))?;
    }
    client.connect().await;
    client.wait_for_connection(Duration::from_secs(5)).await;
    let mut report = RelayExchange::default();
    for raw in events {
        let event: Event = serde_json::from_value(raw.clone())?;
        let record_type = match event.kind.as_u16() {
            KIND_RING_LOG => "ring-log",
            KIND_KEYRING => "keyring",
            _ => "presence",
        };
        match client.send_event(&event).await {
            Ok(output) => report.published.push(PublishedRecord {
                record_type: record_type.into(),
                event_id: output.val.to_hex(),
                accepted: output.success.iter().map(ToString::to_string).collect(),
                failed: output.failed.keys().map(ToString::to_string).collect(),
            }),
            Err(error) => report.errors.push(format!("{record_type}: {error}")),
        }
    }
    if !fetch {
        client.shutdown().await;
        return Ok(report);
    }
    let filter = Filter::new()
        .kinds([Kind::Custom(KIND_RING_LOG), Kind::Custom(KIND_KEYRING), Kind::Custom(KIND_PRESENCE)])
        .identifier(account_tag(account_id)?);
    match client.fetch_events(filter, timeout).await {
        Ok(events) => report.fetched = events.iter().map(event_value).collect(),
        Err(error) => report.errors.push(format!("fetch: {error}")),
    }
    client.shutdown().await;
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn keys(n: u8) -> Keys {
        Keys::parse(&format!("{n:064x}")).unwrap()
    }

    fn genesis(k: &Keys) -> Value {
        let body = json!({"type": "genesis", "parents": [], "nonce": b64url(&[7u8; 16]),
            "device": {"publicKey": k.public_key().to_hex(), "name": "Узел", "kind": "web", "role": "admin"},
            "relays": {"urls": ["wss://relay-a.example"], "minAcks": 1}});
        make_entry(k, body.as_object().unwrap().clone(), 1_791_244_860).unwrap()
    }

    #[test]
    fn entries_made_here_fold_and_migration_adds_member() {
        let node = keys(1);
        let phone = keys(2);
        let g = genesis(&node);
        let account = g["id"].as_str().unwrap();
        let add = make_entry(&node, json!({"type": "add", "accountId": account, "parents": [account], "via": "migration",
            "device": {"publicKey": phone.public_key().to_hex(), "name": "Телефон", "kind": "android", "role": "admin"}}).as_object().unwrap().clone(), 1_791_244_920).unwrap();
        let state = fold_ring(&[add.clone(), g.clone()], Some(account)).unwrap();
        assert_eq!(state["members"].as_array().unwrap().len(), 2);
        assert_eq!(state["heads"], json!([add["id"]]));
        assert_eq!(state["rejected"], json!([]));
    }

    #[test]
    fn sealed_roundtrip_only_for_recipients() {
        let node = keys(1);
        let phone = keys(2);
        let outsider = keys(3);
        let account = genesis(&node)["id"].as_str().unwrap().to_string();
        let plain = json!({"protocol": RING, "accountId": account, "entries": []});
        let recipients = vec![node.public_key().to_hex(), phone.public_key().to_hex()];
        let event = sealed_event(&node, "ring-log", &account, &recipients, &plain, 1_791_244_900).unwrap();
        let (sender, kind, opened) = open_sealed_event(&phone, &event, &account).unwrap();
        assert_eq!((sender.as_str(), kind.as_str(), &opened), (node.public_key().to_hex().as_str(), "ring-log", &plain));
        assert!(open_sealed_event(&outsider, &event, &account).is_err());
        let mut tampered = event.clone();
        tampered["content"] = Value::String("{}".into());
        assert!(open_sealed_event(&phone, &tampered, &account).is_err());
    }
}
