use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct LabelResponse {
    pub id: String,
    pub board_id: String,
    pub name: String,
    pub color: String,
    pub description: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LabelListResponse {
    pub items: Vec<LabelResponse>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateLabelRequest {
    pub name: String,
    pub color: String,
    pub description: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateLabelRequest {
    pub name: Option<String>,
    pub color: Option<String>,
    #[serde(default)]
    pub description: Option<Option<String>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReplaceCardLabelsRequest {
    pub label_ids: Vec<Uuid>,
}
