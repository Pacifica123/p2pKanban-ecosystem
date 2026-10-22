//! R4 of the device ring: adding a device by QR (contracts/rendezvous/1).
//!
//! The node only shows codes; the phone scans. Two modes:
//! - `invite`: the node is the sponsor. A phone scans, says hello, the person
//!   compares the six-digit code and confirms here; the node writes `add` and
//!   sends the whole ring log and keyring in `welcome`.
//! - `join`: the node is the joiner. It puts its hello into the mailbox at
//!   once; a phone of a ring scans and confirms; the node checks `welcome`,
//!   adopts that ring (its own ring, if it had one, must be just itself) and
//!   answers `ack`.
//!
//! The web UI polls `GET /ring/rendezvous/{id}`; every poll reads the mailbox
//! on the QR's relays and moves the meeting on.

use std::{collections::BTreeSet, time::Duration};

use axum::{
    extract::{Path, State},
    http::HeaderMap,
    routing::{get, post},
    Json, Router,
};
use p2p_kanban_nostr_transport::{rendezvous as rv, ring};
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

use super::ring::{
    account_of, append, copies_of, device_name, folded, genesis_relays, heads, invalid, member_keys, node_keys, now,
    refresh_own_keyring, sync_later, trust_members, adopt_items, PROTOCOLS,
};
use crate::{
    config::Settings,
    error::{AppError, AppResult},
    http::response::{ok, ApiEnvelope},
    modules::common::auth_context,
    state::AppState,
};

/// How long a shown QR is valid.
pub const QR_LIFETIME_SECS: u64 = 600;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/ring/rendezvous", post(start))
        .route("/ring/rendezvous/{session}", get(poll))
        .route("/ring/rendezvous/{session}/confirm", post(confirm))
        .route("/ring/rendezvous/{session}/cancel", post(cancel))
}

struct Session {
    id: String,
    mode: String,
    qr: Value,
    secret: Option<Vec<u8>>,
    expires_at: u64,
    status: String,
    peer: Option<Value>,
    outcome: Option<Value>,
}

impl Session {
    fn relays(&self) -> Vec<String> {
        self.qr["r"].as_array().into_iter().flatten().filter_map(Value::as_str).map(str::to_string).collect()
    }

    fn open(&self) -> bool {
        matches!(self.status.as_str(), "waiting" | "confirm" | "welcomed")
    }

    fn view(&self, node: &str) -> Value {
        let showing = matches!(self.status.as_str(), "waiting" | "confirm") && self.secret.is_some();
        // Both screens show the code of the joiner's key: here the node itself in
        // `join`, the phone that said hello in `invite`.
        let code = match self.mode.as_str() {
            "join" => Some(rv::confirm_code(&self.id, node)),
            _ => self.peer.as_ref().and_then(|p| p["code"].as_str().map(str::to_string)),
        };
        json!({
            "sessionId": self.id, "mode": self.mode, "status": self.status,
            "qrText": showing.then(|| rv::qr_encode(&self.qr)), "expiresAt": self.expires_at,
            "relays": self.relays(), "code": code, "peer": self.peer, "outcome": self.outcome,
        })
    }
}

