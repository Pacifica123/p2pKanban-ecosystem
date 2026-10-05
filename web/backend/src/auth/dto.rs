use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::modules::integrations::dto::PortableBundle;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SignUpRequest {
    pub email: String,
    pub password: String,
    pub display_name: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SignInRequest {
    pub email: String,
    pub password: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkExportRequest {
    pub email: String,
    pub password: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkImportRequest {
    pub source_url: String,
    pub email: String,
    pub password: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkUserSnapshot {
    pub id: Uuid,
    pub email: String,
    pub display_name: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkUserAppearanceSnapshot {
    pub app_theme: String,
    pub density: String,
    pub reduce_motion: bool,
    pub checklist_item_submit_mode: String,
    pub card_details_mode: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkWorkspaceSnapshot {
    pub membership_role: String,
    pub bundle: PortableBundle,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkBoardCapabilitySnapshot {
    pub board_id: Uuid,
    pub board_tag: String,
    pub board_key: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkCardTombstoneSnapshot {
    pub workspace_id: Uuid,
    pub board_id: Uuid,
    pub card_id: Uuid,
    pub deleted_at: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkTransportSnapshot {
    pub relays: Vec<String>,
    pub event_kind: u16,
    pub minimum_relay_acks: usize,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct NodeLinkExportResponse {
    pub format: String,
    pub format_version: i32,
    pub user: NodeLinkUserSnapshot,
    pub user_appearance: Option<NodeLinkUserAppearanceSnapshot>,
    pub workspaces: Vec<NodeLinkWorkspaceSnapshot>,
    pub board_capabilities: Vec<NodeLinkBoardCapabilitySnapshot>,
    #[serde(default)]
    pub card_tombstones: Vec<NodeLinkCardTombstoneSnapshot>,
    pub transport: NodeLinkTransportSnapshot,
    pub exported_at: String,
    pub warnings: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRefreshRequest {
    pub refresh_token: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeSignOutRequest {
    pub refresh_token: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DevBootstrapUserRequest {
    pub user_id: Option<String>,
    pub email: Option<String>,
    pub display_name: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DevBootstrapUserResponse {
    pub id: String,
    pub email: String,
    pub display_name: String,
    pub mode: &'static str,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct SessionUserResponse {
    pub id: String,
    pub email: String,
    pub display_name: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthSuccessResponse {
    pub authenticated: bool,
    pub mode: &'static str,
    pub access_token: String,
    pub access_token_expires_at: String,
    pub session_id: String,
    pub device_id: String,
    pub user: SessionUserResponse,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeAuthSuccessResponse {
    pub authenticated: bool,
    pub mode: &'static str,
    pub access_token: String,
    pub access_token_expires_at: String,
    pub refresh_token: String,
    pub session_id: String,
    pub device_id: String,
    pub user: SessionUserResponse,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionResponse {
    pub authenticated: bool,
    pub mode: &'static str,
    pub session_id: Option<String>,
    pub device_id: Option<String>,
    pub user: Option<SessionUserResponse>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SignOutResponse {
    pub signed_out: bool,
    pub mode: &'static str,
}
