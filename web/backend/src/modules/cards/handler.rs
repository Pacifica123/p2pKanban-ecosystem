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
    dto::{
        CreateCardRequest, DeleteCardQuery, ListCardsQuery, MoveCardRequest,
        ReorderColumnCardsRequest, UpdateCardRequest,
    },
    service,
};

pub async fn list_cards(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
    Query(query): Query<ListCardsQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let cards = service::list_cards(&state, actor, board_id, query).await?;
    Ok(ok(cards))
}

pub async fn create_card(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
    Json(payload): Json<CreateCardRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::create_card(&state, actor, board_id, payload).await?;
    Ok((StatusCode::CREATED, ok(card)))
}

pub async fn get_card(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::get_card(&state, actor, card_id).await?;
    Ok(ok(card))
}

pub async fn update_card(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
    Json(payload): Json<UpdateCardRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::update_card(&state, actor, card_id, payload).await?;
    Ok(ok(card))
}

pub async fn delete_card(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
    Query(query): Query<DeleteCardQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::delete_card(&state, actor, card_id, query).await?;
    Ok(ok(card))
}

pub async fn hide_card_locally(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::hide_card_locally(&state, actor, card_id).await?;
    Ok(ok(card))
}

pub async fn unhide_card_locally(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::unhide_card_locally(&state, actor, card_id).await?;
    Ok(ok(card))
}

pub async fn move_card(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
    Json(payload): Json<MoveCardRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::move_card(&state, actor, card_id, payload).await?;
    Ok(ok(card))
}

pub async fn reorder_column_cards(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(column_id): Path<Uuid>,
    Json(payload): Json<ReorderColumnCardsRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let cards = service::reorder_column_cards(&state, actor, column_id, payload).await?;
    Ok(ok(cards))
}

pub async fn archive_card(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::archive_card(&state, actor, card_id).await?;
    Ok(ok(card))
}

pub async fn unarchive_card(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(card_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let card = service::unarchive_card(&state, actor, card_id).await?;
    Ok(ok(card))
}
