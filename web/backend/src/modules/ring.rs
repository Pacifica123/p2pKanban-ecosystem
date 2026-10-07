//! R2 of the device ring (contracts/account-ring/1, contracts/keyring/1).
//!
//! The node keeps one ring per local user: it writes `genesis`, moves the
//! devices it already trusts (`device-link/2`, `web-node-link/1` peers in
//! `trusted_device_peers`) into the ring with `add via: migration`, keeps its
//! own keyring copy, and exchanges sealed copies and presences with the ring's
//! relays. Adding a new device by QR is R4; removal and key rotation are R5.

use std::{
    collections::{BTreeMap, BTreeSet, HashSet},
    sync::Arc,
    time::Duration,
};

use axum::{
    extract::State,
    http::HeaderMap,
    routing::{get, post},
    Json, Router,
};
use p2p_kanban_nostr_transport::{ring, NostrCodec};
use rand::{rngs::OsRng, RngCore};
use serde::Deserialize;
use serde_json::{json, Map, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    config::Settings,
    error::{AppError, AppResult},
    http::response::{ok, ApiEnvelope},
    modules::common::auth_context,
    state::AppState,
};

/// Protocols this node speaks; mobile and abl see the rest as missing.
pub const PROTOCOLS: [&str; 3] = [ring::RING, ring::KEYRING, ring::ROAMING];
/// How often the background worker re-publishes copies and presence.
pub const SYNC_INTERVAL: Duration = Duration::from_secs(600);
const NAME_LIMIT: usize = 200;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/ring", get(get_ring))
        .route("/ring/genesis", post(genesis))
        .route("/ring/migrate", post(migrate))
        .route("/ring/rename", post(rename))
        .route("/ring/sync", post(sync))
}

fn invalid(e: impl std::fmt::Display) -> AppError {
    AppError::bad_request(format!("Кольцо устройств: {e}"))
}

fn node_keys(settings: &Settings) -> AppResult<(String, ring::DeviceKeys)> {
    let nostr = &settings.transports.nostr;
    if !nostr.enabled {
        return Err(AppError::conflict("Кольцу устройств нужен включённый Nostr-роуминг узла"));
    }
    let secret = nostr.secret_key.as_deref().ok_or_else(AppError::internal)?.trim().to_string();
    let keys = ring::DeviceKeys::parse(&secret).map_err(|_| AppError::internal())?;
    Ok((secret, keys))
}

fn now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn clip(text: &str) -> String {
    text.chars().take(NAME_LIMIT).collect()
}

fn device_name(name: &str) -> AppResult<String> {
    let name = name.trim();
    let length = name.chars().count();
    if !(1..=64).contains(&length) {
        return Err(invalid("имя устройства — от 1 до 64 символов"));
    }
    Ok(name.to_string())
}

fn hex64(value: &str) -> AppResult<String> {
    let value = value.trim().to_ascii_lowercase();
    if value.len() != 64 || !value.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(invalid("ключ устройства — 64 hex-символа"));
    }
    Ok(value)
}

/// Relays a new ring starts with: the node's own `wss://` relays (the contract
/// forbids plain `ws://`), at most 16, with the node's acknowledgement quorum.
pub fn genesis_relays(settings: &Settings) -> AppResult<Value> {
    let nostr = &settings.transports.nostr;
    let urls: Vec<String> = nostr.relays.iter().map(|r| r.trim().to_string())
        .filter(|r| r.starts_with("wss://")).take(16).collect();
    if urls.is_empty() {
        return Err(AppError::conflict("Для кольца нужен хотя бы один relay wss:// в TRANSPORTS__NOSTR__RELAYS"));
    }
    let min_acks = nostr.min_relay_acks.clamp(1, urls.len());
    Ok(json!({"urls": urls, "minAcks": min_acks}))
}

// ---------------------------------------------------------------- storage

async fn account_of(db: &PgPool, user: Uuid) -> AppResult<Option<String>> {
    Ok(sqlx::query_scalar("select account_id from account_rings where user_id=$1").bind(user).fetch_optional(db).await?)
}

