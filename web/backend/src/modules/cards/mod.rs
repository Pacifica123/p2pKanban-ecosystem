pub mod dto;
pub mod handler;
pub mod repo;
pub mod service;

use axum::{
    routing::{delete, get, patch, post},
    Router,
};

use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/boards/{boardId}/cards", get(handler::list_cards))
        .route("/boards/{boardId}/cards", post(handler::create_card))
        .route("/cards/{cardId}", get(handler::get_card))
        .route("/cards/{cardId}", patch(handler::update_card))
        .route("/cards/{cardId}", delete(handler::delete_card))
        .route(
            "/cards/{cardId}/hide-local",
            post(handler::hide_card_locally),
        )
        .route(
            "/cards/{cardId}/hide-local",
            delete(handler::unhide_card_locally),
        )
        .route("/cards/{cardId}/move", post(handler::move_card))
        .route(
            "/columns/{columnId}/cards/reorder",
            post(handler::reorder_column_cards),
        )
        .route("/cards/{cardId}/archive", post(handler::archive_card))
        .route("/cards/{cardId}/unarchive", post(handler::unarchive_card))
}
