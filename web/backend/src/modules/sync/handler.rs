use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};

use crate::{error::AppResult, http::response::ok, modules::common::auth_context, state::AppState};

use super::{
    dto::{
        CreateRoamingCapabilityRequest, PullChangesQuery, PushChangesRequest,
        RegisterReplicaRequest, SyncStatusQuery,
    },
    service,
};

pub async fn get_status(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<SyncStatusQuery>,
) -> AppResult<impl IntoResponse> {
    let auth = auth_context(&state, &headers).await?;
    let status = service::get_status(&state, auth, query).await?;
    Ok(ok(status))
}

pub async fn get_transport_status(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<impl IntoResponse> {
    let auth = auth_context(&state, &headers).await?;
    let status = service::get_transport_status(&state, auth).await?;
    Ok(ok(status))
}

pub async fn list_replicas(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<impl IntoResponse> {
    let auth = auth_context(&state, &headers).await?;
    let replicas = service::list_replicas(&state, auth).await?;
    Ok(ok(replicas))
}

pub async fn register_replica(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<RegisterReplicaRequest>,
) -> AppResult<impl IntoResponse> {
    let auth = auth_context(&state, &headers).await?;
    let replica = service::register_replica(&state, auth, payload).await?;
    Ok((StatusCode::CREATED, ok(replica)))
}

pub async fn push_changes(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<PushChangesRequest>,
) -> AppResult<impl IntoResponse> {
    let auth = auth_context(&state, &headers).await?;
    let result = service::push_changes(&state, auth, payload).await?;
    Ok(ok(result))
}

pub async fn pull_changes(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<PullChangesQuery>,
) -> AppResult<impl IntoResponse> {
    let auth = auth_context(&state, &headers).await?;
    let result = service::pull_changes(&state, auth, query).await?;
    Ok(ok(result))
}

pub async fn create_roaming_capability(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<CreateRoamingCapabilityRequest>,
) -> AppResult<impl IntoResponse> {
    let auth = auth_context(&state, &headers).await?;
    let capability = service::create_roaming_capability(&state, auth, payload).await?;
    Ok(ok(capability))
}
