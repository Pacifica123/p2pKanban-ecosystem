use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use serde_json::Value;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::{
    dto::{
        CreateExportJobRequest, CreateImportExecutionRequest, CreateImportJobRequest,
        CreateImportPreviewRequest, CreatePortableExportRequest,
    },
    service,
};

pub async fn list_providers(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let response = service::list_providers(&state, actor).await?;
    Ok(ok(response))
}

pub async fn get_provider_detail(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(provider_key): Path<String>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let response = service::get_provider_detail(&state, actor, &provider_key).await?;
    Ok(ok(response))
}

pub async fn create_import_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<CreateImportJobRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let response = service::create_import_job(&state, actor, payload).await?;
    Ok((StatusCode::ACCEPTED, ok(response)))
}

pub async fn create_export_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<CreateExportJobRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let response = service::create_export_job(&state, actor, payload).await?;
    Ok((StatusCode::ACCEPTED, ok(response)))
}

pub async fn get_import_export_capabilities(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let response = service::get_import_export_capabilities(&state, actor).await?;
    Ok(ok(response))
}

pub async fn create_portable_export(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<CreatePortableExportRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let response = service::create_portable_export(&state, actor, payload).await?;
    Ok((StatusCode::ACCEPTED, ok(response)))
}

pub async fn preview_import_bundle(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<CreateImportPreviewRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let response = service::preview_import_bundle(&state, actor, payload).await?;
    Ok(ok(response))
}

pub async fn create_import_execution(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<CreateImportExecutionRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let response = service::create_import_execution(&state, actor, payload).await?;
    Ok((StatusCode::ACCEPTED, ok(response)))
}

pub async fn receive_webhook(
    Path(provider_key): Path<String>,
    Json(_payload): Json<Value>,
) -> AppResult<impl IntoResponse> {
    let response = service::receive_webhook(&provider_key).await?;
    Ok((StatusCode::ACCEPTED, ok(response)))
}
