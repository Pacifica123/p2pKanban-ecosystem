use std::{collections::BTreeMap, sync::Arc};

use tauri::State;

use crate::{
    application::{
        integration::IntegrationService,
        lan_bridge::{LanBridgeService, LanBridgeServiceError, LanBridgeStartView},
        parity::{ActivityView, AppearanceView, CommentView, LabelView, ParityService, ParityServiceError},
        planner::{
            CardView, ChecklistItemView, ChecklistView, ColumnView, PlannerService, PlannerServiceError,
        },
        system::HealthView,
        vault::{VaultMode, VaultService, VaultState, VaultStatus},
        workspace::{BoardView, WorkspaceService, WorkspaceServiceError, WorkspaceView},
        ApplicationServices,
    },
    domain::{
        integration::{DeepLinkIntent, IntegrationCapabilities},
        lan_bridge::LanBridgeStatus,
    },
    infrastructure::linux::xdg::ProfileDiagnostics,
};

fn health_to_wire(view: HealthView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("status", view.status.to_string()),
        ("service", view.service.to_string()),
        ("version", view.version.to_string()),
        ("env", view.environment.to_string()),
    ])
}

fn profile_diagnostics_to_wire(view: &ProfileDiagnostics) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("dataRoot", view.data_root.display().to_string()),
        ("configRoot", view.config_root.display().to_string()),
        ("stateRoot", view.state_root.display().to_string()),
        ("cacheRoot", view.cache_root.display().to_string()),
        ("profileDatabase", view.profile_database.display().to_string()),
        (
            "runtimeActivation",
            if view.runtime_activation_available { "available" } else { "unavailable" }.to_owned(),
        ),
    ])
}

fn integration_capabilities_to_wire(view: IntegrationCapabilities) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("sessionType", view.session.as_str().to_owned()),
        ("desktop", view.desktop.unwrap_or_else(|| "unknown".to_owned())),
        ("sessionBus", view.session_bus.as_str().to_owned()),
        ("notifications", view.notifications.as_str().to_owned()),
        ("statusNotifier", view.status_notifier.as_str().to_owned()),
        ("portal", view.portal.as_str().to_owned()),
        ("runtimeActivation", view.runtime_activation.as_str().to_owned()),
        ("trayLifecycle", "disabled".to_owned()),
        ("systemdUserService", "disabled".to_owned()),
    ])
}

fn deep_link_intent_to_wire(intent: DeepLinkIntent) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("kind", intent.target.kind().to_owned()),
        ("entityId", intent.target.entity_id().unwrap_or_default()),
        ("canonical", intent.canonical),
    ])
}

fn lan_bridge_status_to_wire(status: LanBridgeStatus) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("lifecycle", status.lifecycle.as_str().to_owned()),
        ("bindAddress", status.bind_address.unwrap_or_default()),
        ("endpoint", status.endpoint.unwrap_or_default()),
        ("expiresAtUnix", status.expires_at_unix.map(|value| value.to_string()).unwrap_or_default()),
        ("attempts", status.attempts.to_string()),
        ("lastResult", status.last_result.unwrap_or_default()),
    ])
}

fn lan_bridge_start_to_wire(view: LanBridgeStartView) -> BTreeMap<&'static str, String> {
    let mut payload = lan_bridge_status_to_wire(view.status);
    payload.insert("capability", view.capability);
    payload.insert("devicePublicKey", view.device_public_key);
    payload
}

fn lan_bridge_error_code(error: LanBridgeServiceError) -> String {
    use crate::application::lan_bridge::{LanBridgeRuntimeError, LanBridgeServiceError::*};
    match error {
        InvalidRequest(_) => "LAN_BRIDGE_INVALID_REQUEST",
        AlreadyRunning => "LAN_BRIDGE_ALREADY_RUNNING",
        Runtime(LanBridgeRuntimeError::BindUnavailable) => "LAN_BRIDGE_BIND_UNAVAILABLE",
        Runtime(LanBridgeRuntimeError::UnsupportedAddress) => "LAN_BRIDGE_UNSUPPORTED_ADDRESS",
        Runtime(_) => "LAN_BRIDGE_RUNTIME_FAILURE",
        Randomness => "LAN_BRIDGE_RANDOMNESS_UNAVAILABLE",
        VaultNotDurable => "LAN_BRIDGE_DURABLE_VAULT_REQUIRED",
        InvalidPackage => "LAN_BRIDGE_INVALID_PACKAGE",
        ImportFailed => "LAN_BRIDGE_IMPORT_FAILED",
        Poisoned => "LAN_BRIDGE_UNAVAILABLE",
    }.to_owned()
}

