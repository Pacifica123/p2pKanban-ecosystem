use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

pub use p2p_kanban_sync_core::{ClientChangeEvent, ServerChangeEvent};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SyncStatusQuery {
    pub replica_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PullChangesQuery {
    pub replica_id: String,
    pub scope: Option<String>,
    pub workspace_id: Option<String>,
    pub last_server_order: Option<i64>,
    pub limit: Option<i64>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RegisterReplicaRequest {
    pub replica_key: String,
    pub kind: Option<String>,
    pub display_name: Option<String>,
    pub platform: Option<String>,
    pub protocol_version: Option<String>,
    pub app_version: Option<String>,
    pub metadata: Option<Value>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ReplicaResponse {
    pub id: String,
    pub replica_key: Option<String>,
    pub kind: String,
    pub status: String,
    pub user_id: Option<String>,
    pub device_id: Option<String>,
    pub display_name: Option<String>,
    pub platform: Option<String>,
    pub protocol_version: Option<String>,
    pub app_version: Option<String>,
    pub last_seen_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RegisterReplicaResponse {
    pub replica: ReplicaResponse,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReplicaListResponse {
    pub items: Vec<ReplicaResponse>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SyncStatusResponse {
    pub healthy: bool,
    pub mode: String,
    pub server_time: String,
    pub max_server_order: Option<i64>,
    pub replica: Option<ReplicaResponse>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SyncScopeRequest {
    pub scope: String,
    pub workspace_id: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SyncScopeResponse {
    pub scope: String,
    pub workspace_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PushChangesRequest {
    pub replica_id: String,
    pub workspace_id: Option<String>,
    pub access_epoch: Option<i64>,
    pub events: Vec<ClientChangeEvent>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PushEventResult {
    pub event_id: String,
    pub replica_seq: i64,
    pub status: String,
    pub server_order: Option<i64>,
    pub error: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PushChangesResponse {
    pub results: Vec<PushEventResult>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SyncCursorResponse {
    pub scope: SyncScopeResponse,
    pub replica_id: String,
    pub last_server_order: i64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PullChangesResponse {
    pub events: Vec<ServerChangeEvent>,
    pub next_cursor: SyncCursorResponse,
    pub has_more: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TransportQueueCount {
    pub transport: String,
    pub status: String,
    pub count: i64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TransportAdapterStatus {
    pub enabled: bool,
    pub mode: String,
    pub configured_endpoints: usize,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TransportStatusResponse {
    pub coordinator: TransportAdapterStatus,
    pub nostr: TransportAdapterStatus,
    pub iroh: TransportAdapterStatus,
    pub queue: Vec<TransportQueueCount>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateRoamingCapabilityRequest {
    pub board_id: Uuid,
    pub author_public_key: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RoamingCapabilityResponse {
    pub format_version: i32,
    pub protocol_version: String,
    pub workspace_id: String,
    pub board_id: String,
    pub board_tag: String,
    pub board_key: String,
    pub capability_epoch: i64,
    pub can_write: bool,
    pub writer_public_keys: Vec<String>,
    pub delegation_roots:Vec<String>,
    pub delegation_chain:Vec<serde_json::Value>,
    pub relays: Vec<String>,
    pub event_kind: u16,
    pub minimum_relay_acks: usize,
    pub provisioned_at: String,
}