async fn load(db: &PgPool, user: Uuid, id: &str) -> AppResult<Session> {
    let row = sqlx::query("select session_id, mode, qr_json, secret_b64, expires_at, status, peer_json, outcome_json
                           from ring_rendezvous_sessions where session_id=$1 and user_id=$2")
        .bind(id).bind(user).fetch_optional(db).await?
        .ok_or_else(|| AppError::not_found("Встреча не найдена"))?;
    let secret: Option<String> = row.try_get("secret_b64")?;
    Ok(Session {
        id: row.try_get("session_id")?,
        mode: row.try_get("mode")?,
        qr: row.try_get("qr_json")?,
        secret: secret.and_then(|s| ring::unb64url(&s).ok()),
        expires_at: row.try_get::<i64, _>("expires_at")? as u64,
        status: row.try_get("status")?,
        peer: row.try_get("peer_json")?,
        outcome: row.try_get("outcome_json")?,
    })
}

async fn save(db: &PgPool, session: &Session) -> AppResult<()> {
    // The secret is erased once the meeting cannot go on.
    let keep_secret = session.open();
    sqlx::query("update ring_rendezvous_sessions set status=$2, peer_json=$3, outcome_json=$4,
                 secret_b64=case when $5 then secret_b64 else null end, updated_at=now() where session_id=$1")
        .bind(&session.id).bind(&session.status).bind(&session.peer).bind(&session.outcome).bind(keep_secret)
        .execute(db).await?;
    Ok(())
}

fn timeout(settings: &Settings) -> Duration {
    Duration::from_secs(settings.transports.nostr.fetch_timeout_secs.clamp(2, 5))
}

fn hello(node: &str, name: &str, session: &str, ring: Value) -> Value {
    json!({"type": "hello", "sessionId": session,
        "device": {"publicKey": node, "name": name, "kind": "web"},
        "software": {"direction": "web", "version": env!("CARGO_PKG_VERSION"), "protocols": PROTOCOLS},
        "ring": ring})
}

async fn send(settings: &Settings, session: &Session, message: Value) -> AppResult<()> {
    let (secret_key, keys) = node_keys(settings)?;
    let secret = session.secret.as_deref().ok_or_else(|| AppError::conflict("Встреча уже закончилась"))?;
    let events = rv::mailbox_events(&keys, secret, &message, now(), session.expires_at).map_err(invalid)?;
    let (accepted, errors) = rv::post(&secret_key, &session.relays(), &events, timeout(settings)).await.map_err(invalid)?;
    if accepted.is_empty() {
        return Err(AppError::conflict(format!("Ни один relay встречи не принял сообщение: {}", errors.join("; "))));
    }
    Ok(())
}

async fn mailbox(settings: &Settings, session: &Session) -> AppResult<Vec<rv::Mail>> {
    let Some(secret) = session.secret.as_deref() else { return Ok(Vec::new()) };
    let events = rv::fetch(&session.relays(), &session.id, timeout(settings)).await
        .map_err(|e| AppError::conflict(format!("Почтовый ящик встречи недоступен: {e}")))?;
    Ok(rv::open_mailbox(&events, secret))
}

fn refused(by: &str, reason: &str, detail: &str) -> Value {
    json!({"by": by, "reason": reason, "detail": detail})
}

// ---------------------------------------------------------------- start

#[derive(Deserialize)]
pub struct StartInput {
    mode: String,
    name: Option<String>,
}

async fn start(State(state): State<AppState>, headers: HeaderMap, Json(input): Json<StartInput>) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let (_, keys) = node_keys(&state.settings)?;
    let node = keys.public_key().to_hex();
    let account = account_of(&state.db, auth.user_id).await?;
    let ring_state = match &account {
        Some(account) => Some(folded(&state.db, account).await?.1),
        None => None,
    };
    let own_name = ring_state.as_ref().and_then(|s| s["members"].as_array().into_iter().flatten()
        .find(|m| m["publicKey"] == node.as_str()).and_then(|m| m["name"].as_str().map(str::to_string)));
    let ring_relays = ring_state.as_ref().map(|s| s["relays"]["urls"].as_array().into_iter().flatten()
        .filter_map(Value::as_str).map(str::to_string).collect::<Vec<_>>());
    let (relays, name) = match input.mode.as_str() {
        "invite" => {
            let s = ring_state.as_ref().ok_or_else(|| AppError::conflict("Сначала создайте кольцо: в режиме «Войти в кольцо узла» телефон входит в кольцо этого узла"))?;
            let me = s["members"].as_array().into_iter().flatten().find(|m| m["publicKey"] == node.as_str());
            if me.is_none_or(|m| m["role"] != "admin") {
                return Err(AppError::conflict("Добавлять устройства может только участник кольца с ролью admin"));
            }
            if s["readerOutdated"].as_array().is_some_and(|o| !o.is_empty()) {
                return Err(AppError::conflict("Журнал кольца содержит записи более новой версии: обновите узел, прежде чем добавлять устройства"));
            }
            (ring_relays.unwrap_or_default(), own_name.unwrap_or_else(|| "Web-узел".into()))
        }
        "join" => {
            let relays = match ring_relays {
                Some(relays) => relays,
                None => genesis_relays(&state.settings)?["urls"].as_array().into_iter().flatten()
                    .filter_map(Value::as_str).map(str::to_string).collect(),
            };
            let name = match input.name.as_deref().map(str::trim).filter(|n| !n.is_empty()) {
                Some(name) => device_name(name)?,
                None => own_name.unwrap_or_else(|| "Web-узел".into()),
            };
            (relays, name)
        }
        _ => return Err(invalid("режим встречи: invite или join")),
    };
    let (qr, secret) = rv::new_qr(&input.mode, &node, &name, "web", &relays, now(), QR_LIFETIME_SECS).map_err(invalid)?;
    let session = Session {
        id: rv::session_id(&secret), mode: input.mode.clone(), qr, secret: Some(secret),
        expires_at: 0, status: "waiting".into(), peer: None, outcome: None,
    };
    let session = Session { expires_at: session.qr["x"].as_u64().unwrap_or(0), ..session };
    sqlx::query("insert into ring_rendezvous_sessions(session_id,user_id,mode,qr_json,secret_b64,expires_at) values($1,$2,$3,$4,$5,$6)")
        .bind(&session.id).bind(auth.user_id).bind(&session.mode).bind(&session.qr)
        .bind(session.secret.as_deref().map(ring::b64url)).bind(session.expires_at as i64)
        .execute(&state.db).await?;
    if session.mode == "join" {
        // The joiner always writes first: the hello waits in the mailbox before the scan.
        let ring = match (&account, &ring_state) {
            (Some(account), Some(s)) => json!({"accountId": account, "members": member_keys(s).len()}),
            _ => Value::Null,
        };
        send(&state.settings, &session, hello(&node, &name, &session.id, ring)).await?;
    }
    Ok(ok(session.view(&node)))
}

// ---------------------------------------------------------------- poll

async fn poll(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let (_, keys) = node_keys(&state.settings)?;
    let node = keys.public_key().to_hex();
    let mut session = load(&state.db, auth.user_id, &id).await?;
    advance(&state, auth.user_id, &node, &mut session).await?;
    Ok(ok(session.view(&node)))
}

async fn advance(state: &AppState, user: Uuid, node: &str, session: &mut Session) -> AppResult<()> {
    if !session.open() {
        return Ok(());
    }
    if now() > session.expires_at && session.status != "welcomed" {
        session.status = "expired".into();
        session.outcome = Some(refused(node, "expired", "Срок QR истёк (10 минут). Покажите новый код."));
        return save(&state.db, session).await;
    }
    let mails = mailbox(&state.settings, session).await?;
    let from_peer: Vec<&rv::Mail> = mails.iter().filter(|m| m.sender != node).collect();
    if let Some(refuse) = from_peer.iter().find(|m| m.message["type"] == "refuse") {
        session.status = "refused".into();
        session.outcome = Some(refused(&refuse.sender, refuse.message["reason"].as_str().unwrap_or("declined"),
            refuse.message["detail"].as_str().unwrap_or("")));
        return save(&state.db, session).await;
    }
    match session.mode.as_str() {
        "invite" => advance_sponsor(state, user, node, session, &mails).await,
        _ => advance_joiner(state, user, node, session, &from_peer).await,
    }
}

async fn advance_sponsor(state: &AppState, user: Uuid, node: &str, session: &mut Session, mails: &[rv::Mail]) -> AppResult<()> {
    if session.status == "welcomed" {
        let joiner = session.peer.as_ref().and_then(|p| p["publicKey"].as_str()).unwrap_or_default();
        if let Some(ack) = mails.iter().find(|m| m.sender == joiner && m.message["type"] == "ack") {
            session.status = "done".into();
            session.outcome = Some(json!({"accountId": ack.message["accountId"], "heads": ack.message["heads"], "joined": session.peer}));
            save(&state.db, session).await?;
            if let Some(account) = account_of(&state.db, user).await? {
                sync_later(state, user, account);
            }
        }
        return Ok(());
    }
    let account = account_of(&state.db, user).await?.ok_or_else(|| AppError::conflict("Кольцо этого узла не найдено"))?;
    let (_, ring_state) = folded(&state.db, &account).await?;
    let fresh = ring_state["readerOutdated"].as_array().is_none_or(|o| o.is_empty());
    match rv::sponsor_review(&session.qr, mails, node, &ring_state, fresh, now()) {
        Ok(None) => Ok(()),
        Ok(Some(hello)) => {
            let joiner = hello["device"]["publicKey"].as_str().unwrap_or_default();
            let member = member_keys(&ring_state).iter().any(|k| k == joiner);
            session.status = "confirm".into();
            session.peer = Some(json!({
                "publicKey": joiner, "name": hello["device"]["name"], "kind": hello["device"]["kind"],
                "software": hello["software"], "ring": hello["ring"], "alreadyMember": member,
                "code": rv::confirm_code(&session.id, joiner),
            }));
            save(&state.db, session).await
        }
        Err(refusal) => {
            send(&state.settings, session, refusal.message(&session.id)).await?;
            session.status = "refused".into();
            session.outcome = Some(refused(node, refusal.reason, &refusal.detail));
            save(&state.db, session).await
        }
    }
}

async fn advance_joiner(state: &AppState, user: Uuid, node: &str, session: &mut Session, from_peer: &[&rv::Mail]) -> AppResult<()> {
    let welcomes: Vec<&&rv::Mail> = from_peer.iter().filter(|m| m.message["type"] == "welcome").collect();
    let senders: BTreeSet<&str> = welcomes.iter().map(|m| m.sender.as_str()).collect();
    if senders.len() > 1 {
        return refuse_as_joiner(state, node, session, "contested", "Ответили два разных устройства: QR мог увидеть кто-то ещё. Покажите новый код.").await;
    }
    let Some(welcome) = welcomes.last() else { return Ok(()) };
    let ring_state = match rv::verify_welcome(welcome, &session.qr, node) {
        Ok(state) => state,
        Err(refusal) => return refuse_as_joiner(state, node, session, refusal.reason, &refusal.detail).await,
    };
    let account = ring_state["accountId"].as_str().ok_or_else(AppError::internal)?.to_string();
    if let Err(detail) = adopt_ring(&state.db, user, &account, welcome).await? {
        return refuse_as_joiner(state, node, session, "ring-merge-unsupported", &detail).await;
    }
    trust_members(&state.db, user, &ring_state, node).await?;
    adopt_items(&state.db, user, &account).await?;
    let sponsor = ring_state["members"].as_array().into_iter().flatten().find(|m| m["publicKey"] == welcome.sender.as_str());
    send(&state.settings, session, json!({"type": "ack", "sessionId": session.id, "accountId": account,
        "heads": heads(&ring_state).into_iter().take(16).collect::<Vec<_>>()})).await?;
    session.status = "done".into();
    session.peer = sponsor.map(|m| json!({"publicKey": m["publicKey"], "name": m["name"], "kind": m["kind"]}));
    session.outcome = Some(json!({"accountId": account, "members": member_keys(&ring_state).len()}));
    save(&state.db, session).await?;
    sync_later(state, user, account);
    Ok(())
}

async fn refuse_as_joiner(state: &AppState, node: &str, session: &mut Session, reason: &'static str, detail: &str) -> AppResult<()> {
    let message = json!({"type": "refuse", "sessionId": session.id, "reason": reason, "detail": detail});
    // Best effort: the outcome is recorded here even if no relay takes the refusal.
    if let Err(error) = send(&state.settings, session, message).await {
        tracing::warn!(session = %session.id, error = %error, "could not send rendezvous refusal");
    }
    session.status = "refused".into();
    session.outcome = Some(refused(node, reason, detail));
    save(&state.db, session).await
}

/// Make the welcomed ring this user's ring on the node. A previous ring of the
/// node is replaced only when nobody else is in it. `Ok(Err(detail))` refuses.
async fn adopt_ring(db: &PgPool, user: Uuid, account: &str, welcome: &rv::Mail) -> AppResult<Result<(), String>> {
    let current = account_of(db, user).await?;
    let owner: Option<Uuid> = sqlx::query_scalar("select user_id from account_rings where account_id=$1").bind(account).fetch_optional(db).await?;
    if owner.is_some_and(|o| o != user) {
        return Ok(Err("Это кольцо на узле уже у другого пользователя: одно кольцо — один аккаунт.".into()));
    }
    if let Some(current) = current.as_deref().filter(|c| *c != account) {
        let (_, old) = folded(db, current).await?;
        let members = member_keys(&old).len();
        if members > 1 {
            return Ok(Err(format!("Этот узел уже в другом кольце из {members} устройств. Слияние колец пока не поддерживается.")));
        }
    }
    let mut tx = db.begin().await?;
    if current.as_deref().is_some_and(|c| c != account) {
        sqlx::query("delete from account_rings where user_id=$1").bind(user).execute(&mut *tx).await?;
    }
    sqlx::query("insert into account_rings(user_id,account_id) values($1,$2) on conflict (user_id) do nothing")
        .bind(user).bind(account).execute(&mut *tx).await?;
    for entry in welcome.message["entries"].as_array().into_iter().flatten().take(ring::MAX_ENTRIES) {
        let Some(id) = entry["id"].as_str() else { continue };
        sqlx::query("insert into account_ring_entries(account_id,id,event_json,source) values($1,$2,$3,'relay') on conflict do nothing")
            .bind(account).bind(id).bind(entry).execute(&mut *tx).await?;
    }
    sqlx::query("insert into account_keyring_copies(account_id,author_public_key,created_at,keyring_json) values($1,$2,$3,$4)
                 on conflict (account_id,author_public_key) do update set created_at=excluded.created_at, keyring_json=excluded.keyring_json, received_at=now()
                 where account_keyring_copies.created_at<excluded.created_at")
        .bind(account).bind(&welcome.sender).bind(welcome.created_at as i64).bind(&welcome.message["keyring"])
        .execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(Ok(()))
}

// ---------------------------------------------------------------- confirm, cancel

#[derive(Deserialize, Default)]
pub struct ConfirmInput {
    role: Option<String>,
}

async fn confirm(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>, input: Option<Json<ConfirmInput>>) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let (_, keys) = node_keys(&state.settings)?;
    let node = keys.public_key().to_hex();
    let role = input.and_then(|Json(i)| i.role).unwrap_or_else(|| "admin".into());
    if !matches!(role.as_str(), "admin" | "member") {
        return Err(invalid("роль: admin или member"));
    }
    let mut session = load(&state.db, auth.user_id, &id).await?;
    if session.mode != "invite" {
        return Err(AppError::conflict("Подтверждают на устройстве, которое сканировало QR"));
    }
    // Read the mailbox once more: a second hello since the last poll stops the meeting.
    advance(&state, auth.user_id, &node, &mut session).await?;
    if session.status != "confirm" {
        return Ok(ok(session.view(&node)));
    }
    let peer = session.peer.clone().ok_or_else(AppError::internal)?;
    let joiner = peer["publicKey"].as_str().ok_or_else(AppError::internal)?.to_string();
    let account = account_of(&state.db, auth.user_id).await?.ok_or_else(AppError::internal)?;
    refresh_own_keyring(&state.settings, &state.db, auth.user_id, &account, &node).await?;
    let (_, before) = folded(&state.db, &account).await?;
    if !member_keys(&before).contains(&joiner) {
        // Re-connecting a member writes nothing: welcome alone is the remote repair.
        let body = json!({"type": "add", "via": "rendezvous",
            "device": {"publicKey": joiner, "name": peer["name"], "kind": peer["kind"], "role": role}});
        append(&state.db, &keys, &account, body.as_object().cloned().unwrap_or_default()).await?;
    }
    let (entries, after) = folded(&state.db, &account).await?;
    trust_members(&state.db, auth.user_id, &after, &node).await?;
    let mut copies = copies_of(&state.db, &account).await?;
    copies.push(json!({"items": super::ring::stored_own(&state.db, &account).await?.into_values().collect::<Vec<_>>()}));
    let welcome = json!({"type": "welcome", "sessionId": session.id, "accountId": account, "entries": entries,
        "keyring": {"protocol": ring::KEYRING, "accountId": account, "ringHeads": heads(&after), "items": ring::merge_keyrings(&copies)}});
    send(&state.settings, &session, welcome).await?;
    session.status = "welcomed".into();
    save(&state.db, &session).await?;
    sync_later(&state, auth.user_id, account);
    Ok(ok(session.view(&node)))
}

async fn cancel(State(state): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let (_, keys) = node_keys(&state.settings)?;
    let node = keys.public_key().to_hex();
    let mut session = load(&state.db, auth.user_id, &id).await?;
    if session.open() && session.status != "welcomed" {
        let detail = "Человек отменил встречу на узле.";
        if session.status == "confirm" || session.mode == "join" {
            let message = json!({"type": "refuse", "sessionId": session.id, "reason": "declined", "detail": detail});
            if let Err(error) = send(&state.settings, &session, message).await {
                tracing::warn!(session = %session.id, error = %error, "could not send rendezvous refusal");
            }
        }
        session.status = "canceled".into();
        session.outcome = Some(refused(&node, "declined", detail));
        save(&state.db, &session).await?;
    }
    Ok(ok(session.view(&node)))
}
