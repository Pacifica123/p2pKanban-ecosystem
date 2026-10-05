use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct IntegrationProviderSummary {
    pub key: String,
    pub display_name: String,
    pub provider_type: String,
    pub status: String,
    pub auth_mode: String,
    pub supports_import: bool,
    pub supports_export: bool,
    pub supports_inbound_webhooks: bool,
    pub supports_outbound_webhooks: bool,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct IntegrationTouchpoint {
    pub key: String,
    pub direction: String,
    pub payload_format: String,
    pub description: String,
    pub status: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct DomainEventSubscription {
    pub event_type: String,
    pub delivery_mode: String,
    pub purpose: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WebhookContract {
    pub mode: String,
    pub signature_scheme: String,
    pub event_types: Vec<String>,
    pub description: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct IntegrationProviderDetailResponse {
    pub provider: IntegrationProviderSummary,
    pub import_touchpoints: Vec<IntegrationTouchpoint>,
    pub export_touchpoints: Vec<IntegrationTouchpoint>,
    pub domain_event_subscriptions: Vec<DomainEventSubscription>,
    pub inbound_webhook: Option<WebhookContract>,
    pub outbound_webhook: Option<WebhookContract>,
    pub boundary_rules: Vec<String>,
    pub notes: Vec<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct IntegrationProviderCatalogResponse {
    pub items: Vec<IntegrationProviderSummary>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateImportJobRequest {
    pub provider_key: String,
    pub workspace_id: Option<String>,
    pub source_ref: Option<String>,
    #[serde(default)]
    pub options: Value,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateExportJobRequest {
    pub provider_key: String,
    pub workspace_id: Option<String>,
    pub target_ref: Option<String>,
    #[serde(default)]
    pub options: Value,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct IntegrationOperationStubResponse {
    pub operation: String,
    pub provider_key: String,
    pub status: String,
    pub message: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WebhookReceiptResponse {
    pub provider_key: String,
    pub status: String,
    pub message: String,
    pub accepted_event_types: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableEntityCounts {
    pub workspaces: i32,
    pub boards: i32,
    pub columns: i32,
    pub cards: i32,
    pub comments: i32,
    pub checklists: i32,
    pub attachments: i32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableBundleSummary {
    pub scope_kind: String,
    pub entity_counts: PortableEntityCounts,
    pub includes_activity_history: bool,
    pub includes_appearance: bool,
    pub includes_archived: bool,
    pub includes_attachments: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableBundleManifest {
    pub format: String,
    pub format_version: i32,
    pub bundle_kind: String,
    pub scope_kind: String,
    pub workspace_id: Option<Uuid>,
    pub board_id: Option<Uuid>,
    pub includes_local_metadata: bool,
    pub summary: PortableBundleSummary,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableBundleScope {
    pub scope_kind: String,
    pub workspace_id: Option<Uuid>,
    pub board_id: Option<Uuid>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableBundleOrigin {
    pub exported_by_user_id: Uuid,
    pub generated_at: String,
    pub backend_visible_state: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableBundleIncludes {
    pub appearance: bool,
    pub activity_history: bool,
    pub archived: bool,
    pub attachments: bool,
    pub local_metadata: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableBundlePayload {
    pub workspaces: Value,
    pub boards: Value,
    pub columns: Value,
    pub cards: Value,
    pub labels: Value,
    pub card_labels: Value,
    pub checklists: Value,
    pub checklist_items: Value,
    pub comments: Value,
    pub board_appearance_settings: Value,
    pub activity_entries: Value,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableBundleRestoreHints {
    pub recommended_strategy: String,
    pub requires_manual_review: bool,
    pub destructive_restore_allowed: bool,
    pub notes: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableBundle {
    #[serde(rename = "manifest.json")]
    pub manifest_json: PortableBundleManifest,
    pub scope: PortableBundleScope,
    pub origin: PortableBundleOrigin,
    pub includes: PortableBundleIncludes,
    pub payload: PortableBundlePayload,
    pub restore_hints: PortableBundleRestoreHints,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ImportExportCapabilitiesResponse {
    pub provider_key: String,
    pub format: String,
    pub format_version: i32,
    pub supported_export_modes: Vec<String>,
    pub client_only_backup_modes: Vec<String>,
    pub supported_import_modes: Vec<String>,
    pub supported_scope_kinds: Vec<String>,
    pub supported_restore_strategies: Vec<String>,
    pub max_bundle_size_bytes: Option<i64>,
    pub notes: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreatePortableExportRequest {
    pub scope_kind: String,
    pub workspace_id: Option<Uuid>,
    pub board_id: Option<Uuid>,
    pub export_mode: String,
    #[serde(default)]
    pub include_archived: bool,
    #[serde(default)]
    pub include_activity_history: bool,
    #[serde(default = "default_true")]
    pub include_appearance: bool,
    #[serde(default)]
    pub include_attachments: bool,
    pub target_ref: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PortableExportResponse {
    pub job_id: Uuid,
    pub provider_key: String,
    pub status: String,
    pub export_mode: String,
    pub suggested_file_name: String,
    pub target_ref: Option<String>,
    pub bundle_manifest: PortableBundleManifest,
    pub bundle: PortableBundle,
    pub message: String,
    pub warnings: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateImportPreviewRequest {
    pub source_ref: Option<String>,
    pub import_mode: String,
    pub target_workspace_id: Option<Uuid>,
    pub restore_strategy: String,
    #[serde(default)]
    pub bundle_manifest: Value,
    #[serde(default)]
    pub bundle: Value,
    #[serde(default)]
    pub options: Value,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ImportPreviewResponse {
    pub preview_id: Uuid,
    pub provider_key: String,
    pub status: String,
    pub detected_format: String,
    pub detected_format_version: i32,
    pub import_mode: String,
    pub restore_strategy: String,
    pub requires_manual_review: bool,
    pub warnings: Vec<String>,
    pub steps: Vec<String>,
    pub summary: PortableBundleSummary,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateImportExecutionRequest {
    pub source_ref: Option<String>,
    pub import_mode: String,
    pub target_workspace_id: Option<Uuid>,
    pub restore_strategy: String,
    pub preview_id: Option<Uuid>,
    #[serde(default)]
    pub bundle_manifest: Value,
    #[serde(default)]
    pub options: Value,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ImportExecutionResponse {
    pub job_id: Uuid,
    pub provider_key: String,
    pub status: String,
    pub import_mode: String,
    pub restore_strategy: String,
    pub preview_id: Option<Uuid>,
    pub target_workspace_id: Option<Uuid>,
    pub message: String,
    pub warnings: Vec<String>,
}

fn default_true() -> bool {
    true
}
