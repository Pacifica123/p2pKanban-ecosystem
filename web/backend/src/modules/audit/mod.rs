pub mod dto;
pub mod handler;
pub mod repo;
pub mod service;

use axum::{routing::get, Router};

use crate::state::AppState;

pub fn router() -> Router<AppState> {
    Router::new().route(
        "/workspaces/{workspaceId}/audit-log",
        get(handler::list_workspace_audit_log),
    )
}
