pub mod dto;
pub mod handler;
pub mod repo;
pub mod service;

use axum::{
    routing::{get, put},
    Router,
};

use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/me/appearance", get(handler::get_my_preferences))
        .route("/me/appearance", put(handler::upsert_my_preferences))
        .route(
            "/boards/{boardId}/appearance",
            get(handler::get_board_appearance),
        )
        .route(
            "/boards/{boardId}/appearance",
            put(handler::upsert_board_appearance),
        )
}
