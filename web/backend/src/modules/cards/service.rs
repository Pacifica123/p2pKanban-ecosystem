use std::collections::HashSet;

use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    state::AppState,
};

use super::dto::{
    CardListResponse, CardResponse, CreateCardRequest, DeleteCardQuery, ListCardsQuery,
    MoveCardRequest, ReorderColumnCardsRequest, UpdateCardRequest,
};

pub async fn list_cards(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
    query: ListCardsQuery,
) -> AppResult<CardListResponse> {
    super::repo::list_cards(&state.db, actor_user_id, board_id, query).await
}

pub async fn create_card(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: CreateCardRequest,
) -> AppResult<CardResponse> {
    if payload.title.trim().is_empty() {
        return Err(AppError::bad_request("Card title is required"));
    }
    if let Some(priority) = payload.priority.as_deref() {
        if !matches!(priority, "low" | "medium" | "high" | "urgent") {
            return Err(AppError::bad_request("Unsupported card priority"));
        }
    }

    super::repo::create_card(&state.db, actor_user_id, board_id, payload).await
}

pub async fn get_card(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    super::repo::get_card(&state.db, actor_user_id, card_id).await
}

pub async fn update_card(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: UpdateCardRequest,
) -> AppResult<CardResponse> {
    if let Some(title) = &payload.title {
        if title.trim().is_empty() {
            return Err(AppError::bad_request("Card title cannot be empty"));
        }
    }
    if let Some(priority) = payload.priority.as_ref().and_then(Option::as_deref) {
        if !matches!(priority, "low" | "medium" | "high" | "urgent") {
            return Err(AppError::bad_request("Unsupported card priority"));
        }
    }

    super::repo::update_card(&state.db, actor_user_id, card_id, payload).await
}

pub async fn delete_card(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
    query: DeleteCardQuery,
) -> AppResult<CardResponse> {
    if !matches!(query.scope.as_deref(), None | Some("all_devices")) {
        return Err(AppError::bad_request(
            "Use POST /cards/{cardId}/hide-local for node-local hiding",
        ));
    }
    super::repo::delete_card(&state.db, actor_user_id, card_id).await
}

pub async fn hide_card_locally(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    super::repo::hide_card_locally(&state.db, actor_user_id, card_id).await
}

pub async fn unhide_card_locally(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    super::repo::unhide_card_locally(&state.db, actor_user_id, card_id).await
}

pub async fn move_card(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: MoveCardRequest,
) -> AppResult<CardResponse> {
    super::repo::move_card(&state.db, actor_user_id, card_id, payload).await
}

pub async fn reorder_column_cards(
    state: &AppState,
    actor_user_id: Uuid,
    column_id: Uuid,
    payload: ReorderColumnCardsRequest,
) -> AppResult<CardListResponse> {
    if payload.items.is_empty() {
        return Err(AppError::bad_request("At least one card item is required"));
    }

    let mut seen = HashSet::with_capacity(payload.items.len());
    for item in &payload.items {
        if !seen.insert(item.card_id) {
            return Err(AppError::bad_request("Duplicate cardId in reorder payload"));
        }
        if !item.position.is_finite() {
            return Err(AppError::bad_request(
                "Card position must be a finite number",
            ));
        }
    }

    super::repo::reorder_column_cards(&state.db, actor_user_id, column_id, payload).await
}

pub async fn archive_card(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    super::repo::archive_card(&state.db, actor_user_id, card_id).await
}

pub async fn unarchive_card(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    super::repo::unarchive_card(&state.db, actor_user_id, card_id).await
}
