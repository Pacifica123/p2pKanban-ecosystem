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
        .route(
            "/workspaces/{workspaceId}/boards",
            get(handler::list_boards),
        )
        .route(
            "/workspaces/{workspaceId}/boards",
            post(handler::create_board),
        )
        .route("/boards/{boardId}", get(handler::get_board))
        .route("/boards/{boardId}", patch(handler::update_board))
        .route("/boards/{boardId}", delete(handler::delete_board))
        .route("/boards/{boardId}/archive", post(handler::archive_board))
        .route("/boards/{boardId}/columns", get(handler::list_columns))
        .route("/boards/{boardId}/columns", post(handler::create_column))
        .route("/columns/{columnId}", patch(handler::update_column))
        .route("/columns/{columnId}", delete(handler::delete_column))
        .route(
            "/boards/{boardId}/columns/{columnId}",
            patch(handler::update_column_scoped),
        )
        .route(
            "/boards/{boardId}/columns/{columnId}",
            delete(handler::delete_column_scoped),
        )
}
