use axum::Json;
use serde::Serialize;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ApiEnvelope<T> {
    pub data: T,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HealthPayload {
    pub status: &'static str,
    pub service: String,
    pub version: &'static str,
    pub env: String,
}

pub fn ok<T: Serialize>(data: T) -> Json<ApiEnvelope<T>> {
    Json(ApiEnvelope { data })
}
