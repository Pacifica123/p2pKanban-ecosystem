use uuid::Uuid;

use crate::{error::AppResult, state::AppState};

use super::dto::{AuditLogListResponse, ListAuditLogQuery};

pub async fn list_workspace_audit_log(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    query: ListAuditLogQuery,
) -> AppResult<AuditLogListResponse> {
    super::repo::list_workspace_audit_log(&state.db, actor_user_id, workspace_id, query).await
}