fn workspace_to_wire(view: WorkspaceView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("title", view.title),
        ("accessEpoch", view.access_epoch.to_string()),
    ])
}

fn board_to_wire(view: BoardView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("workspaceId", view.workspace_id),
        ("title", view.title),
    ])
}


fn column_to_wire(view: ColumnView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("boardId", view.board_id),
        ("title", view.title),
        ("position", view.position.to_string()),
    ])
}

fn card_to_wire(view: CardView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("workspaceId", view.workspace_id),
        ("boardId", view.board_id),
        ("columnId", view.column_id),
        ("title", view.title),
        ("position", view.position.to_string()),
        ("archived", view.archived.to_string()),
    ])
}

fn checklist_to_wire(view: ChecklistView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("cardId", view.card_id),
        ("title", view.title),
        ("position", view.position.to_string()),
    ])
}

fn checklist_item_to_wire(view: ChecklistItemView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("checklistId", view.checklist_id),
        ("title", view.title),
        ("position", view.position.to_string()),
        ("isDone", view.is_done.to_string()),
    ])
}


fn label_to_wire(view: LabelView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("boardId", view.board_id),
        ("name", view.name),
        ("color", view.color.unwrap_or_default()),
        ("position", view.position.to_string()),
    ])
}

fn comment_to_wire(view: CommentView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("cardId", view.card_id),
        ("authorUserId", view.author_user_id.unwrap_or_default()),
        ("body", view.body),
        ("createdAt", view.created_at),
        ("updatedAt", view.updated_at),
    ])
}

fn appearance_to_wire(view: AppearanceView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("boardId", view.board_id),
        ("settingsJson", view.settings_json),
        ("updatedAt", view.updated_at),
    ])
}

fn activity_to_wire(view: ActivityView) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("id", view.id),
        ("boardId", view.board_id),
        ("cardId", view.card_id.unwrap_or_default()),
        ("actorUserId", view.actor_user_id.unwrap_or_default()),
        ("kind", view.kind),
        ("entityType", view.entity_type),
        ("entityId", view.entity_id.unwrap_or_default()),
        ("payloadJson", view.payload_json),
        ("occurredAt", view.occurred_at),
    ])
}

fn parity_error_code(error: ParityServiceError) -> String {
    match error {
        ParityServiceError::InvalidId => "INVALID_ID",
        ParityServiceError::EmptyValue => "VALUE_REQUIRED",
        ParityServiceError::ValueTooLong => "VALUE_TOO_LONG",
        ParityServiceError::InvalidJson => "INVALID_JSON",
        ParityServiceError::RepositoryPoisoned => "PARITY_SERVICE_UNAVAILABLE",
        ParityServiceError::Repository(inner) => match inner {
            crate::application::parity::ParityRepositoryError::WorkspaceNotFound => "WORKSPACE_NOT_FOUND",
            crate::application::parity::ParityRepositoryError::BoardNotFound => "BOARD_NOT_FOUND",
            crate::application::parity::ParityRepositoryError::CardNotFound => "CARD_NOT_FOUND",
            crate::application::parity::ParityRepositoryError::LabelNotFound => "LABEL_NOT_FOUND",
            crate::application::parity::ParityRepositoryError::CommentNotFound => "COMMENT_NOT_FOUND",
            crate::application::parity::ParityRepositoryError::ScopeMismatch => "SCOPE_MISMATCH",
            crate::application::parity::ParityRepositoryError::DuplicateLabel => "LABEL_ALREADY_EXISTS",
            crate::application::parity::ParityRepositoryError::DuplicateComment => "COMMENT_ALREADY_EXISTS",
            crate::application::parity::ParityRepositoryError::StorageFailure => "PARITY_STORAGE_FAILURE",
        },
    }.to_owned()
}