async fn entries_of(db: &PgPool, account: &str) -> AppResult<Vec<Value>> {
    Ok(sqlx::query_scalar("select event_json from account_ring_entries where account_id=$1 order by id")
        .bind(account).fetch_all(db).await?)
}

async fn folded(db: &PgPool, account: &str) -> AppResult<(Vec<Value>, Value)> {
    let entries = entries_of(db, account).await?;
    let state = ring::fold_ring(&entries, Some(account)).map_err(invalid)?;
    Ok((entries, state))
}

fn member_keys(state: &Value) -> Vec<String> {
    state["members"].as_array().into_iter().flatten()
        .filter_map(|m| m["publicKey"].as_str().map(str::to_string)).collect()
}

fn heads(state: &Value) -> Vec<String> {
    state["heads"].as_array().into_iter().flatten().filter_map(Value::as_str).map(str::to_string).collect()
}

/// Sign `body` with the node key and keep it only when the fold accepts it.
async fn append(db: &PgPool, keys: &ring::DeviceKeys, account: &str, mut body: Map<String, Value>) -> AppResult<Value> {
    let (entries, state) = folded(db, account).await?;
    let parents: Vec<String> = heads(&state).into_iter().take(ring::MAX_PARENTS).collect();
    body.insert("accountId".into(), json!(account));
    body.insert("parents".into(), json!(parents));
    let entry = ring::make_entry(keys, body, now()).map_err(invalid)?;
    let id = entry["id"].as_str().ok_or_else(AppError::internal)?.to_string();
    let mut all = entries;
    all.push(entry.clone());
    if all.len() > ring::MAX_ENTRIES {
        return Err(AppError::conflict("Журнал кольца заполнен (1024 записи)"));
    }
    let after = ring::fold_ring(&all, Some(account)).map_err(invalid)?;
    if let Some(reject) = after["rejected"].as_array().into_iter().flatten().find(|r| r["id"] == id.as_str()) {
        return Err(invalid(format!("запись отклонена свёрткой: {}", reject["reason"].as_str().unwrap_or("?"))));
    }
    sqlx::query("insert into account_ring_entries(account_id,id,event_json,source) values($1,$2,$3,'local') on conflict do nothing")
        .bind(account).bind(&id).bind(&entry).execute(db).await?;
    Ok(after)
}

// ---------------------------------------------------------------- keyring

fn rank_free(item: &Value) -> Value {
    let mut item = item.clone();
    if let Some(map) = item.as_object_mut() {
        map.remove("rev");
        map.remove("updatedBy");
    }
    item
}

