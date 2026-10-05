pub mod dto;
pub mod handler;
pub mod repo;
pub mod service;

use axum::{routing::get, Router};

use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/boards/{boardId}/activity",
            get(handler::list_board_activity),
        )
        .route(
            "/boards/{boardId}/productivity",
            get(handler::get_board_productivity),
        )
        .route("/cards/{cardId}/activity", get(handler::list_card_activity))
}
