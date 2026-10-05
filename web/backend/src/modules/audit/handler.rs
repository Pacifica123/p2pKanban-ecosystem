use axum::{
    extract::{Path, Query, State},
    http::HeaderMap,
    response::IntoResponse,
};
use uuid::Uuid;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::{dto::ListAuditLogQuery, service};

pub async fn list_workspace_audit_log(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
    Query(query): Query<ListAuditLogQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let items = service::list_workspace_audit_log(&state, actor, workspace_id, query).await?;
    Ok(ok(items))
}
