use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ListBoardsQuery {
    pub limit: Option<i64>,
    pub cursor: Option<String>,
    pub archived: Option<bool>,
    pub q: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateBoardRequest {
    pub name: String,
    pub description: Option<String>,
    pub board_type: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateBoardRequest {
    pub name: Option<String>,
    #[serde(default)]
    pub description: Option<Option<String>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateColumnRequest {
    pub name: String,
    pub description: Option<String>,
    pub position: Option<f64>,
    pub color_token: Option<String>,
    pub wip_limit: Option<i32>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateColumnRequest {
    pub name: Option<String>,
    #[serde(default)]
    pub description: Option<Option<String>>,
    pub position: Option<f64>,
    #[serde(default)]
    pub color_token: Option<Option<String>>,
    #[serde(default)]
    pub wip_limit: Option<Option<i32>>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PageInfo {
    pub has_next_page: bool,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BoardListResponse {
    pub items: Vec<BoardResponse>,
    pub page_info: PageInfo,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ColumnListResponse {
    pub items: Vec<ColumnResponse>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct BoardResponse {
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    pub description: Option<String>,
    pub board_type: String,
    pub is_archived: bool,
    pub label_ids: Vec<String>,
    pub checklist_count: i64,
    pub checklist_completed_item_count: i64,
    pub comment_count: i64,
    pub created_by_user_id: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    pub archived_at: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ColumnResponse {
    pub id: String,
    pub board_id: String,
    pub name: String,
    pub description: Option<String>,
    pub position: f64,
    pub color_token: Option<String>,
    pub wip_limit: Option<i32>,
    pub created_at: String,
    pub updated_at: String,
}