fn planner_error_code(error: PlannerServiceError) -> String {
    match error {
        PlannerServiceError::EmptyTitle => "TITLE_REQUIRED",
        PlannerServiceError::TitleTooLong => "TITLE_TOO_LONG",
        PlannerServiceError::InvalidId => "INVALID_ID",
        PlannerServiceError::OrderExhausted => "ORDER_EXHAUSTED",
        PlannerServiceError::RepositoryPoisoned => "PLANNER_SERVICE_UNAVAILABLE",
        PlannerServiceError::Repository(inner) => match inner {
            crate::application::repository::RepositoryError::WorkspaceNotFound => "WORKSPACE_NOT_FOUND",
            crate::application::repository::RepositoryError::StaleAccessEpoch { .. } => "STALE_ACCESS_EPOCH",
            crate::application::repository::RepositoryError::BoardNotFound => "BOARD_NOT_FOUND",
            crate::application::repository::RepositoryError::ColumnNotFound => "COLUMN_NOT_FOUND",
            crate::application::repository::RepositoryError::CardNotFound => "CARD_NOT_FOUND",
            crate::application::repository::RepositoryError::ScopeMismatch => "SCOPE_MISMATCH",
            crate::application::repository::RepositoryError::DuplicateCard => "CARD_ALREADY_EXISTS",
            crate::application::repository::RepositoryError::DuplicateColumn => "COLUMN_ALREADY_EXISTS",
            crate::application::repository::RepositoryError::DuplicateChecklist => "CHECKLIST_ALREADY_EXISTS",
            crate::application::repository::RepositoryError::DuplicateChecklistItem => "CHECKLIST_ITEM_ALREADY_EXISTS",
            crate::application::repository::RepositoryError::ChecklistNotFound => "CHECKLIST_NOT_FOUND",
            crate::application::repository::RepositoryError::ChecklistItemNotFound => "CHECKLIST_ITEM_NOT_FOUND",
            crate::application::repository::RepositoryError::DuplicateReorderItem => "DUPLICATE_REORDER_ITEM",
            crate::application::repository::RepositoryError::Tombstoned => "ENTITY_TOMBSTONED",
            crate::application::repository::RepositoryError::StorageFailure => "PLANNER_STORAGE_FAILURE",
        },
    }
    .to_owned()
}

fn vault_status_to_wire(status: VaultStatus) -> BTreeMap<&'static str, String> {
    let mode = match status.mode {
        VaultMode::SessionOnly => "session-only",
        VaultMode::SecretService => "secret-service",
        VaultMode::Passphrase => "passphrase",
    };
    let state = match status.state {
        VaultState::Ready => "ready",
        VaultState::ProviderUnavailable => "provider-unavailable",
        VaultState::ProviderLocked => "provider-locked",
        VaultState::ProviderCorrupt => "provider-corrupt",
        VaultState::PassphraseRequired => "passphrase-required",
    };
    BTreeMap::from([
        ("mode", mode.to_owned()),
        ("state", state.to_owned()),
        ("durable", status.durable.to_string()),
        ("passphraseFallbackAvailable", status.passphrase_fallback_available.to_string()),
    ])
}

