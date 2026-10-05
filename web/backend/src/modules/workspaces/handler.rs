use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use uuid::Uuid;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::{
    dto::{
        AddWorkspaceMemberRequest, CreateWorkspaceInvitationRequest, CreateWorkspaceRequest,
        ListWorkspacesQuery, UpdateWorkspaceMemberRequest, UpdateWorkspaceRequest,
    },
    service,
};

pub async fn list_workspaces(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<ListWorkspacesQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let payload = service::list_workspaces(&state, actor, query).await?;
    Ok(ok(payload))
}

pub async fn create_workspace(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<CreateWorkspaceRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let workspace = service::create_workspace(&state, actor, payload).await?;
    Ok((StatusCode::CREATED, ok(workspace)))
}

pub async fn get_workspace(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let workspace = service::get_workspace(&state, actor, workspace_id).await?;
    Ok(ok(workspace))
}

pub async fn update_workspace(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
    Json(payload): Json<UpdateWorkspaceRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let workspace = service::update_workspace(&state, actor, workspace_id, payload).await?;
    Ok(ok(workspace))
}

pub async fn delete_workspace(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let workspace = service::delete_workspace(&state, actor, workspace_id).await?;
    Ok(ok(workspace))
}

pub async fn archive_workspace(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let workspace = service::archive_workspace(&state, actor, workspace_id).await?;
    Ok(ok(workspace))
}

pub async fn list_members(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let members = service::list_members(&state, actor, workspace_id).await?;
    Ok(ok(members))
}

pub async fn add_member(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
    Json(payload): Json<AddWorkspaceMemberRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let member = service::add_member(&state, actor, workspace_id, payload).await?;
    Ok((StatusCode::CREATED, ok(member)))
}

pub async fn update_member(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path((workspace_id, member_id)): Path<(Uuid, Uuid)>,
    Json(payload): Json<UpdateWorkspaceMemberRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let member = service::update_member(&state, actor, workspace_id, member_id, payload).await?;
    Ok(ok(member))
}

pub async fn remove_member(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path((workspace_id, member_id)): Path<(Uuid, Uuid)>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let member = service::remove_member(&state, actor, workspace_id, member_id).await?;
    Ok(ok(member))
}

pub async fn create_invitation(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
    Json(payload): Json<CreateWorkspaceInvitationRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let invitation = service::create_invitation(&state, actor, workspace_id, payload).await?;
    Ok((StatusCode::CREATED, ok(invitation)))
}

pub async fn list_invitations(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let invitations = service::list_invitations(&state, actor, workspace_id).await?;
    Ok(ok(invitations))
}

pub async fn preview_invitation(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(token): Path<String>,
) -> AppResult<impl IntoResponse> {
    let _actor = actor_user_id(&state, &headers).await?;
    let invitation = service::preview_invitation(&state, &token).await?;
    Ok(ok(invitation))
}

pub async fn accept_invitation(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(token): Path<String>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let workspace = service::accept_invitation(&state, actor, &token).await?;
    Ok(ok(workspace))
}

pub async fn revoke_invitation(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path((workspace_id, invitation_id)): Path<(Uuid, Uuid)>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let invitation = service::revoke_invitation(
        &state,
        actor,
        workspace_id,
        invitation_id,
    )
    .await?;
    Ok(ok(invitation))
}