/// Spaces and boards this node holds for the user, without rev/updatedBy.
async fn local_items(settings: &Settings, db: &PgPool, user: Uuid) -> AppResult<BTreeMap<(String, String), Value>> {
    let mut items = BTreeMap::new();
    for row in sqlx::query("select id, name from workspaces where owner_user_id=$1 and deleted_at is null")
        .bind(user).fetch_all(db).await?
    {
        let id: Uuid = row.try_get("id")?;
        let name: String = row.try_get("name")?;
        items.insert(("space".into(), id.to_string()), json!({"kind": "space", "id": id.to_string(), "name": clip(&name), "deleted": false}));
    }
    let rows = sqlx::query(
        "select b.id, b.workspace_id, b.name, w.access_epoch, rbc.board_tag, rbc.board_key_base64, rbc.capability_epoch
         from boards b join workspaces w on w.id=b.workspace_id
         left join roaming_board_capabilities rbc on rbc.board_id=b.id
         where w.owner_user_id=$1 and w.deleted_at is null and b.deleted_at is null")
        .bind(user).fetch_all(db).await?;
    let codec = NostrCodec::new(settings.transports.nostr.master_key().map_err(|_| AppError::internal())?)
        .map_err(|_| AppError::internal())?;
    for row in rows {
        let board: Uuid = row.try_get("id")?;
        let space: Uuid = row.try_get("workspace_id")?;
        let name: String = row.try_get("name")?;
        let (key, epoch) = match (row.try_get::<Option<String>, _>("board_key_base64")?, row.try_get::<Option<i64>, _>("capability_epoch")?) {
            (Some(key), Some(epoch)) => (key, epoch),
            _ => {
                // Same pinning as the node-link export: the derived key becomes the stored one.
                let material = codec.roaming_capability(&board.to_string()).map_err(|_| AppError::internal())?;
                let epoch: i64 = row.try_get("access_epoch")?;
                let stored = sqlx::query_as::<_, (String, i64)>(
                    "insert into roaming_board_capabilities (board_id,board_tag,board_key_base64,source_kind,capability_epoch) values ($1,$2,$3,'linked_node',$4)
                     on conflict (board_id) do update set board_id=excluded.board_id returning board_key_base64, capability_epoch")
                    .bind(board).bind(&material.board_tag).bind(&material.board_key).bind(epoch)
                    .fetch_one(db).await?;
                stored
            }
        };
        items.insert(("board".into(), board.to_string()), json!({
            "kind": "board", "id": board.to_string(), "spaceId": space.to_string(), "name": clip(&name), "deleted": false,
            "roaming": {"protocol": ring::ROAMING, "epoch": epoch.max(1), "boardKey": key},
        }));
    }
    Ok(items)
}

/// Pure part of the keyring refresh: new own copy from the stored one, the
/// node's current spaces and boards, and the highest rev seen in other copies.
pub fn next_own_items(stored: &BTreeMap<(String, String), Value>, current: &BTreeMap<(String, String), Value>,
                      seen_rev: &BTreeMap<(String, String), i64>, node: &str) -> BTreeMap<(String, String), Value> {
    let keys: BTreeSet<&(String, String)> = stored.keys().chain(current.keys()).collect();
    let mut out = BTreeMap::new();
    for key in keys {
        let old = stored.get(key);
        let bump = |base: Option<&Value>| old.and_then(|o| o["rev"].as_i64()).unwrap_or(0)
            .max(seen_rev.get(key).copied().unwrap_or(0)).max(base.and_then(|b| b["rev"].as_i64()).unwrap_or(0)) + 1;
        let next = match (current.get(key), old) {
            (Some(now), Some(old)) if rank_free(old) == *now => old.clone(),
            (Some(now), _) => {
                let mut item = now.clone();
                item["rev"] = json!(bump(None));
                item["updatedBy"] = json!(node);
                item
            }
            (None, Some(old)) if old["deleted"] == true => old.clone(),
            (None, Some(old)) => {
                let mut item = old.clone();
                if let Some(map) = item.as_object_mut() {
                    map.remove("roaming");
                }
                item["deleted"] = json!(true);
                item["rev"] = json!(bump(Some(old)));
                item["updatedBy"] = json!(node);
                item
            }
            (None, None) => continue,
        };
        out.insert(key.clone(), next);
    }
    out
}

async fn copies_of(db: &PgPool, account: &str) -> AppResult<Vec<Value>> {
    Ok(sqlx::query_scalar("select keyring_json from account_keyring_copies where account_id=$1 order by author_public_key")
        .bind(account).fetch_all(db).await?)
}

async fn stored_own(db: &PgPool, account: &str) -> AppResult<BTreeMap<(String, String), Value>> {
    let rows = sqlx::query("select kind, id, item_json from account_keyring_items where account_id=$1")
        .bind(account).fetch_all(db).await?;
    rows.into_iter().map(|r| Ok(((r.try_get("kind")?, r.try_get("id")?), r.try_get("item_json")?))).collect()
}

async fn refresh_own_keyring(settings: &Settings, db: &PgPool, user: Uuid, account: &str, node: &str) -> AppResult<Vec<Value>> {
    let stored = stored_own(db, account).await?;
    let current = local_items(settings, db, user).await?;
    let mut seen = BTreeMap::new();
    for copy in copies_of(db, account).await? {
        for item in copy["items"].as_array().into_iter().flatten() {
            let key = (item["kind"].as_str().unwrap_or_default().to_string(), item["id"].as_str().unwrap_or_default().to_string());
            let rev = item["rev"].as_i64().unwrap_or(0);
            let entry = seen.entry(key).or_insert(0);
            *entry = (*entry).max(rev);
        }
    }
    let next = next_own_items(&stored, &current, &seen, node);
    for ((kind, id), item) in &next {
        if stored.get(&(kind.clone(), id.clone())) != Some(item) {
            sqlx::query("insert into account_keyring_items(account_id,kind,id,rev,item_json) values($1,$2,$3,$4,$5)
                         on conflict (account_id,kind,id) do update set rev=excluded.rev, item_json=excluded.item_json, updated_at=now()")
                .bind(account).bind(kind).bind(id).bind(item["rev"].as_i64().unwrap_or(1)).bind(item).execute(db).await?;
        }
    }
    Ok(next.into_values().collect())
}

fn keyring_summary(items: &[Value]) -> Value {
    let live = |kind: &str| items.iter().filter(|i| i["kind"] == kind && i["deleted"] != true).count();
    json!({"digest": ring::keyring_digest(items), "items": items.len(), "boards": live("board")})
}

// ---------------------------------------------------------------- relay exchange

/// What a sync took in from the relays.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct Absorbed {
    pub not_for_this_node: usize,
    pub new_entries: usize,
    pub keyring_copies: usize,
    pub presences: usize,
}

/// Open sealed copies fetched under the account tag and keep what is valid.
pub async fn absorb(db: &PgPool, keys: &ring::DeviceKeys, account: &str, fetched: &[Value]) -> AppResult<(Absorbed, Value)> {
    let node = keys.public_key().to_hex();
    let entries = entries_of(db, account).await?;
    // Open what came back. Entries carry their own signatures, so a ring-log
    // copy is useful whoever sealed it; keyrings and presences only from members.
    let mut not_for_us = 0usize;
    let mut candidates: BTreeMap<String, Value> = BTreeMap::new();
    let mut keyrings = Vec::new();
    let mut presences = Vec::new();
    for raw in fetched {
        let Ok((sender, record_type, plain)) = ring::open_sealed_event(&keys, raw, account) else {
            not_for_us += 1;
            continue;
        };
        if sender == node || plain["accountId"] != account {
            continue;
        }
        let created = raw["created_at"].as_i64().unwrap_or(0);
        match record_type.as_str() {
            "ring-log" if plain["protocol"] == ring::RING => {
                for entry in plain["entries"].as_array().into_iter().flatten().take(ring::MAX_ENTRIES) {
                    if let Some(id) = entry["id"].as_str() {
                        candidates.entry(id.to_string()).or_insert_with(|| entry.clone());
                    }
                }
            }
            "keyring" if plain["protocol"] == ring::KEYRING => keyrings.push((sender, created, plain)),
            "presence" if plain["type"] == "presence" && plain["publicKey"] == sender.as_str() => presences.push((sender, plain)),
            _ => {}
        }
    }
    let known: HashSet<String> = entries.iter().filter_map(|e| e["id"].as_str().map(str::to_string)).collect();
    candidates.retain(|id, _| !known.contains(id));
    let mut all = entries.clone();
    all.extend(candidates.values().cloned());
    let merged = ring::fold_ring(&all, Some(account)).map_err(invalid)?;
    let rejected: HashSet<&str> = merged["rejected"].as_array().into_iter().flatten().filter_map(|r| r["id"].as_str()).collect();
    let mut new_entries = 0;
    for (id, entry) in &candidates {
        if rejected.contains(id.as_str()) || known.len() + new_entries >= ring::MAX_ENTRIES {
            continue;
        }
        new_entries += sqlx::query("insert into account_ring_entries(account_id,id,event_json,source) values($1,$2,$3,'relay') on conflict do nothing")
            .bind(account).bind(id).bind(entry).execute(db).await?.rows_affected() as usize;
    }
    let final_state = ring::fold_ring(&entries_of(db, account).await?, Some(account)).map_err(invalid)?;
    let final_members = member_keys(&final_state);
    let mut accepted_copies = 0;
    for (sender, created, plain) in keyrings {
        if !final_members.contains(&sender) {
            continue;
        }
        accepted_copies += sqlx::query("insert into account_keyring_copies(account_id,author_public_key,created_at,keyring_json) values($1,$2,$3,$4)
                     on conflict (account_id,author_public_key) do update set created_at=excluded.created_at, keyring_json=excluded.keyring_json, received_at=now()
                     where account_keyring_copies.created_at<excluded.created_at")
            .bind(account).bind(&sender).bind(created).bind(&plain).execute(db).await?.rows_affected() as usize;
    }
    let mut accepted_presences = 0;
    for (sender, plain) in presences {
        if !final_members.contains(&sender) {
            continue;
        }
        accepted_presences += sqlx::query("insert into account_ring_presences(account_id,public_key,seen_at,presence_json) values($1,$2,$3,$4)
                     on conflict (account_id,public_key) do update set seen_at=excluded.seen_at, presence_json=excluded.presence_json, received_at=now()
                     where account_ring_presences.seen_at<excluded.seen_at")
            .bind(account).bind(&sender).bind(plain["seenAt"].as_i64().unwrap_or(0)).bind(&plain).execute(db).await?.rows_affected() as usize;
    }

    Ok((Absorbed { not_for_this_node: not_for_us, new_entries, keyring_copies: accepted_copies, presences: accepted_presences }, final_state))
}

/// Publish the node's sealed ring log, keyring and presence; take in what the
/// other members published. Returns the report stored as `last_sync_json`.
pub async fn sync_account(settings: &Settings, db: &PgPool, user: Uuid, account: &str) -> AppResult<Value> {
    let (secret, keys) = node_keys(settings)?;
    let node = keys.public_key().to_hex();
    let (entries, state) = folded(db, account).await?;
    let members = member_keys(&state);
    if !members.contains(&node) {
        return Err(AppError::conflict("Этот узел не участник своего кольца: он исключён"));
    }
    let relays: Vec<String> = state["relays"]["urls"].as_array().into_iter().flatten()
        .filter_map(Value::as_str).map(str::to_string).collect();
    let ring_heads = heads(&state);
    let own = refresh_own_keyring(settings, db, user, account, &node).await?;
    let recipients: Vec<String> = members.iter().take(ring::MAX_RECIPIENTS).cloned().collect();
    let at = now();
    let log = ring::sealed_event(&keys, "ring-log", account, &recipients,
        &json!({"protocol": ring::RING, "accountId": account, "entries": entries}), at).map_err(invalid)?;
    let keyring = ring::sealed_event(&keys, "keyring", account, &recipients,
        &json!({"protocol": ring::KEYRING, "accountId": account, "ringHeads": ring_heads, "items": own}), at).map_err(invalid)?;
    let timeout = Duration::from_secs(settings.transports.nostr.fetch_timeout_secs.max(3));
    let exchange = ring::exchange(&secret, &relays, account, &[log, keyring], true, timeout).await
        .unwrap_or_else(|error| ring::RelayExchange { errors: vec![format!("relays: {error}")], ..Default::default() });

    let (absorbed, final_state) = absorb(db, &keys, account, &exchange.fetched).await?;
    let final_members = member_keys(&final_state);

    // Presence last, so it reports the heads and keyring after this exchange.
    let reachable: HashSet<String> = exchange.published.iter().flat_map(|p| p.accepted.iter().map(|u| u.trim_end_matches('/').to_string())).collect();
    let mut merged_items = copies_of(db, account).await?;
    merged_items.push(json!({"items": own}));
    let merged_items = ring::merge_keyrings(&merged_items);
    let presence = json!({
        "protocol": ring::RING, "type": "presence", "accountId": account, "publicKey": node, "seenAt": now(),
        "software": {"direction": "web", "version": env!("CARGO_PKG_VERSION"), "protocols": PROTOCOLS},
        "ringHeads": heads(&final_state).into_iter().take(16).collect::<Vec<_>>(),
        "keyring": keyring_summary(&merged_items),
        "relays": relays.iter().map(|u| json!({"url": u, "reachable": reachable.contains(u.trim_end_matches('/'))})).collect::<Vec<_>>(),
    });
    let recipients: Vec<String> = final_members.iter().take(ring::MAX_RECIPIENTS).cloned().collect();
    let mut errors = exchange.errors.clone();
    let mut published = exchange.published.clone();
    match ring::sealed_event(&keys, "presence", account, &recipients, &presence, now()) {
        Ok(event) => match ring::exchange(&secret, &relays, account, &[event], false, timeout).await {
            Ok(report) => {
                published.extend(report.published);
                errors.extend(report.errors);
            }
            Err(error) => errors.push(format!("presence: {error}")),
        },
        Err(error) => errors.push(format!("presence: {error}")),
    }
    let min_acks = state["relays"]["minAcks"].as_u64().unwrap_or(1) as usize;
    let report = json!({
        "at": now(),
        "relays": relays,
        "minAcks": min_acks,
        "published": published,
        "quorum": published.iter().all(|p| p.accepted.len() >= min_acks) && !published.is_empty(),
        "fetched": exchange.fetched.len(),
        "notForThisNode": absorbed.not_for_this_node,
        "newEntries": absorbed.new_entries,
        "keyringCopies": absorbed.keyring_copies,
        "presences": absorbed.presences,
        "errors": errors,
    });
    sqlx::query("update account_rings set last_sync_at=now(), last_sync_json=$2 where account_id=$1")
        .bind(account).bind(&report).execute(db).await?;
    Ok(report)
}

/// Background pass for every ring on this node (worker, every SYNC_INTERVAL).
pub async fn sync_all(settings: Arc<Settings>, db: PgPool) {
    let rings = match sqlx::query_as::<_, (Uuid, String)>("select user_id, account_id from account_rings").fetch_all(&db).await {
        Ok(rings) => rings,
        Err(error) => {
            tracing::warn!(error = %error, "could not list device rings");
            return;
        }
    };
    for (user, account) in rings {
        if let Err(error) = sync_account(&settings, &db, user, &account).await {
            tracing::warn!(account_id = %account, error = %error, "device ring sync failed");
        }
    }
}

fn sync_later(state: &AppState, user: Uuid, account: String) {
    let settings = state.settings.clone();
    let db = state.db.clone();
    tokio::spawn(async move {
        if let Err(error) = sync_account(&settings, &db, user, &account).await {
            tracing::warn!(account_id = %account, error = %error, "device ring sync failed");
        }
    });
}

// ---------------------------------------------------------------- handlers

async fn view(state: &AppState, user: Uuid) -> AppResult<Value> {
    let nostr_enabled = state.settings.transports.nostr.enabled;
    if !nostr_enabled {
        return Ok(json!({"enabled": false, "ring": null, "legacy": [], "keyring": null, "presences": [], "skew": [], "lastSync": null}));
    }
    let (_, keys) = node_keys(&state.settings)?;
    let node = keys.public_key().to_hex();
    let peers = sqlx::query_as::<_, (String, String)>(
        "select public_key, to_char(approved_at at time zone 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') from trusted_device_peers where user_id=$1 order by approved_at, public_key")
        .bind(user).fetch_all(&state.db).await?;
    let relays_configured = genesis_relays(&state.settings).ok();
    let Some(account) = account_of(&state.db, user).await? else {
        let legacy: Vec<Value> = peers.into_iter().filter(|(k, _)| *k != node)
            .map(|(k, at)| json!({"publicKey": k, "approvedAt": at})).collect();
        return Ok(json!({"enabled": true, "nodePublicKey": node, "ring": null, "legacy": legacy, "keyring": null,
            "presences": [], "skew": [], "lastSync": null, "relays": relays_configured}));
    };
    let (_, ring_state) = folded(&state.db, &account).await?;
    let in_ring: HashSet<String> = member_keys(&ring_state).into_iter()
        .chain(ring_state["removed"].as_array().into_iter().flatten().filter_map(|m| m["publicKey"].as_str().map(str::to_string)))
        .collect();
    let legacy: Vec<Value> = peers.into_iter().filter(|(k, _)| *k != node && !in_ring.contains(k))
        .map(|(k, at)| json!({"publicKey": k, "approvedAt": at})).collect();
    let own: Vec<Value> = stored_own(&state.db, &account).await?.into_values().collect();
    let mut copies = copies_of(&state.db, &account).await?;
    let copy_count = copies.len();
    copies.push(json!({"items": own}));
    let merged = ring::merge_keyrings(&copies);
    let own_keys: HashSet<(String, String)> = own.iter()
        .map(|i| (i["kind"].as_str().unwrap_or_default().to_string(), i["id"].as_str().unwrap_or_default().to_string())).collect();
    let items: Vec<Value> = merged.iter().map(|i| json!({
        "kind": i["kind"], "id": i["id"], "name": i["name"], "rev": i["rev"], "deleted": i["deleted"],
        "epoch": i["roaming"]["epoch"], "spaceId": i["spaceId"],
        "onThisNode": own_keys.contains(&(i["kind"].as_str().unwrap_or_default().to_string(), i["id"].as_str().unwrap_or_default().to_string())),
    })).collect();
    let presences: Vec<Value> = sqlx::query_scalar("select presence_json from account_ring_presences where account_id=$1 order by public_key")
        .bind(&account).fetch_all(&state.db).await?;
    let skew = ring::presence_skew(&presences, &heads(&ring_state));
    let last: Option<Value> = sqlx::query_scalar("select last_sync_json from account_rings where account_id=$1")
        .bind(&account).fetch_one(&state.db).await?;
    Ok(json!({
        "enabled": true, "nodePublicKey": node, "ring": ring_state, "legacy": legacy,
        "keyring": {"summary": keyring_summary(&merged), "copies": copy_count, "items": items},
        "presences": presences, "skew": skew, "lastSync": last, "relays": relays_configured,
    }))
}

async fn get_ring(State(state): State<AppState>, headers: HeaderMap) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    Ok(ok(view(&state, auth.user_id).await?))
}

#[derive(Deserialize)]
pub struct GenesisInput {
    name: String,
}

async fn genesis(State(state): State<AppState>, headers: HeaderMap, Json(input): Json<GenesisInput>) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let (_, keys) = node_keys(&state.settings)?;
    let name = device_name(&input.name)?;
    let relays = genesis_relays(&state.settings)?;
    let mut nonce = [0u8; 16];
    OsRng.fill_bytes(&mut nonce);
    let body = json!({"type": "genesis", "parents": [], "nonce": ring::b64url(&nonce), "relays": relays,
        "device": {"publicKey": keys.public_key().to_hex(), "name": name, "kind": "web", "role": "admin"}});
    let entry = ring::make_entry(&keys, body.as_object().cloned().unwrap_or_default(), now()).map_err(invalid)?;
    let account = entry["id"].as_str().ok_or_else(AppError::internal)?.to_string();
    let mut tx = state.db.begin().await?;
    let created = sqlx::query("insert into account_rings(user_id,account_id) values($1,$2) on conflict (user_id) do nothing")
        .bind(auth.user_id).bind(&account).execute(&mut *tx).await?.rows_affected();
    if created == 0 {
        return Err(AppError::conflict("Кольцо этого аккаунта уже создано"));
    }
    sqlx::query("insert into account_ring_entries(account_id,id,event_json,source) values($1,$2,$3,'local')")
        .bind(&account).bind(&account).bind(&entry).execute(&mut *tx).await?;
    tx.commit().await?;
    sync_later(&state, auth.user_id, account);
    Ok(ok(view(&state, auth.user_id).await?))
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MigrateInput {
    public_key: String,
    name: String,
    kind: String,
}

async fn migrate(State(state): State<AppState>, headers: HeaderMap, Json(input): Json<MigrateInput>) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let (_, keys) = node_keys(&state.settings)?;
    let account = account_of(&state.db, auth.user_id).await?.ok_or_else(|| AppError::conflict("Сначала создайте кольцо"))?;
    let public_key = hex64(&input.public_key)?;
    let name = device_name(&input.name)?;
    if !["android", "arch", "web"].contains(&input.kind.as_str()) {
        return Err(invalid("вид устройства: android, arch или web"));
    }
    let trusted: bool = sqlx::query_scalar("select exists(select 1 from trusted_device_peers where user_id=$1 and public_key=$2)")
        .bind(auth.user_id).bind(&public_key).fetch_one(&state.db).await?;
    if !trusted {
        return Err(AppError::forbidden("Перенести в кольцо можно только устройство, которому узел уже доверяет; новое устройство добавляется по QR (следующий этап)"));
    }
    let body = json!({"type": "add", "via": "migration",
        "device": {"publicKey": public_key, "name": name, "kind": input.kind, "role": "admin"}});
    append(&state.db, &keys, &account, body.as_object().cloned().unwrap_or_default()).await?;
    sync_later(&state, auth.user_id, account);
    Ok(ok(view(&state, auth.user_id).await?))
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RenameInput {
    public_key: String,
    name: String,
}

async fn rename(State(state): State<AppState>, headers: HeaderMap, Json(input): Json<RenameInput>) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let (_, keys) = node_keys(&state.settings)?;
    let account = account_of(&state.db, auth.user_id).await?.ok_or_else(|| AppError::conflict("Сначала создайте кольцо"))?;
    let body = json!({"type": "rename", "publicKey": hex64(&input.public_key)?, "name": device_name(&input.name)?});
    append(&state.db, &keys, &account, body.as_object().cloned().unwrap_or_default()).await?;
    sync_later(&state, auth.user_id, account);
    Ok(ok(view(&state, auth.user_id).await?))
}

async fn sync(State(state): State<AppState>, headers: HeaderMap) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let account = account_of(&state.db, auth.user_id).await?.ok_or_else(|| AppError::conflict("Сначала создайте кольцо"))?;
    sync_account(&state.settings, &state.db, auth.user_id, &account).await?;
    Ok(ok(view(&state, auth.user_id).await?))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(kind: &str, id: &str) -> (String, String) {
        (kind.to_string(), id.to_string())
    }

    #[test]
    fn keyring_revs_grow_on_change_and_deletion_drops_the_key() {
        let node = "ab".repeat(32);
        let board = json!({"kind": "board", "id": "b", "spaceId": "s", "name": "План", "deleted": false,
            "roaming": {"protocol": ring::ROAMING, "epoch": 1, "boardKey": "k"}});
        let mut current = BTreeMap::from([(key("board", "b"), board.clone())]);
        let first = next_own_items(&BTreeMap::new(), &current, &BTreeMap::new(), &node);
        assert_eq!(first[&key("board", "b")]["rev"], 1);
        assert_eq!(next_own_items(&first, &current, &BTreeMap::new(), &node), first, "no change, no new rev");

        current.get_mut(&key("board", "b")).unwrap()["name"] = json!("План на октябрь");
        let seen = BTreeMap::from([(key("board", "b"), 4)]);
        let renamed = next_own_items(&first, &current, &seen, &node);
        assert_eq!(renamed[&key("board", "b")]["rev"], 5, "a rename beats the highest rev seen on other devices");

        let gone = next_own_items(&renamed, &BTreeMap::new(), &BTreeMap::new(), &node);
        let item = &gone[&key("board", "b")];
        assert_eq!((item["deleted"].clone(), item["rev"].clone(), item.get("roaming").is_none()), (json!(true), json!(6), true));
        assert_eq!(next_own_items(&gone, &BTreeMap::new(), &BTreeMap::new(), &node), gone, "deletion is stable");
    }
}
