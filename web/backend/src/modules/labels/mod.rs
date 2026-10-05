pub mod dto;
pub mod handler;
pub mod repo;
pub mod service;

use axum::{
    routing::{delete, get, patch, post, put},
    Router,
};

use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/boards/{boardId}/labels", get(handler::list_labels))
        .route("/boards/{boardId}/labels", post(handler::create_label))
        .route("/labels/{labelId}", patch(handler::update_label))
        .route("/labels/{labelId}", delete(handler::delete_label))
        .route("/cards/{cardId}/labels", put(handler::replace_card_labels))
}
