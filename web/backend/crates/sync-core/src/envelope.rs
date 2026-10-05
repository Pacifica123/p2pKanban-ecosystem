use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const SYNC_PROTOCOL_VERSION: &str = "p2p-kanban-sync/1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ClientChangeEvent {
    pub event_id: String,
    pub replica_id: String,
    pub replica_seq: i64,
    pub entity_type: String,
    pub entity_id: String,
    pub operation: String,
    pub field_mask: Option<Vec<String>>,
    pub logical_clock: i64,
    pub base_server_order: Option<i64>,
    pub occurred_at: Option<String>,
    #[serde(default)]
    pub payload: Value,
    #[serde(default)]
    pub metadata: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ServerChangeEvent {
    pub event_id: String,
    pub replica_id: String,
    pub replica_seq: i64,
    pub entity_type: String,
    pub entity_id: String,
    pub operation: String,
    pub field_mask: Vec<String>,
    pub logical_clock: i64,
    pub base_server_order: Option<i64>,
    pub payload: Value,
    pub metadata: Value,
    pub server_order: i64,
    pub accepted_at: String,
    pub actor_user_id: Option<String>,
    pub actor_device_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SyncEnvelope {
    pub protocol_version: String,
    pub envelope_id: String,
    pub workspace_id: String,
    pub event: ServerChangeEvent,
    #[serde(default)]
    pub parents: Vec<String>,
    pub emitted_at: String,
}

impl SyncEnvelope {
    pub fn new(workspace_id: impl Into<String>, event: ServerChangeEvent) -> Self {
        Self {
            protocol_version: SYNC_PROTOCOL_VERSION.to_string(),
            envelope_id: event.event_id.clone(),
            workspace_id: workspace_id.into(),
            event,
            parents: Vec::new(),
            emitted_at: String::new(),
        }
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(self)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SignedSyncEnvelope {
    pub envelope: SyncEnvelope,
    pub signer_key_id: String,
    pub algorithm: String,
    pub signature: String,
    pub digest: String,
}
