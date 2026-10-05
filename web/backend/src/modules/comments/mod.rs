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
        .route("/cards/{cardId}/comments", get(handler::list_comments))
        .route("/cards/{cardId}/comments", post(handler::create_comment))
        .route("/comments/{commentId}", patch(handler::update_comment))
        .route("/comments/{commentId}", delete(handler::delete_comment))
}
