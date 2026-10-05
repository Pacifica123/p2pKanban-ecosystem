use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ListCommentsQuery {
    pub limit: Option<i64>,
    pub cursor: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PageInfo {
    pub has_next_page: bool,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct CommentResponse {
    pub id: String,
    pub card_id: String,
    pub author_user_id: Option<String>,
    pub body: String,
    pub created_at: String,
    pub updated_at: String,
    pub edited_at: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommentListResponse {
    pub items: Vec<CommentResponse>,
    pub page_info: PageInfo,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateCommentRequest {
    pub body: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateCommentRequest {
    pub body: Option<String>,
}
