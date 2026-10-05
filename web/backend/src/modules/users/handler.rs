use axum::{
    extract::{Path, State},
    http::HeaderMap,
    response::IntoResponse,
};
use uuid::Uuid;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::service;

pub async fn get_current_user(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let me = service::get_current_user(&state, actor).await?;
    Ok(ok(me))
}

pub async fn list_devices(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let devices = service::list_devices(&state, actor).await?;
    Ok(ok(devices))
}

pub async fn revoke_device(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(device_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    service::revoke_device(&state, actor, device_id).await?;
    Ok(ok(
        serde_json::json!({"revoked": true, "deviceId": device_id}),
    ))
}
