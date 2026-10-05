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
    dto::{CreateLabelRequest, ReplaceCardLabelsRequest, UpdateLabelRequest},
    service,
};

pub async fn list_labels(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let labels = service::list_labels(&state, actor, board_id).await?;
    Ok(ok(labels))
}

pub async fn create_label(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
    Json(payload): Json<CreateLabelRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let label = service::create_label(&state, actor, board_id, payload).await?;
    Ok((StatusCode::CREATED, ok(label)))
}

pub async fn update_label(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(label_id): Path<Uuid>,
    Json(payload): Json<UpdateLabelRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let label = service::update_label(&state, actor, label_id, payload).await?;
    Ok(ok(label))
}

pub async fn delete_label(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(label_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let label = service::delete_label(&state, actor, label_id).await?;
    Ok(ok(label))
}

pub async fn replace_card_labels(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
    Json(payload): Json<ReplaceCardLabelsRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::replace_card_labels(&state, actor, card_id, payload).await?;
    Ok(ok(card))
}
