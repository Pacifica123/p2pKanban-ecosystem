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
    /// Image fingerprint (`P2PKANBAN_BUILD`), `null` when unknown.
    pub build: Option<String>,
    /// Monorepo commit (`P2PKANBAN_SOURCE_REVISION`), `null` when unknown.
    pub commit: Option<String>,
}

pub fn ok<T: Serialize>(data: T) -> Json<ApiEnvelope<T>> {
    Json(ApiEnvelope { data })
}