fn workspace_error_code(error: WorkspaceServiceError) -> String {
    match error {
        WorkspaceServiceError::EmptyTitle => "TITLE_REQUIRED",
        WorkspaceServiceError::TitleTooLong => "TITLE_TOO_LONG",
        WorkspaceServiceError::InvalidId => "INVALID_ID",
        WorkspaceServiceError::RepositoryPoisoned => "WORKSPACE_SERVICE_UNAVAILABLE",
        WorkspaceServiceError::Repository(inner) => match inner {
            crate::application::workspace::WorkspaceRepositoryError::WorkspaceNotFound => "WORKSPACE_NOT_FOUND",
            crate::application::workspace::WorkspaceRepositoryError::BoardNotFound => "BOARD_NOT_FOUND",
            crate::application::workspace::WorkspaceRepositoryError::DuplicateWorkspace => "WORKSPACE_ALREADY_EXISTS",
            crate::application::workspace::WorkspaceRepositoryError::DuplicateBoard => "BOARD_ALREADY_EXISTS",
            crate::application::workspace::WorkspaceRepositoryError::StorageFailure => "WORKSPACE_STORAGE_FAILURE",
        },
    }
    .to_owned()
}

#[tauri::command]
pub fn desktop_api_health(app: State<'_, ApplicationServices>) -> BTreeMap<&'static str, String> {
    health_to_wire(app.system().health())
}

#[tauri::command]
pub fn desktop_api_profile_diagnostics(
    diagnostics: State<'_, ProfileDiagnostics>,
) -> BTreeMap<&'static str, String> {
    profile_diagnostics_to_wire(&diagnostics)
}

#[tauri::command]
pub fn desktop_api_vault_status(
    vault: State<'_, Arc<VaultService>>,
) -> BTreeMap<&'static str, String> {
    vault_status_to_wire(vault.status())
}

#[tauri::command]
pub fn desktop_api_list_workspaces(
    workspaces: State<'_, WorkspaceService>,
) -> Result<Vec<BTreeMap<&'static str, String>>, String> {
    workspaces
        .list_workspaces()
        .map(|items| items.into_iter().map(workspace_to_wire).collect())
        .map_err(workspace_error_code)
}

