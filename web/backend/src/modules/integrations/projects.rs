//! Project bindings and explicit evidence ingestion, never process execution.
use crate::{
    error::{AppError, AppResult},
    http::response::{ok, ApiEnvelope},
    modules::common::{
        actor_user_id, board_workspace_id, require_workspace_access, require_workspace_owner,
        require_workspace_write,
    },
    state::AppState,
};
use axum::{
    extract::{Path, Query, State},
    http::HeaderMap,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::Row;
use uuid::Uuid;
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Scope {
    board_id: Uuid,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NewProject {
    board_id: Uuid,
    name: String,
    locator: String,
}
fn project_json(r: &sqlx::postgres::PgRow) -> AppResult<Value> {
    Ok(
        json!({"schemaVersion":1,"projectId":r.try_get::<Uuid,_>("id")?,"name":r.try_get::<String,_>("name")?,"workspaceId":r.try_get::<Uuid,_>("workspace_id")?,"componentId":r.try_get::<Uuid,_>("component_id")?,"resource":r.try_get::<Value,_>("resource_json")?,"defaultWorkScope":{"kind":"board","id":r.try_get::<Uuid,_>("board_id")?}}),
    )
}
pub async fn list(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(scope): Query<Scope>,
) -> AppResult<Json<ApiEnvelope<Value>>> {
    let u = actor_user_id(&state, &headers).await?;
    let w = board_workspace_id(&state.db, scope.board_id).await?;
    require_workspace_access(&state.db, w, u).await?;
    let rows =
        sqlx::query("select * from integration_projects where board_id=$1 order by created_at,id")
            .bind(scope.board_id)
            .fetch_all(&state.db)
            .await?;
    Ok(ok(
        json!({"items":rows.iter().map(project_json).collect::<AppResult<Vec<_>>>()?}),
    ))
}
pub async fn create(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(i): Json<NewProject>,
) -> AppResult<Json<ApiEnvelope<Value>>> {
    let u = actor_user_id(&state, &headers).await?;
    let w = board_workspace_id(&state.db, i.board_id).await?;
    require_workspace_owner(&state.db, w, u).await?;
    if i.name.trim().is_empty()
        || i.name.len() > 200
        || i.locator.trim().is_empty()
        || i.locator.len() > 500
        || i.locator.chars().any(char::is_control)
    {
        return Err(AppError::bad_request(
            "Name and local workspace label are required (200/500 byte limits)",
        ));
    }
    let row=sqlx::query("insert into integration_projects(id,workspace_id,name,component_id,board_id,resource_json,created_by) values($1,$2,$3,$4,$5,$6,$7) returning *").bind(Uuid::now_v7()).bind(w).bind(i.name.trim()).bind(Uuid::now_v7()).bind(i.board_id).bind(json!({"provider":"devctl","kind":"local_workspace","locator":i.locator.trim()})).bind(u).fetch_one(&state.db).await?;
    Ok(ok(project_json(&row)?))
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Receipt {
    schema_version: u8,
    receipt_id: Uuid,
    project_id: Uuid,
    patch_id: String,
    patch_sha256: String,
    result: String,
    commit: Option<String>,
    checks: Vec<Check>,
    work_items: Vec<WorkItem>,
    applied_at: String,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Check {
    name: String,
    status: String,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkItem {
    r#ref: String,
    transition: Option<String>,
}
fn validate_receipt(r: &Receipt, p: Uuid) -> AppResult<()> {
    let h = r.patch_sha256.strip_prefix("sha256:").unwrap_or("");
    let hex = |s: &str, n: usize| s.len() == n && s.bytes().all(|c| c.is_ascii_hexdigit());
    if r.schema_version != 1
        || r.project_id != p
        || !hex(h, 64)
        || r.patch_id.trim().is_empty()
        || r.patch_id.len() > 200
        || !matches!(
            r.result.as_str(),
            "applied" | "failed" | "push_failed" | "rolled_back"
        )
        || r.checks.len() > 100
        || r.work_items.len() > 100
        || r.applied_at.len() > 40
        || r.commit
            .as_ref()
            .is_some_and(|c| !hex(c, 40) && !hex(c, 64))
        || (matches!(r.result.as_str(), "applied" | "push_failed") && r.commit.is_none())
    {
        return Err(AppError::bad_request("Invalid receipt metadata"));
    }
    for c in &r.checks {
        if c.name.is_empty()
            || c.name.len() > 200
            || !matches!(c.status.as_str(), "passed" | "failed" | "skipped")
            || (r.result == "applied" && c.status == "failed")
        {
            return Err(AppError::bad_request("Invalid receipt check"));
        }
    }
    Ok(())
}
async fn validate_scope(
    state: &AppState,
    p: Uuid,
    u: Uuid,
    r: &Receipt,
    write: bool,
) -> AppResult<()> {
    validate_receipt(r, p)?;
    let (w, b) = sqlx::query_as::<_, (Uuid, Uuid)>(
        "select workspace_id,board_id from integration_projects where id=$1",
    )
    .bind(p)
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| AppError::bad_request("Unknown project"))?;
    if write {
        require_workspace_write(&state.db, w, u).await?;
    } else {
        require_workspace_access(&state.db, w, u).await?;
    }
    let valid=sqlx::query_scalar::<_,bool>("select pg_input_is_valid($1, 'timestamp with time zone') and $1::text ~ 'T.*(Z|[+-][0-9]{2}:[0-9]{2})$'").bind(&r.applied_at).fetch_one(&state.db).await?;
    if !valid {
        return Err(AppError::bad_request("Invalid ISO timestamp"));
    }
    for item in &r.work_items {
        let (kind, id) = item
            .r#ref
            .split_once(':')
            .ok_or_else(|| AppError::bad_request("Invalid work reference"))?;
        let id = Uuid::parse_str(id).map_err(|_| AppError::bad_request("Invalid work UUID"))?;
        let exists=match kind{"card"=>sqlx::query_scalar::<_,bool>("select exists(select 1 from cards where id=$1 and board_id=$2 and deleted_at is null)").bind(id).bind(b).fetch_one(&state.db).await?,"checklistItem"=>sqlx::query_scalar::<_,bool>("select exists(select 1 from checklist_items i join checklists l on l.id=i.checklist_id join cards c on c.id=l.card_id where i.id=$1 and c.board_id=$2 and c.deleted_at is null and l.deleted_at is null and i.deleted_at is null)").bind(id).bind(b).fetch_one(&state.db).await?,_=>return Err(AppError::bad_request("Unsupported work scope"))};
        if !exists {
            return Err(AppError::bad_request(
                "Work item outside bound board or deleted",
            ));
        }
        if item.transition.as_deref().is_some_and(|s| s != "complete") {
            return Err(AppError::bad_request("Unsupported transition intent"));
        }
    }
    Ok(())
}
pub async fn preview(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(p): Path<Uuid>,
    Json(r): Json<Receipt>,
) -> AppResult<Json<ApiEnvelope<Value>>> {
    let u = actor_user_id(&state, &headers).await?;
    validate_scope(&state, p, u, &r, false).await?;
    Ok(ok(
        json!({"receipt":r,"policy":"evidence_only","notice":"User-supplied evidence; no automatic task transitions."}),
    ))
}
pub async fn ingest(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(p): Path<Uuid>,
    Json(r): Json<Receipt>,
) -> AppResult<Json<ApiEnvelope<Value>>> {
    let u = actor_user_id(&state, &headers).await?;
    validate_scope(&state, p, u, &r, true).await?;
    let payload = serde_json::to_value(&r).map_err(|_| AppError::internal())?;
    let inserted=sqlx::query("insert into integration_receipts(project_id,receipt_id,payload_json,imported_by) values($1,$2,$3,$4) on conflict do nothing").bind(p).bind(r.receipt_id).bind(&payload).bind(u).execute(&state.db).await?.rows_affected()>0;
    let saved = sqlx::query_scalar::<_, Value>(
        "select payload_json from integration_receipts where project_id=$1 and receipt_id=$2",
    )
    .bind(p)
    .bind(r.receipt_id)
    .fetch_one(&state.db)
    .await?;
    if saved != payload {
        return Err(AppError::conflict(
            "Receipt ID already has different evidence",
        ));
    }
    Ok(ok(
        json!({"receipt":saved,"duplicate":!inserted,"policy":"evidence_only"}),
    ))
}
pub async fn receipts(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(p): Path<Uuid>,
) -> AppResult<Json<ApiEnvelope<Value>>> {
    let u = actor_user_id(&state, &headers).await?;
    let w =
        sqlx::query_scalar::<_, Uuid>("select workspace_id from integration_projects where id=$1")
            .bind(p)
            .fetch_optional(&state.db)
            .await?
            .ok_or_else(|| AppError::bad_request("Unknown project"))?;
    require_workspace_access(&state.db, w, u).await?;
    let rows=sqlx::query("select payload_json,imported_by,created_at::text as imported_at from integration_receipts where project_id=$1 order by created_at desc limit 100").bind(p).fetch_all(&state.db).await?;
    let items=rows.iter().map(|r|Ok(json!({"receipt":r.try_get::<Value,_>("payload_json")?,"importedBy":r.try_get::<Uuid,_>("imported_by")?,"importedAt":r.try_get::<String,_>("imported_at")?}))).collect::<AppResult<Vec<_>>>()?;
    Ok(ok(json!({"items":items})))
}
