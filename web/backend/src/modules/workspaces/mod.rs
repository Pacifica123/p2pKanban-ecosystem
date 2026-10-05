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
        .route("/workspaces", get(handler::list_workspaces))
        .route("/workspaces", post(handler::create_workspace))
        .route("/workspaces/{workspaceId}", get(handler::get_workspace))
        .route(
            "/workspaces/{workspaceId}",
            patch(handler::update_workspace),
        )
        .route(
            "/workspaces/{workspaceId}",
            delete(handler::delete_workspace),
        )
        .route(
            "/workspaces/{workspaceId}/archive",
            post(handler::archive_workspace),
        )
        .route(
            "/workspaces/{workspaceId}/members",
            get(handler::list_members),
        )
        .route(
            "/workspaces/{workspaceId}/members",
            post(handler::add_member),
        )
        .route(
            "/workspaces/{workspaceId}/members/{memberId}",
            patch(handler::update_member),
        )
        .route(
            "/workspaces/{workspaceId}/members/{memberId}",
            delete(handler::remove_member),
        )
        .route(
            "/workspaces/{workspaceId}/invitations",
            get(handler::list_invitations),
        )
        .route(
            "/workspaces/{workspaceId}/invitations",
            post(handler::create_invitation),
        )
        .route(
            "/workspaces/{workspaceId}/invitations/{invitationId}",
            delete(handler::revoke_invitation),
        )
        .route("/invitations/{token}", get(handler::preview_invitation))
        .route(
            "/invitations/{token}/accept",
            post(handler::accept_invitation),
        )
}