#[tauri::command]
pub fn desktop_api_create_workspace(
    title: String,
    workspaces: State<'_, WorkspaceService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    workspaces
        .create_workspace(&title)
        .map(workspace_to_wire)
        .map_err(workspace_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_boards(
    workspaceId: String,
    workspaces: State<'_, WorkspaceService>,
) -> Result<Vec<BTreeMap<&'static str, String>>, String> {
    workspaces
        .list_boards(&workspaceId)
        .map(|items| items.into_iter().map(board_to_wire).collect())
        .map_err(workspace_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_create_board(
    workspaceId: String,
    title: String,
    workspaces: State<'_, WorkspaceService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    workspaces
        .create_board(&workspaceId, &title)
        .map(board_to_wire)
        .map_err(workspace_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_open_board(
    workspaceId: String,
    boardId: String,
    workspaces: State<'_, WorkspaceService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    workspaces
        .open_board(&workspaceId, &boardId)
        .map(board_to_wire)
        .map_err(workspace_error_code)
}


#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_columns(
    workspaceId: String,
    boardId: String,
    planner: State<'_, PlannerService>,
) -> Result<Vec<BTreeMap<&'static str, String>>, String> {
    planner
        .list_columns(&workspaceId, &boardId)
        .map(|items| items.into_iter().map(column_to_wire).collect())
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_create_column(
    workspaceId: String,
    boardId: String,
    title: String,
    planner: State<'_, PlannerService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    planner
        .create_column(&workspaceId, &boardId, &title)
        .map(column_to_wire)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_cards(
    workspaceId: String,
    boardId: String,
    includeArchived: bool,
    planner: State<'_, PlannerService>,
) -> Result<Vec<BTreeMap<&'static str, String>>, String> {
    planner
        .list_cards(&workspaceId, &boardId, includeArchived)
        .map(|items| items.into_iter().map(card_to_wire).collect())
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_create_card(
    workspaceId: String,
    boardId: String,
    columnId: String,
    title: String,
    planner: State<'_, PlannerService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    planner
        .create_card(&workspaceId, &boardId, &columnId, &title)
        .map(card_to_wire)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_move_card(
    workspaceId: String,
    cardId: String,
    targetColumnId: String,
    planner: State<'_, PlannerService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    planner
        .move_card(&workspaceId, &cardId, &targetColumnId)
        .map(card_to_wire)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_swap_card_order(
    workspaceId: String,
    cardId: String,
    otherCardId: String,
    planner: State<'_, PlannerService>,
) -> Result<(), String> {
    planner
        .swap_card_order(&workspaceId, &cardId, &otherCardId)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_set_card_archived(
    workspaceId: String,
    cardId: String,
    archived: bool,
    planner: State<'_, PlannerService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    planner
        .set_card_archived(&workspaceId, &cardId, archived)
        .map(card_to_wire)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_delete_card(
    workspaceId: String,
    cardId: String,
    planner: State<'_, PlannerService>,
) -> Result<(), String> {
    planner.delete_card(&workspaceId, &cardId).map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_checklists(
    workspaceId: String,
    cardId: String,
    planner: State<'_, PlannerService>,
) -> Result<Vec<BTreeMap<&'static str, String>>, String> {
    planner
        .list_checklists(&workspaceId, &cardId)
        .map(|items| items.into_iter().map(checklist_to_wire).collect())
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_create_checklist(
    workspaceId: String,
    cardId: String,
    title: String,
    planner: State<'_, PlannerService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    planner
        .create_checklist(&workspaceId, &cardId, &title)
        .map(checklist_to_wire)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_delete_checklist(
    workspaceId: String,
    checklistId: String,
    planner: State<'_, PlannerService>,
) -> Result<(), String> {
    planner
        .delete_checklist(&workspaceId, &checklistId)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_checklist_items(
    workspaceId: String,
    checklistId: String,
    planner: State<'_, PlannerService>,
) -> Result<Vec<BTreeMap<&'static str, String>>, String> {
    planner
        .list_checklist_items(&workspaceId, &checklistId)
        .map(|items| items.into_iter().map(checklist_item_to_wire).collect())
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_create_checklist_item(
    workspaceId: String,
    checklistId: String,
    title: String,
    planner: State<'_, PlannerService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    planner
        .create_checklist_item(&workspaceId, &checklistId, &title)
        .map(checklist_item_to_wire)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_set_checklist_item_done(
    workspaceId: String,
    itemId: String,
    done: bool,
    planner: State<'_, PlannerService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    planner
        .set_checklist_item_done(&workspaceId, &itemId, done)
        .map(checklist_item_to_wire)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_delete_checklist_item(
    workspaceId: String,
    itemId: String,
    planner: State<'_, PlannerService>,
) -> Result<(), String> {
    planner
        .delete_checklist_item(&workspaceId, &itemId)
        .map_err(planner_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_pending_change_count(
    workspaceId: String,
    boardId: String,
    planner: State<'_, PlannerService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    planner
        .pending_change_count(&workspaceId, &boardId)
        .map(|count| BTreeMap::from([("count", count.to_string())]))
        .map_err(planner_error_code)
}


#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_labels(workspaceId:String, boardId:String, parity:State<'_,ParityService>) -> Result<Vec<BTreeMap<&'static str,String>>,String> {
    parity.list_labels(&workspaceId,&boardId).map(|items|items.into_iter().map(label_to_wire).collect()).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_create_label(workspaceId:String, boardId:String, name:String, color:Option<String>, parity:State<'_,ParityService>) -> Result<BTreeMap<&'static str,String>,String> {
    parity.create_label(&workspaceId,&boardId,&name,color.as_deref()).map(label_to_wire).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_delete_label(workspaceId:String, boardId:String, labelId:String, parity:State<'_,ParityService>) -> Result<(),String> {
    parity.delete_label(&workspaceId,&boardId,&labelId).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_card_label_ids(workspaceId:String, cardId:String, parity:State<'_,ParityService>) -> Result<Vec<String>,String> {
    parity.list_card_label_ids(&workspaceId,&cardId).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_set_card_label(workspaceId:String, cardId:String, labelId:String, assigned:bool, parity:State<'_,ParityService>) -> Result<(),String> {
    parity.set_card_label(&workspaceId,&cardId,&labelId,assigned).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_comments(workspaceId:String, cardId:String, parity:State<'_,ParityService>) -> Result<Vec<BTreeMap<&'static str,String>>,String> {
    parity.list_comments(&workspaceId,&cardId).map(|items|items.into_iter().map(comment_to_wire).collect()).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_create_comment(workspaceId:String, cardId:String, body:String, parity:State<'_,ParityService>) -> Result<BTreeMap<&'static str,String>,String> {
    parity.create_comment(&workspaceId,&cardId,&body).map(comment_to_wire).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_delete_comment(workspaceId:String, commentId:String, parity:State<'_,ParityService>) -> Result<(),String> {
    parity.delete_comment(&workspaceId,&commentId).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_get_appearance(workspaceId:String, boardId:String, parity:State<'_,ParityService>) -> Result<BTreeMap<&'static str,String>,String> {
    parity.get_appearance(&workspaceId,&boardId).map(appearance_to_wire).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_set_appearance(workspaceId:String, boardId:String, settingsJson:String, parity:State<'_,ParityService>) -> Result<BTreeMap<&'static str,String>,String> {
    parity.set_appearance(&workspaceId,&boardId,&settingsJson).map(appearance_to_wire).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_list_activity(workspaceId:String, boardId:String, limit:usize, parity:State<'_,ParityService>) -> Result<Vec<BTreeMap<&'static str,String>>,String> {
    parity.list_activity(&workspaceId,&boardId,limit).map(|items|items.into_iter().map(activity_to_wire).collect()).map_err(parity_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_unsynced_parity_count(workspaceId:String, boardId:String, parity:State<'_,ParityService>) -> Result<BTreeMap<&'static str,String>,String> {
    parity.unsynced_parity_count(&workspaceId,&boardId).map(|count|BTreeMap::from([("count",count.to_string())])).map_err(parity_error_code)
}

#[tauri::command]
pub fn desktop_api_integration_capabilities(
    integration: State<'_, IntegrationService>,
) -> BTreeMap<&'static str, String> {
    integration_capabilities_to_wire(integration.capabilities())
}

#[tauri::command]
pub fn desktop_api_take_deep_link_intents(
    integration: State<'_, IntegrationService>,
) -> Vec<BTreeMap<&'static str, String>> {
    integration
        .take_deep_links()
        .into_iter()
        .map(deep_link_intent_to_wire)
        .collect()
}


#[tauri::command]
pub fn desktop_api_lan_bridge_addresses(
    bridge: State<'_, LanBridgeService>,
) -> Vec<String> {
    bridge.available_bind_addresses()
}

#[tauri::command]
pub fn desktop_api_lan_bridge_status(
    bridge: State<'_, LanBridgeService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    bridge.status().map(lan_bridge_status_to_wire).map_err(lan_bridge_error_code)
}

#[allow(non_snake_case)]
#[tauri::command]
pub fn desktop_api_start_lan_bridge(
    bridge: State<'_, LanBridgeService>,
    bindAddress: String,
    ttlSeconds: u64,
) -> Result<BTreeMap<&'static str, String>, String> {
    bridge
        .start(&bindAddress, ttlSeconds)
        .map(lan_bridge_start_to_wire)
        .map_err(lan_bridge_error_code)
}

#[tauri::command]
pub fn desktop_api_stop_lan_bridge(
    bridge: State<'_, LanBridgeService>,
) -> Result<BTreeMap<&'static str, String>, String> {
    bridge.stop().map(lan_bridge_status_to_wire).map_err(lan_bridge_error_code)
}

#[cfg(test)]
mod tests {
    use super::{
        deep_link_intent_to_wire, health_to_wire, integration_capabilities_to_wire,
        lan_bridge_status_to_wire, profile_diagnostics_to_wire, vault_status_to_wire,
    };
    use crate::{
        application::{
            system::HealthView,
            vault::{VaultState, VaultStatus},
        },
        domain::{
            integration::{parse_deep_link, CapabilityState, IntegrationCapabilities, SessionKind},
            lan_bridge::{LanBridgeLifecycle, LanBridgeStatus},
        },
        infrastructure::linux::xdg::ProfileDiagnostics,
    };
    use std::path::PathBuf;

    #[test]
    fn adapter_maps_application_read_model_to_existing_wire_contract() {
        let payload = health_to_wire(HealthView {
            status: "ok",
            service: "native-test",
            version: "1.2.3",
            environment: "desktop",
        });

        assert_eq!(payload.get("status").map(String::as_str), Some("ok"));
        assert_eq!(payload.get("service").map(String::as_str), Some("native-test"));
        assert_eq!(payload.get("version").map(String::as_str), Some("1.2.3"));
        assert_eq!(payload.get("env").map(String::as_str), Some("desktop"));
    }

    #[test]
    fn diagnostics_adapter_exposes_only_resolved_paths_and_runtime_capability() {
        let payload = profile_diagnostics_to_wire(&ProfileDiagnostics {
            data_root: PathBuf::from("/tmp/data/p2pkanban"),
            config_root: PathBuf::from("/tmp/config/p2pkanban"),
            state_root: PathBuf::from("/tmp/state/p2pkanban"),
            cache_root: PathBuf::from("/tmp/cache/p2pkanban"),
            profile_database: PathBuf::from("/tmp/data/p2pkanban/profiles/default/profile.db"),
            runtime_activation_available: false,
        });
        assert_eq!(payload.get("runtimeActivation").map(String::as_str), Some("unavailable"));
        assert_eq!(payload.len(), 6);
    }

    #[test]
    fn vault_status_wire_exposes_capability_but_not_secret_operations() {
        let payload = vault_status_to_wire(VaultStatus::session_only(
            VaultState::ProviderUnavailable,
        ));
        assert_eq!(payload.get("mode").map(String::as_str), Some("session-only"));
        assert_eq!(
            payload.get("state").map(String::as_str),
            Some("provider-unavailable")
        );
        assert_eq!(payload.get("durable").map(String::as_str), Some("false"));
        assert_eq!(
            payload.get("passphraseFallbackAvailable").map(String::as_str),
            Some("true")
        );
        assert_eq!(payload.len(), 4);
    }

    #[test]
    fn a13_integration_wire_exposes_capabilities_and_validated_intents_only() {
        let payload = integration_capabilities_to_wire(IntegrationCapabilities {
            session: SessionKind::X11,
            desktop: Some("KDE".into()),
            session_bus: CapabilityState::Available,
            notifications: CapabilityState::Unavailable,
            status_notifier: CapabilityState::Available,
            portal: CapabilityState::Unavailable,
            runtime_activation: CapabilityState::Available,
        });
        assert_eq!(payload.get("sessionType").map(String::as_str), Some("x11"));
        assert_eq!(payload.get("notifications").map(String::as_str), Some("unavailable"));
        assert_eq!(payload.get("trayLifecycle").map(String::as_str), Some("disabled"));
        assert_eq!(payload.get("systemdUserService").map(String::as_str), Some("disabled"));
        assert_eq!(payload.len(), 9);

        let intent = deep_link_intent_to_wire(
            parse_deep_link("p2pkanban://board/11111111-2222-4333-8444-555555555555").unwrap(),
        );
        assert_eq!(intent.get("kind").map(String::as_str), Some("board"));
        assert_eq!(intent.get("entityId").map(String::as_str), Some("11111111-2222-4333-8444-555555555555"));
    }


    #[test]
    fn a14_bridge_wire_exposes_lifecycle_metadata_without_secret_material() {
        let payload = lan_bridge_status_to_wire(LanBridgeStatus {
            lifecycle: LanBridgeLifecycle::Listening,
            bind_address: Some("192.168.1.2:55000".into()),
            endpoint: Some("http://192.168.1.2:55000/v1/p2pkanban/pair".into()),
            expires_at_unix: Some(2_000_000_000),
            attempts: 2,
            last_result: None,
        });
        assert_eq!(payload.get("lifecycle").map(String::as_str), Some("listening"));
        assert_eq!(payload.get("attempts").map(String::as_str), Some("2"));
        assert!(!payload.contains_key("capability"));
        assert_eq!(payload.len(), 6);
    }

}
