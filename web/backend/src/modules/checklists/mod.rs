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
        .route("/cards/{cardId}/checklists", get(handler::list_checklists))
        .route(
            "/cards/{cardId}/checklists",
            post(handler::create_checklist),
        )
        .route(
            "/checklists/{checklistId}",
            patch(handler::update_checklist),
        )
        .route(
            "/checklists/{checklistId}",
            delete(handler::delete_checklist),
        )
        .route(
            "/checklists/{checklistId}/items",
            post(handler::create_item),
        )
        .route("/checklist-items/{itemId}", patch(handler::update_item))
        .route("/checklist-items/{itemId}", delete(handler::delete_item))
}
