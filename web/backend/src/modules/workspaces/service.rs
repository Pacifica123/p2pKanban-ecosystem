use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    state::AppState,
};

use super::dto::{
    AddWorkspaceMemberRequest, CreateWorkspaceInvitationRequest, CreateWorkspaceRequest,
    CreatedWorkspaceInvitationResponse, ListWorkspacesQuery, UpdateWorkspaceMemberRequest,
    UpdateWorkspaceRequest, WorkspaceInvitationPreviewResponse, WorkspaceInvitationResponse,
    WorkspaceInvitationsListResponse, WorkspaceListResponse, WorkspaceMemberResponse,
    WorkspaceMembersListResponse, WorkspaceResponse, WorkspaceWithMembersResponse,
};

fn valid_collaborator_role(role: &str) -> bool {
    matches!(role, "member" | "guest")
}

fn invitation_token_hash(token: &str) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(token.as_bytes()))
}

fn create_invitation_token() -> String {
    let mut bytes = [0u8; 32];
    OsRng.fill_bytes(&mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}

fn normalized_invitation_token(value: &str) -> AppResult<String> {
    let token = value.trim();
    if token.len() < 32 || token.len() > 160 {
        return Err(AppError::bad_request("Invitation token is invalid"));
    }
    Ok(token.to_string())
}

pub async fn list_workspaces(
    state: &AppState,
    actor_user_id: Uuid,
    query: ListWorkspacesQuery,
) -> AppResult<WorkspaceListResponse> {
    super::repo::list_workspaces(&state.db, actor_user_id, query).await
}

pub async fn create_workspace(
    state: &AppState,
    actor_user_id: Uuid,
    payload: CreateWorkspaceRequest,
) -> AppResult<WorkspaceResponse> {
    let name = payload.name.trim();
    if name.is_empty() {
        return Err(AppError::bad_request("Workspace name is required"));
    }

    let visibility = payload.visibility.as_deref().unwrap_or("private");
    if !matches!(visibility, "private" | "shared") {
        return Err(AppError::bad_request(
            "Workspace visibility must be private or shared",
        ));
    }

    super::repo::create_workspace(&state.db, actor_user_id, payload).await
}

pub async fn get_workspace(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceWithMembersResponse> {
    super::repo::get_workspace(&state.db, actor_user_id, workspace_id).await
}

pub async fn update_workspace(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    payload: UpdateWorkspaceRequest,
) -> AppResult<WorkspaceResponse> {
    if let Some(name) = &payload.name {
        if name.trim().is_empty() {
            return Err(AppError::bad_request("Workspace name cannot be empty"));
        }
    }

    if let Some(visibility) = &payload.visibility {
        if !matches!(visibility.as_str(), "private" | "shared") {
            return Err(AppError::bad_request(
                "Workspace visibility must be private or shared",
            ));
        }
    }

    super::repo::update_workspace(&state.db, actor_user_id, workspace_id, payload).await
}

pub async fn delete_workspace(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceResponse> {
    super::repo::delete_workspace(&state.db, actor_user_id, workspace_id).await
}

pub async fn archive_workspace(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceResponse> {
    super::repo::archive_workspace(&state.db, actor_user_id, workspace_id).await
}

pub async fn list_members(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceMembersListResponse> {
    super::repo::list_members(&state.db, actor_user_id, workspace_id).await
}

pub async fn add_member(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    payload: AddWorkspaceMemberRequest,
) -> AppResult<WorkspaceMemberResponse> {
    let role = payload.role.as_str();
    if !valid_collaborator_role(role) {
        return Err(AppError::bad_request(
            "Workspace member role must be member or guest",
        ));
    }

    super::repo::add_member(&state.db, actor_user_id, workspace_id, payload).await
}

pub async fn update_member(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    member_id: Uuid,
    payload: UpdateWorkspaceMemberRequest,
) -> AppResult<WorkspaceMemberResponse> {
    if let Some(role) = &payload.role {
        if !valid_collaborator_role(role) {
            return Err(AppError::bad_request(
                "Workspace member role must be member or guest",
            ));
        }
    }

    super::repo::update_member(&state.db, actor_user_id, workspace_id, member_id, payload).await
}

pub async fn remove_member(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    member_id: Uuid,
) -> AppResult<WorkspaceMemberResponse> {
    super::repo::remove_member(&state.db, actor_user_id, workspace_id, member_id).await
}

pub async fn create_invitation(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    payload: CreateWorkspaceInvitationRequest,
) -> AppResult<CreatedWorkspaceInvitationResponse> {
    if !valid_collaborator_role(&payload.role) {
        return Err(AppError::bad_request(
            "Invitation role must be member or guest",
        ));
    }
    let expires_in_hours = payload.expires_in_hours.unwrap_or(24);
    if !(1..=24 * 30).contains(&expires_in_hours) {
        return Err(AppError::bad_request(
            "Invitation lifetime must be between 1 and 720 hours",
        ));
    }
    let token = create_invitation_token();
    super::repo::create_invitation(
        &state.db,
        actor_user_id,
        workspace_id,
        payload.role,
        expires_in_hours,
        invitation_token_hash(&token),
        token,
    )
    .await
}

pub async fn list_invitations(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceInvitationsListResponse> {
    super::repo::list_invitations(&state.db, actor_user_id, workspace_id).await
}

pub async fn preview_invitation(
    state: &AppState,
    token: &str,
) -> AppResult<WorkspaceInvitationPreviewResponse> {
    let token = normalized_invitation_token(token)?;
    super::repo::preview_invitation(&state.db, &invitation_token_hash(&token)).await
}

pub async fn accept_invitation(
    state: &AppState,
    actor_user_id: Uuid,
    token: &str,
) -> AppResult<WorkspaceResponse> {
    let token = normalized_invitation_token(token)?;
    super::repo::accept_invitation(
        &state.db,
        actor_user_id,
        &invitation_token_hash(&token),
    )
    .await
}

pub async fn revoke_invitation(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    invitation_id: Uuid,
) -> AppResult<WorkspaceInvitationResponse> {
    super::repo::revoke_invitation(
        &state.db,
        actor_user_id,
        workspace_id,
        invitation_id,
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::{invitation_token_hash, normalized_invitation_token};

    #[test]
    fn invitation_hash_is_deterministic_without_storing_raw_token() {
        let token = "hPCjB_Fl6u03bMQ7hMf8uaQqK3n4nVGxbJuuw-hCF6E";
        assert_eq!(invitation_token_hash(token), invitation_token_hash(token));
        assert_ne!(invitation_token_hash(token), token);
    }

    #[test]
    fn short_invitation_tokens_are_rejected() {
        assert!(normalized_invitation_token("short").is_err());
    }
}
