use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use uuid::Uuid;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::{
    dto::{
        CreateChecklistItemRequest, CreateChecklistRequest, UpdateChecklistItemRequest,
        UpdateChecklistRequest,
    },
    service,
};

pub async fn list_checklists(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let checklists = service::list_checklists(&state, actor, card_id).await?;
    Ok(ok(checklists))
}

pub async fn create_checklist(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
    Json(payload): Json<CreateChecklistRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let checklist = service::create_checklist(&state, actor, card_id, payload).await?;
    Ok((StatusCode::CREATED, ok(checklist)))
}

pub async fn update_checklist(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(checklist_id): Path<Uuid>,
    Json(payload): Json<UpdateChecklistRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let checklist = service::update_checklist(&state, actor, checklist_id, payload).await?;
    Ok(ok(checklist))
}

pub async fn delete_checklist(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(checklist_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let checklist = service::delete_checklist(&state, actor, checklist_id).await?;
    Ok(ok(checklist))
}

pub async fn create_item(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(checklist_id): Path<Uuid>,
    Json(payload): Json<CreateChecklistItemRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let item = service::create_item(&state, actor, checklist_id, payload).await?;
    Ok((StatusCode::CREATED, ok(item)))
}

pub async fn update_item(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(item_id): Path<Uuid>,
    Json(payload): Json<UpdateChecklistItemRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let item = service::update_item(&state, actor, item_id, payload).await?;
    Ok(ok(item))
}

pub async fn delete_item(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(item_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let item = service::delete_item(&state, actor, item_id).await?;
    Ok(ok(item))
}
