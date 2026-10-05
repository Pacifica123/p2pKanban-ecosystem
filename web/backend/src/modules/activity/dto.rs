use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ListActivityQuery {
    pub limit: Option<i64>,
    pub cursor: Option<String>,
    pub kinds: Option<Vec<String>>,
    pub actor_user_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BoardProductivityQuery {
    pub days: Option<i64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProductivityDayResponse {
    pub date: String,
    pub action_count: i64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BoardProductivityResponse {
    pub days: Vec<ProductivityDayResponse>,
    pub total_actions: i64,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ActivityActorResponse {
    pub user_id: Option<String>,
    pub display_name: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ActivityEntryResponse {
    pub id: String,
    pub created_at: String,
    pub kind: String,
    pub workspace_id: String,
    pub board_id: String,
    pub card_id: Option<String>,
    pub entity_type: String,
    pub entity_id: String,
    pub actor: ActivityActorResponse,
    pub field_mask: Vec<String>,
    pub payload: Value,
    pub request_id: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ActivityListResponse {
    pub items: Vec<ActivityEntryResponse>,
    pub next_cursor: Option<String>,
}
