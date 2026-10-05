use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ChecklistItemResponse {
    pub id: String,
    pub checklist_id: String,
    pub title: String,
    pub is_done: bool,
    pub position: f64,
    pub completed_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ChecklistResponse {
    pub id: String,
    pub card_id: String,
    pub title: String,
    pub position: f64,
    pub items: Vec<ChecklistItemResponse>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChecklistListResponse {
    pub items: Vec<ChecklistResponse>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateChecklistRequest {
    pub title: String,
    pub position: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateChecklistRequest {
    pub title: Option<String>,
    pub position: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateChecklistItemRequest {
    pub title: String,
    pub position: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateChecklistItemRequest {
    pub title: Option<String>,
    pub position: Option<f64>,
    pub is_done: Option<bool>,
}
