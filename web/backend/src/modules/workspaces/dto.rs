use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ListWorkspacesQuery {
    pub limit: Option<i64>,
    pub cursor: Option<String>,
    pub archived: Option<bool>,
    pub q: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateWorkspaceRequest {
    pub name: String,
    pub slug: Option<String>,
    pub description: Option<String>,
    pub visibility: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateWorkspaceRequest {
    pub name: Option<String>,
    #[serde(default)]
    pub slug: Option<Option<String>>,
    #[serde(default)]
    pub description: Option<Option<String>>,
    pub visibility: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AddWorkspaceMemberRequest {
    pub user_id: String,
    pub role: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateWorkspaceMemberRequest {
    pub role: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateWorkspaceInvitationRequest {
    pub role: String,
    pub expires_in_hours: Option<i64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PageInfo {
    pub has_next_page: bool,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceListResponse {
    pub items: Vec<WorkspaceResponse>,
    pub page_info: PageInfo,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceMembersListResponse {
    pub items: Vec<WorkspaceMemberResponse>,
    pub page_info: PageInfo,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceInvitationsListResponse {
    pub items: Vec<WorkspaceInvitationResponse>,
    pub page_info: PageInfo,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceResponse {
    pub id: String,
    pub name: String,
    pub slug: Option<String>,
    pub description: Option<String>,
    pub visibility: String,
    pub owner_user_id: String,
    pub member_count: i64,
    pub current_user_role: Option<String>,
    pub access_epoch: i64,
    pub is_archived: bool,
    pub created_at: String,
    pub updated_at: String,
    pub archived_at: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceWithMembersResponse {
    #[serde(flatten)]
    pub workspace: WorkspaceResponse,
    pub members: Vec<WorkspaceMemberResponse>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceMemberResponse {
    pub id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub display_name: String,
    pub email: String,
    pub role: String,
    pub status: String,
    pub invited_by_user_id: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    pub removed_at: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceInvitationResponse {
    pub id: String,
    pub workspace_id: String,
    pub role: String,
    pub status: String,
    pub created_by_user_id: String,
    pub expires_at: String,
    pub created_at: String,
    pub revoked_at: Option<String>,
    pub accepted_at: Option<String>,
    pub accepted_by_user_id: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CreatedWorkspaceInvitationResponse {
    pub invitation: WorkspaceInvitationResponse,
    pub token: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceInvitationPreviewResponse {
    pub workspace_id: String,
    pub workspace_name: String,
    pub role: String,
    pub status: String,
    pub expires_at: String,
}
