use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use uuid::Uuid;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::{
    dto::{CreateCommentRequest, ListCommentsQuery, UpdateCommentRequest},
    service,
};

pub async fn list_comments(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
    Query(query): Query<ListCommentsQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let comments = service::list_comments(&state, actor, card_id, query).await?;
    Ok(ok(comments))
}

pub async fn create_comment(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
    Json(payload): Json<CreateCommentRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let comment = service::create_comment(&state, actor, card_id, payload).await?;
    Ok((StatusCode::CREATED, ok(comment)))
}

pub async fn update_comment(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(comment_id): Path<Uuid>,
    Json(payload): Json<UpdateCommentRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let comment = service::update_comment(&state, actor, comment_id, payload).await?;
    Ok(ok(comment))
}

pub async fn delete_comment(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(comment_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let comment = service::delete_comment(&state, actor, comment_id).await?;
    Ok(ok(comment))
}
