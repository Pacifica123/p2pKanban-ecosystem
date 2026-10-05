use super::{dto::NodeLinkExportResponse, pairing, repo, service};
use crate::{
    error::{AppError, AppResult},
    http::response::{ok, ApiEnvelope},
    modules::common::{auth_context, require_workspace_access},
    state::AppState,
};
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::Response,
    Json,
};
use p2p_kanban_nostr_transport::device_link as protocol;
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::Row;
use uuid::Uuid;
fn invalid(e: impl std::fmt::Display) -> AppError {
    AppError::bad_request(format!("Device link: {e}"))
}
pub(super) fn secret(state: &AppState) -> AppResult<&str> {
    if !state.settings.transports.nostr.enabled {
        return Err(AppError::conflict("Enable Nostr roaming first"));
    }
    state
        .settings
        .transports
        .nostr
        .secret_key
        .as_deref()
        .ok_or_else(AppError::internal)
}
pub async fn issue_chain(
    state: &AppState,
    board: Uuid,
    user: Uuid,
    subject: &str,
) -> AppResult<Vec<Value>> {
    let(workspace,epoch)=sqlx::query_as::<_,(Uuid,i64)>("select b.workspace_id,w.access_epoch from boards b join workspaces w on w.id=b.workspace_id where b.id=$1 and b.deleted_at is null and w.deleted_at is null").bind(board).fetch_one(&state.db).await?;
    if require_workspace_access(&state.db, workspace, user)
        .await?
        .as_deref()
        != Some("owner")
    {
        return Err(AppError::forbidden(
            "Only an owner may delegate device access",
        ));
    }
    let stored = sqlx::query_scalar::<_, Value>(
        "select chain_json from roaming_device_grants where board_id=$1 and epoch=$2",
    )
    .bind(board)
    .bind(epoch)
    .fetch_optional(&state.db)
    .await?;
    let key = secret(state)?;
    if let Some(raw) = stored {
        let chain: Vec<Value> = serde_json::from_value(raw).map_err(invalid)?;
        protocol::verify_chain(
            &chain,
            &protocol::public_key(key).map_err(invalid)?,
            protocol::now(),
        )
        .map_err(invalid)?;
        if subject == protocol::public_key(key).map_err(invalid)? {
            return Ok(chain);
        }
        return protocol::extend(key, &chain, subject).map_err(invalid);
    }
    let g = protocol::Grant {
        protocol: protocol::PROTOCOL.into(),
        workspace_id: workspace.to_string(),
        board_id: board.to_string(),
        user_id: user.to_string(),
        epoch,
        subject: subject.into(),
        can_delegate: true,
        parent_id: None,
        expires_at: protocol::now() + 90 * 86400,
    };
    Ok(vec![protocol::sign(
        key,
        protocol::GRANT_KIND,
        &serde_json::to_value(g).map_err(invalid)?,
    )
    .map_err(invalid)?])
}
pub(super) async fn prepared(state: &AppState, user_id: Uuid, subject: &str) -> AppResult<Value> {
    let user = repo::find_active_user_by_id(&state.db, user_id)
        .await?
        .ok_or_else(AppError::internal)?;
    let snapshot = pairing::export_for_user(state, user).await?;
    if snapshot.board_capabilities.is_empty() {
        return Err(AppError::conflict("Нет досок владельца для подключения"));
    }
    let mut chains = serde_json::Map::new();
    for cap in &snapshot.board_capabilities {
        chains.insert(
            cap.board_id.to_string(),
            serde_json::to_value(issue_chain(state, cap.board_id, user_id, subject).await?)
                .map_err(invalid)?,
        );
    }
    Ok(json!({"snapshot":snapshot,"chains":chains}))
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Prepare {
    author_public_key: String,
}
pub async fn prepare(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(input): Json<Prepare>,
) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let data = prepared(&state, auth.user_id, &input.author_public_key).await?;
    sqlx::query("insert into trusted_device_peers(user_id,public_key) values($1,$2) on conflict do nothing")
      .bind(auth.user_id).bind(&input.author_public_key).execute(&state.db).await?;
    let parts =
        protocol::encrypt(secret(&state)?, &input.author_public_key, &data).map_err(invalid)?;
    Ok(ok(protocol::sign(secret(&state)?,protocol::RESPONSE_KIND,&json!({"protocol":protocol::PROTOCOL,"recipient":input.author_public_key,"requestId":"preparation","parts":parts})).map_err(invalid)?))
}
pub async fn request(State(state): State<AppState>) -> AppResult<Json<ApiEnvelope<Value>>> {
    pairing::ensure_empty_destination(&state).await?;
    create_request(&state, false).await
}
pub async fn supplement_request(State(state): State<AppState>, headers: HeaderMap) -> AppResult<Json<ApiEnvelope<Value>>> {
    auth_context(&state, &headers).await?;
    create_request(&state, true).await
}
pub(super) async fn create_request(state: &AppState, supplement: bool) -> AppResult<Json<ApiEnvelope<Value>>> {
    let key = secret(&state)?;
    let now = protocol::now();
    let mut tx = state.db.begin().await?;
    sqlx::query("select pg_advisory_xact_lock(2026090601)")
        .execute(&mut *tx)
        .await?;
    sqlx::query("delete from device_link_challenges where expires_at<$1 and consumed_at is null")
        .bind(now as i64)
        .execute(&mut *tx)
        .await?;
    if !supplement { if let Some(e)=sqlx::query_scalar::<_,Value>("select request_json from device_link_challenges where consumed_at is null and expires_at>$1 order by created_at desc limit 1").bind(now as i64).fetch_optional(&mut *tx).await?{tx.commit().await?;return Ok(ok(e));} }
    let e=protocol::sign(key,protocol::REQUEST_KIND,&json!({"protocol":protocol::PROTOCOL,"nonce":Uuid::now_v7().to_string(),"expiresAt":now+600,"label":"Самостоятельный узел p2pKanban","supplement":supplement})).map_err(invalid)?;
    sqlx::query("insert into device_link_challenges(id,request_json,expires_at) values($1,$2,$3)")
        .bind(e["id"].as_str().unwrap())
        .bind(&e)
        .bind((now + 600) as i64)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(ok(e))
}
pub(super) fn check_request(raw: &Value) -> AppResult<(String, String, u64)> {
    let (recipient, id, b) =
        protocol::checked_event(raw, protocol::REQUEST_KIND).map_err(invalid)?;
    let expiry = b["expiresAt"]
        .as_u64()
        .ok_or_else(|| invalid("missing expiry"))?;
    if b["protocol"] != protocol::PROTOCOL
        || expiry <= protocol::now()
        || expiry > protocol::now() + 660
    {
        return Err(invalid("Запрос истёк или имеет неверный срок"));
    }
    Ok((recipient, id, expiry))
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Approve {
    request: Value,
    confirmed_request_id: String,
}
pub async fn approve(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(input): Json<Approve>,
) -> AppResult<Json<ApiEnvelope<Value>>> {
    let auth = auth_context(&state, &headers).await?;
    let (recipient, id, expiry) = check_request(&input.request)?;
    if input.confirmed_request_id != id {
        return Err(invalid("Подтвердите отпечаток на новом устройстве"));
    }
    let data = prepared(&state, auth.user_id, &recipient).await?;
    let parts = protocol::encrypt(secret(&state)?, &recipient, &data).map_err(invalid)?;
    sqlx::query("insert into trusted_device_peers(user_id,public_key) values($1,$2) on conflict do nothing")
      .bind(auth.user_id).bind(&recipient).execute(&state.db).await?;
    Ok(ok(protocol::sign(secret(&state)?,protocol::RESPONSE_KIND,&json!({"protocol":protocol::PROTOCOL,"recipient":recipient,"requestId":id,"expiresAt":expiry,"parts":parts})).map_err(invalid)?))
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Accept {
    response: Value,
    #[serde(default)]
    password: String,
    #[serde(default)]
    supplement: bool,
    confirmed_sender: String,
}
pub async fn accept(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(input): Json<Accept>,
) -> AppResult<Response> {
    let local_user = if input.supplement { Some(auth_context(&state, &headers).await?.user_id) }
        else { service::validate_password(&input.password)?; None };
    let key = secret(&state)?;
    let recipient = protocol::public_key(key).map_err(invalid)?;
    let (sender, _, body) =
        protocol::checked_event(&input.response, protocol::RESPONSE_KIND).map_err(invalid)?;
    if input.confirmed_sender != sender
        || body["recipient"] != recipient
        || body["protocol"] != protocol::PROTOCOL
    {
        return Err(invalid(
            "Неверное устройство или неподтверждённый отправитель",
        ));
    }
    let expiry = body["expiresAt"]
        .as_u64()
        .ok_or_else(|| invalid("missing expiry"))?;
    if expiry <= protocol::now() {
        return Err(invalid("Приглашение истекло"));
    }
    let id = body["requestId"]
        .as_str()
        .ok_or_else(|| invalid("missing request ID"))?;
    let parts: Vec<String> = serde_json::from_value(body["parts"].clone()).map_err(invalid)?;
    let data = protocol::decrypt(key, &sender, &parts).map_err(invalid)?;
    let remote: NodeLinkExportResponse =
        serde_json::from_value(data["snapshot"].clone()).map_err(invalid)?;
    let chains = data["chains"]
        .as_object()
        .ok_or_else(|| invalid("missing delegations"))?;
    pairing::validate_remote_snapshot(
        &state,
        &remote,
        &service::normalize_email(&remote.user.email)?,
    )?;
    if chains.len() != remote.board_capabilities.len() {
        return Err(invalid("Набор прав не совпадает с досками"));
    }
    let mut verified = Vec::new();
    let mut epochs = std::collections::HashMap::new();
    for cap in &remote.board_capabilities {
        let chain: Vec<Value> = serde_json::from_value(
            chains
                .get(&cap.board_id.to_string())
                .cloned()
                .ok_or_else(|| invalid("missing grant"))?,
        )
        .map_err(invalid)?;
        let (root, g) =
            protocol::verify_chain(&chain, &recipient, protocol::now()).map_err(invalid)?;
        if chain.last().and_then(|e| e["pubkey"].as_str()) != Some(sender.as_str())
            || g.board_id != cap.board_id.to_string()
            || g.user_id != remote.user.id.to_string()
            || !g.can_delegate
        {
            return Err(invalid("Delegation identity mismatch"));
        }
        let workspace = Uuid::parse_str(&g.workspace_id).map_err(invalid)?;
        if epochs
            .insert(workspace, g.epoch)
            .is_some_and(|epoch| epoch != g.epoch)
        {
            return Err(invalid("Conflicting workspace epochs"));
        }
        if !remote.workspaces.iter().any(|w| {
            w.bundle.manifest_json.workspace_id == Some(workspace)
                && w.bundle
                    .payload
                    .boards
                    .as_array()
                    .is_some_and(|b| b.iter().any(|v| v["id"] == cap.board_id.to_string()))
        }) {
            return Err(invalid("Delegation workspace mismatch"));
        }
        verified.push((cap.board_id, workspace, root, g.epoch, chain));
    }
    if local_user.is_some_and(|user| user != remote.user.id) { return Err(AppError::forbidden("Разрешение принадлежит другому аккаунту")); }
    let password_hash = if input.supplement { String::new() } else { service::hash_password(&input.password)? };
    let mut tx = state.db.begin().await?;
    // Admission, snapshot and nonce consumption commit together; sign-up races cannot merge identities.
    sqlx::query("lock table users,workspaces,boards in exclusive mode")
        .execute(&mut *tx)
        .await?;
    let occupied=sqlx::query_scalar::<_,bool>("select exists(select 1 from users) or exists(select 1 from workspaces) or exists(select 1 from boards)").fetch_one(&mut *tx).await?;
    if occupied && !input.supplement {
        return Err(AppError::conflict(
            "Нужен пустой узел. Существующие данные сохранены",
        ));
    }
    let request=sqlx::query("select request_json,consumed_at is not null as used from device_link_challenges where id=$1 for update").bind(id).fetch_optional(&mut *tx).await?.ok_or_else(||invalid("Неизвестный запрос"))?;
    let (_, rid, rexp) = check_request(&request.try_get::<Value, _>("request_json")?)?;
    let request_body = protocol::checked_event(&request.try_get::<Value, _>("request_json")?, protocol::REQUEST_KIND).map_err(invalid)?.2;
    if request_body["supplement"].as_bool().unwrap_or(false) != input.supplement { return Err(invalid("Режим запроса не совпадает с режимом принятия")); }
    if rid != id || rexp != expiry || request.try_get::<bool, _>("used")? {
        return Err(invalid("Приглашение уже использовано или истекло"));
    }
    if input.supplement {
        // Admit a new key only when an existing approved key has actually
        // delegated to this signer. A signed response by itself proves no trust.
        let mut trusted=sqlx::query_scalar::<_,bool>(
            "select exists(select 1 from trusted_device_peers where user_id=$1 and public_key=$2)")
            .bind(remote.user.id).bind(&sender).fetch_one(&mut *tx).await?;
        if !trusted {
            for (_,_,root,_,_) in &verified {
                if root==&recipient {trusted=true;break;}
                trusted=sqlx::query_scalar::<_,bool>(r#"
                    select exists(select 1 from trusted_device_peers where user_id=$1 and public_key=$2)
                    or exists(select 1 from roaming_device_grants g join boards b on b.id=g.board_id
                      join workspaces w on w.id=b.workspace_id where g.user_id=$1 and g.root_key=$2
                      and g.epoch=w.access_epoch and w.owner_user_id=$1 and w.deleted_at is null)
                "#).bind(remote.user.id).bind(root).fetch_one(&mut *tx).await?;
                if trusted {break;}
            }
        }
        if !trusted {return Err(AppError::forbidden("Нет подтверждённого доверия к устройству отправителя"));}
        sqlx::query("insert into trusted_device_peers(user_id,public_key) values($1,$2) on conflict do nothing")
            .bind(remote.user.id).bind(&sender).execute(&mut *tx).await?;
        let added = super::device_supplement::import_missing(&mut tx, &remote, &verified).await?;
        sqlx::query("update device_link_challenges set consumed_at=now() where id=$1").bind(id).execute(&mut *tx).await?;
        tx.commit().await?;
        use axum::response::IntoResponse;
        return Ok(ok(json!({"addedBoards":added,"mode":"add-missing-boards"})).into_response());
    }
    pairing::import_user(&mut tx, &remote, &password_hash).await?;
    for w in &remote.workspaces {
        pairing::import_workspace_bundle(&mut tx, remote.user.id, &w.bundle).await?;
    }
    pairing::import_user_appearance(&mut tx, remote.user.id, remote.user_appearance.as_ref())
        .await?;
    pairing::import_board_capabilities(&mut tx, &remote.board_capabilities).await?;
    pairing::import_card_tombstones(&mut tx, &remote.card_tombstones).await?;
    let verified_roots:Vec<String>=verified.iter().map(|(_,_,root,_,_)|root.clone()).collect();
    for (board, workspace, root, epoch, chain) in verified {
        sqlx::query("update workspaces set access_epoch=$2 where id=$1")
            .bind(workspace)
            .bind(epoch)
            .execute(&mut *tx)
            .await?;
        sqlx::query("update roaming_board_capabilities set capability_epoch=$2 where board_id=$1")
            .bind(board)
            .bind(epoch)
            .execute(&mut *tx)
            .await?;
        sqlx::query("insert into roaming_device_grants(board_id,user_id,root_key,chain_json,epoch) values($1,$2,$3,$4,$5)").bind(board).bind(remote.user.id).bind(&root).bind(serde_json::to_value(chain).map_err(invalid)?).bind(epoch).execute(&mut *tx).await?;
        sqlx::query("insert into roaming_board_authorizations(id,workspace_id,board_id,user_id,author_public_key,role,capability_epoch) values($1,$2,$3,$4,$5,'owner',$6)").bind(Uuid::now_v7()).bind(workspace).bind(board).bind(remote.user.id).bind(&root).bind(epoch).execute(&mut *tx).await?;
    }
    for root in &verified_roots {
        sqlx::query("insert into trusted_device_peers(user_id,public_key) values($1,$2) on conflict do nothing")
            .bind(remote.user.id).bind(root).execute(&mut *tx).await?;
    }
    sqlx::query("insert into trusted_device_peers(user_id,public_key) values($1,$2) on conflict do nothing").bind(remote.user.id).bind(&sender).execute(&mut *tx).await?;
    sqlx::query("update device_link_challenges set consumed_at=now() where id=$1")
        .bind(id)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    let user = repo::find_active_user_by_id(&state.db, remote.user.id)
        .await?
        .ok_or_else(AppError::internal)?;
    let session = service::create_authenticated_session(&state, &user, &headers).await?;
    super::handler::response_with_cookies(
        StatusCode::CREATED,
        session.payload,
        &[session.refresh_cookie, session.device_cookie],
    )
}
pub async fn lan_pending_request(State(state):State<AppState>)->AppResult<Json<ApiEnvelope<Value>>>{
    let row=sqlx::query_scalar::<_,Value>("select request_json from device_link_challenges where consumed_at is null and expires_at>$1 order by created_at desc limit 1")
      .bind(protocol::now() as i64).fetch_optional(&state.db).await?;
    Ok(ok(json!({"request":row})))
}
