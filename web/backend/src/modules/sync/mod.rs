pub mod dto;
pub mod handler;
pub mod repo;
pub mod service;

use axum::{
    routing::{get, post},
    Router,
};

use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/sync/status", get(handler::get_status))
        .route(
            "/sync/transports/status",
            get(handler::get_transport_status),
        )
        .route("/sync/replicas", get(handler::list_replicas))
        .route("/sync/replicas", post(handler::register_replica))
        .route("/sync/push", post(handler::push_changes))
        .route("/sync/pull", get(handler::pull_changes))
        .route(
            "/sync/roaming/capability",
            post(handler::create_roaming_capability),
        )
}
