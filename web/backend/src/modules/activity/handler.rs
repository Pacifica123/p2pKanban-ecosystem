use axum::{
    extract::{Path, Query, State},
    http::HeaderMap,
    response::IntoResponse,
};
use uuid::Uuid;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::{
    dto::{BoardProductivityQuery, ListActivityQuery},
    service,
};

pub async fn get_board_productivity(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
    Query(query): Query<BoardProductivityQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let productivity = service::get_board_productivity(&state, actor, board_id, query).await?;
    Ok(ok(productivity))
}

pub async fn list_board_activity(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
    Query(query): Query<ListActivityQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let activity = service::list_board_activity(&state, actor, board_id, query).await?;
    Ok(ok(activity))
}

pub async fn list_card_activity(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
    Query(query): Query<ListActivityQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let activity = service::list_card_activity(&state, actor, card_id, query).await?;
    Ok(ok(activity))
}
