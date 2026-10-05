use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ListAuditLogQuery {
    pub limit: Option<i64>,
    pub cursor: Option<String>,
    pub action_type: Option<String>,
    pub actor_user_id: Option<String>,
    pub target_entity_type: Option<String>,
    pub target_entity_id: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct AuditLogEntryResponse {
    pub id: String,
    pub created_at: String,
    pub action_type: String,
    pub workspace_id: Option<String>,
    pub actor_user_id: Option<String>,
    pub target_entity_type: Option<String>,
    pub target_entity_id: Option<String>,
    pub request_id: Option<String>,
    pub metadata: Value,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuditLogListResponse {
    pub items: Vec<AuditLogEntryResponse>,
    pub next_cursor: Option<String>,
}
