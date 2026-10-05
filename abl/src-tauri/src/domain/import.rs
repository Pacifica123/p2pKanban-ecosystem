use std::collections::{BTreeMap, BTreeSet};

use serde::Deserialize;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

pub const DEVICE_LINK_PROTOCOL_V2: &str = "p2p-kanban-device-link/2";
pub const DEVICE_LINK_GRANT_KIND: u16 = 27_780;
pub const DEVICE_LINK_REQUEST_KIND: u16 = 27_781;
pub const DEVICE_LINK_RESPONSE_KIND: u16 = 27_782;
pub const WEB_NODE_LINK_FORMAT: &str = "p2p-kanban-web-node-link";
pub const WEB_NODE_LINK_VERSION: u32 = 1;
pub const WEB_NODE_LINK_MAX_BYTES: usize = 32 * 1024 * 1024;
pub const PORTABLE_BUNDLE_FORMAT: &str = "p2p_planner_bundle";
pub const PORTABLE_BUNDLE_VERSION: u32 = 1;

const MAX_IMPORT_ENTITIES: usize = 100_000;
const MAX_TEXT_BYTES: usize = 1_048_576;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImportSourceKind {
    PortableBundleV1,
    DeviceLinkV2,
    WebNodeLinkV1,
}

impl ImportSourceKind {
    pub fn stable_name(self) -> &'static str {
        match self {
            Self::PortableBundleV1 => "portable-bundle-v1",
            Self::DeviceLinkV2 => "device-link-v2",
            Self::WebNodeLinkV1 => "web-node-link-v1",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ImportValidationError {
    InvalidJson,
    Oversized,
    UnsupportedFormat,
    UnsupportedVersion,
    LocalMetadataForbidden,
    SecretBearingInput,
    InvalidIdentifier,
    InvalidCapability,
    InvalidReference,
    DuplicateIdentifier,
    InvalidPosition,
    InvalidText,
    EmptyScope,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportReceiptSpec {
    pub source_digest: String,
    pub source_kind: ImportSourceKind,
    pub format_version: String,
    pub user_id: Option<String>,
    pub workspace_id: Option<String>,
    pub board_id: Option<String>,
    pub omissions_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PrincipalSpec {
    pub user_id: String,
    pub replica_id: String,
    pub device_public_key: String,
    pub provisioned_by: ImportSourceKind,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportedWorkspace {
    pub id: String,
    pub title: String,
    pub access_epoch: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportedBoard {
    pub id: String,
    pub workspace_id: String,
    pub title: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImportedColumn {
    pub id: String,
    pub board_id: String,
    pub title: String,
    pub position: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImportedCard {
    pub id: String,
    pub workspace_id: String,
    pub board_id: String,
    pub column_id: String,
    pub title: String,
    pub position: f64,
    pub archived: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImportedChecklist {
    pub id: String,
    pub workspace_id: String,
    pub board_id: String,
    pub card_id: String,
    pub title: String,
    pub position: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImportedChecklistItem {
    pub id: String,
    pub checklist_id: String,
    pub title: String,
    pub position: f64,
    pub is_done: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportedTombstone {
    pub entity_kind: String,
    pub entity_id: String,
    pub workspace_id: String,
    pub board_id: String,
    pub card_id: Option<String>,
    pub checklist_id: Option<String>,
    pub logical_clock: u64,
    pub replica_id: String,
    pub event_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityMetadataSpec {
    pub workspace_id: String,
    pub board_id: String,
    pub user_id: String,
    pub capability_epoch: u64,
    pub subject: String,
    pub can_delegate: bool,
    pub parent_id: Option<String>,
    pub expires_at_unix: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityExtensionSpec {
    pub entity_type: String,
    pub entity_id: String,
    pub payload_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpaqueSectionSpec {
    pub section_name: String,
    pub payload_json: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImportPlan {
    pub receipt: ImportReceiptSpec,
    pub principal: Option<PrincipalSpec>,
    pub workspaces: Vec<ImportedWorkspace>,
    pub boards: Vec<ImportedBoard>,
    pub columns: Vec<ImportedColumn>,
    pub cards: Vec<ImportedCard>,
    pub checklists: Vec<ImportedChecklist>,
    pub checklist_items: Vec<ImportedChecklistItem>,
    pub tombstones: Vec<ImportedTombstone>,
    pub capabilities: Vec<CapabilityMetadataSpec>,
    pub entity_extensions: Vec<EntityExtensionSpec>,
    pub opaque_sections: Vec<OpaqueSectionSpec>,
    pub requires_empty_profile: bool,
}

impl ImportPlan {
    pub fn validate_graph(&self) -> Result<(), ImportValidationError> {
        if self.receipt.source_digest.len() != 64
            || !self.receipt.source_digest.bytes().all(|byte| byte.is_ascii_hexdigit())
            || self.receipt.format_version.trim().is_empty()
        {
            return Err(ImportValidationError::InvalidIdentifier);
        }
        if let Some(value) = &self.receipt.user_id {
            validate_uuid(value)?;
        }
        if let Some(value) = &self.receipt.workspace_id {
            validate_uuid(value)?;
        }
        if let Some(value) = &self.receipt.board_id {
            validate_uuid(value)?;
        }
        let omissions: Vec<String> = serde_json::from_str(&self.receipt.omissions_json)
            .map_err(|_| ImportValidationError::InvalidJson)?;
        if omissions.iter().any(|value| value.trim().is_empty()) {
            return Err(ImportValidationError::InvalidJson);
        }
        if let Some(principal) = &self.principal {
            validate_uuid(&principal.user_id)?;
            validate_uuid(&principal.replica_id)?;
            if !is_hex_32_byte_key(&principal.device_public_key)
                || !matches!(principal.provisioned_by, ImportSourceKind::DeviceLinkV2 | ImportSourceKind::WebNodeLinkV1)
                || self.receipt.user_id.as_deref().is_some_and(|value| value != principal.user_id.as_str())
            {
                return Err(ImportValidationError::InvalidCapability);
            }
        }

        let total = self.workspaces.len()
            + self.boards.len()
            + self.columns.len()
            + self.cards.len()
            + self.checklists.len()
            + self.checklist_items.len()
            + self.tombstones.len();
        if total == 0 {
            return Err(ImportValidationError::EmptyScope);
        }
        if total > MAX_IMPORT_ENTITIES {
            return Err(ImportValidationError::Oversized);
        }

        let mut all_ids = BTreeSet::new();
        let mut workspace_ids = BTreeSet::new();
        for workspace in &self.workspaces {
            validate_uuid(&workspace.id)?;
            validate_text(&workspace.title)?;
            if workspace.access_epoch == 0 {
                return Err(ImportValidationError::InvalidCapability);
            }
            if !all_ids.insert(workspace.id.clone()) {
                return Err(ImportValidationError::DuplicateIdentifier);
            }
            workspace_ids.insert(workspace.id.clone());
        }

        let mut board_ids = BTreeSet::new();
        let mut board_workspace = BTreeMap::new();
        for board in &self.boards {
            validate_uuid(&board.id)?;
            validate_uuid(&board.workspace_id)?;
            validate_text(&board.title)?;
            if !workspace_ids.contains(&board.workspace_id) {
                return Err(ImportValidationError::InvalidReference);
            }
            if !all_ids.insert(board.id.clone()) {
                return Err(ImportValidationError::DuplicateIdentifier);
            }
            board_ids.insert(board.id.clone());
            board_workspace.insert(board.id.clone(), board.workspace_id.clone());
        }

        let mut column_ids = BTreeSet::new();
        let mut column_board = BTreeMap::new();
        for column in &self.columns {
            validate_uuid(&column.id)?;
            validate_uuid(&column.board_id)?;
            validate_text(&column.title)?;
            validate_position(column.position)?;
            if !board_ids.contains(&column.board_id) {
                return Err(ImportValidationError::InvalidReference);
            }
            if !all_ids.insert(column.id.clone()) {
                return Err(ImportValidationError::DuplicateIdentifier);
            }
            column_ids.insert(column.id.clone());
            column_board.insert(column.id.clone(), column.board_id.clone());
        }

        let mut card_ids = BTreeSet::new();
        let mut card_scope = BTreeMap::new();
        for card in &self.cards {
            validate_uuid(&card.id)?;
            validate_uuid(&card.workspace_id)?;
            validate_uuid(&card.board_id)?;
            validate_uuid(&card.column_id)?;
            validate_text(&card.title)?;
            validate_position(card.position)?;
            if board_workspace.get(&card.board_id) != Some(&card.workspace_id)
                || column_board.get(&card.column_id) != Some(&card.board_id)
            {
                return Err(ImportValidationError::InvalidReference);
            }
            if !all_ids.insert(card.id.clone()) {
                return Err(ImportValidationError::DuplicateIdentifier);
            }
            card_ids.insert(card.id.clone());
            card_scope.insert(card.id.clone(), (card.workspace_id.clone(), card.board_id.clone()));
        }

        let mut checklist_ids = BTreeSet::new();
        for checklist in &self.checklists {
            validate_uuid(&checklist.id)?;
            validate_uuid(&checklist.workspace_id)?;
            validate_uuid(&checklist.board_id)?;
            validate_uuid(&checklist.card_id)?;
            validate_text(&checklist.title)?;
            validate_position(checklist.position)?;
            if card_scope.get(&checklist.card_id)
                != Some(&(checklist.workspace_id.clone(), checklist.board_id.clone()))
            {
                return Err(ImportValidationError::InvalidReference);
            }
            if !all_ids.insert(checklist.id.clone()) {
                return Err(ImportValidationError::DuplicateIdentifier);
            }
            checklist_ids.insert(checklist.id.clone());
        }

        let mut item_ids = BTreeSet::new();
        for item in &self.checklist_items {
            validate_uuid(&item.id)?;
            validate_uuid(&item.checklist_id)?;
            validate_text(&item.title)?;
            validate_position(item.position)?;
            if !checklist_ids.contains(&item.checklist_id) {
                return Err(ImportValidationError::InvalidReference);
            }
            if !all_ids.insert(item.id.clone()) {
                return Err(ImportValidationError::DuplicateIdentifier);
            }
            item_ids.insert(item.id.clone());
        }

        let mut tombstone_ids = BTreeSet::new();
        for tombstone in &self.tombstones {
            validate_uuid(&tombstone.entity_id)?;
            validate_uuid(&tombstone.workspace_id)?;
            validate_uuid(&tombstone.board_id)?;
            validate_text(&tombstone.replica_id)?;
            validate_text(&tombstone.event_id)?;
            if tombstone.logical_clock == 0
                || tombstone.replica_id.trim().is_empty()
                || tombstone.event_id.trim().is_empty()
                || board_workspace.get(&tombstone.board_id) != Some(&tombstone.workspace_id)
                || !tombstone_ids.insert((tombstone.entity_kind.clone(), tombstone.entity_id.clone()))
            {
                return Err(ImportValidationError::InvalidReference);
            }
            match tombstone.entity_kind.as_str() {
                "card" => {
                    if tombstone.card_id.is_some() || tombstone.checklist_id.is_some() {
                        return Err(ImportValidationError::InvalidReference);
                    }
                }
                "checklist" => {
                    let card = tombstone.card_id.as_deref().ok_or(ImportValidationError::InvalidReference)?;
                    validate_uuid(card)?;
                    if tombstone.checklist_id.is_some() {
                        return Err(ImportValidationError::InvalidReference);
                    }
                }
                "checklist_item" => {
                    let card = tombstone.card_id.as_deref().ok_or(ImportValidationError::InvalidReference)?;
                    let checklist = tombstone.checklist_id.as_deref().ok_or(ImportValidationError::InvalidReference)?;
                    validate_uuid(card)?;
                    validate_uuid(checklist)?;
                }
                _ => return Err(ImportValidationError::InvalidReference),
            }
        }

        let mut capability_boards = BTreeSet::new();
        for capability in &self.capabilities {
            validate_capability_metadata(capability)?;
            if board_workspace.get(&capability.board_id) != Some(&capability.workspace_id)
                || !capability_boards.insert(capability.board_id.clone())
            {
                return Err(ImportValidationError::InvalidReference);
            }
            if let Some(principal) = &self.principal {
                if capability.user_id != principal.user_id
                    || capability.subject != principal.device_public_key
                {
                    return Err(ImportValidationError::InvalidCapability);
                }
            }
        }

        if let Some(workspace_id) = &self.receipt.workspace_id {
            if !workspace_ids.contains(workspace_id) {
                return Err(ImportValidationError::InvalidReference);
            }
        }
        if let Some(board_id) = &self.receipt.board_id {
            if !board_ids.contains(board_id) {
                return Err(ImportValidationError::InvalidReference);
            }
        }
        if let (Some(workspace_id), Some(board_id)) = (&self.receipt.workspace_id, &self.receipt.board_id) {
            if board_workspace.get(board_id) != Some(workspace_id) {
                return Err(ImportValidationError::InvalidReference);
            }
        }

        let mut opaque_names = BTreeSet::new();
        for section in &self.opaque_sections {
            let value: Value = serde_json::from_str(&section.payload_json)
                .map_err(|_| ImportValidationError::InvalidJson)?;
            if section.section_name.trim().is_empty()
                || !opaque_names.insert(section.section_name.clone())
            {
                return Err(ImportValidationError::InvalidJson);
            }
            reject_secret_bearing_keys(&value)?;
        }
        let mut extension_ids = BTreeSet::new();
        for extension in &self.entity_extensions {
            let value: Value = serde_json::from_str(&extension.payload_json)
                .map_err(|_| ImportValidationError::InvalidJson)?;
            let known_target = match extension.entity_type.as_str() {
                "board" => board_ids.contains(&extension.entity_id),
                "column" => column_ids.contains(&extension.entity_id),
                "card" => card_ids.contains(&extension.entity_id),
                "checklist" => checklist_ids.contains(&extension.entity_id),
                "checklist_item" => item_ids.contains(&extension.entity_id),
                _ => false,
            };
            if extension.entity_id.trim().is_empty()
                || !known_target
                || !extension_ids.insert((extension.entity_type.clone(), extension.entity_id.clone()))
            {
                return Err(ImportValidationError::InvalidReference);
            }
            reject_secret_bearing_keys(&value)?;
        }

        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DeviceLinkGrantV2 {
    pub protocol: String,
    pub workspace_id: String,
    pub board_id: String,
    pub user_id: String,
    pub epoch: u64,
    pub subject: String,
    pub can_delegate: bool,
    pub parent_id: Option<String>,
    pub expires_at: i64,
}

pub fn parse_device_link_grant_v2(raw: &str, now_unix: i64) -> Result<DeviceLinkGrantV2, ImportValidationError> {
    if raw.len() > MAX_TEXT_BYTES {
        return Err(ImportValidationError::Oversized);
    }
    let grant: DeviceLinkGrantV2 = serde_json::from_str(raw).map_err(|_| ImportValidationError::InvalidJson)?;
    if grant.protocol != DEVICE_LINK_PROTOCOL_V2 {
        return Err(ImportValidationError::UnsupportedVersion);
    }
    validate_uuid(&grant.workspace_id)?;
    validate_uuid(&grant.board_id)?;
    validate_uuid(&grant.user_id)?;
    if grant.epoch == 0 || grant.expires_at <= now_unix || !is_hex_32_byte_key(&grant.subject) {
        return Err(ImportValidationError::InvalidCapability);
    }
    if let Some(parent) = &grant.parent_id {
        if parent.trim().is_empty() || parent.len() > 512 {
            return Err(ImportValidationError::InvalidCapability);
        }
    }
    Ok(grant)
}

pub fn capability_from_device_link_grant(grant: &DeviceLinkGrantV2) -> CapabilityMetadataSpec {
    CapabilityMetadataSpec {
        workspace_id: grant.workspace_id.clone(),
        board_id: grant.board_id.clone(),
        user_id: grant.user_id.clone(),
        capability_epoch: grant.epoch,
        subject: grant.subject.clone(),
        can_delegate: grant.can_delegate,
        parent_id: grant.parent_id.clone(),
        expires_at_unix: Some(grant.expires_at),
    }
}

#[derive(Debug, Deserialize)]
struct PortableBundleDto {
    #[serde(rename = "manifest.json")]
    manifest: PortableManifestDto,
    scope: PortableScopeDto,
    #[serde(default)]
    origin: Value,
    #[serde(default)]
    includes: Value,
    payload: PortablePayloadDto,
    #[serde(default, rename = "restoreHints")]
    restore_hints: Value,
    #[serde(flatten)]
    extra: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PortableManifestDto {
    format: String,
    format_version: u32,
    bundle_kind: String,
    scope_kind: String,
    workspace_id: String,
    board_id: String,
    includes_local_metadata: bool,
    #[serde(flatten)]
    extra: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PortableScopeDto {
    scope_kind: String,
    workspace_id: String,
    board_id: String,
}

#[derive(Debug, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct PortablePayloadDto {
    #[serde(default)]
    workspaces: Vec<WorkspaceDto>,
    #[serde(default)]
    boards: Vec<BoardDto>,
    #[serde(default)]
    columns: Vec<ColumnDto>,
    #[serde(default)]
    cards: Vec<CardDto>,
    #[serde(default)]
    checklists: Vec<ChecklistDto>,
    #[serde(default)]
    checklist_items: Vec<ChecklistItemDto>,
    #[serde(default)]
    labels: Value,
    #[serde(default)]
    card_labels: Value,
    #[serde(default)]
    comments: Value,
    #[serde(default)]
    board_appearance_settings: Value,
    #[serde(default)]
    activity_entries: Value,
    #[serde(flatten)]
    extra: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
struct WorkspaceDto {
    id: String,
    #[serde(default, alias = "title")]
    name: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct BoardDto {
    id: String,
    workspace_id: String,
    #[serde(default, alias = "title")]
    name: String,
    #[serde(default)]
    archived_at: Option<Value>,
    #[serde(flatten)]
    extra: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ColumnDto {
    id: String,
    board_id: String,
    #[serde(default, alias = "title")]
    name: String,
    position: f64,
    #[serde(flatten)]
    extra: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CardDto {
    id: String,
    column_id: String,
    title: String,
    position: f64,
    #[serde(default)]
    archived_at: Option<Value>,
    #[serde(flatten)]
    extra: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ChecklistDto {
    id: String,
    card_id: String,
    #[serde(default, alias = "name")]
    title: String,
    position: f64,
    #[serde(flatten)]
    extra: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ChecklistItemDto {
    id: String,
    checklist_id: String,
    #[serde(default, alias = "name")]
    title: String,
    position: f64,
    #[serde(default, alias = "completed")]
    is_done: bool,
    #[serde(flatten)]
    extra: BTreeMap<String, Value>,
}

pub fn parse_portable_bundle_v1(raw: &str) -> Result<ImportPlan, ImportValidationError> {
    if raw.len() > WEB_NODE_LINK_MAX_BYTES {
        return Err(ImportValidationError::Oversized);
    }
    let raw_value: Value = serde_json::from_str(raw).map_err(|_| ImportValidationError::InvalidJson)?;
    reject_secret_bearing_keys(&raw_value)?;
    let bundle: PortableBundleDto = serde_json::from_value(raw_value).map_err(|_| ImportValidationError::InvalidJson)?;

    if bundle.manifest.format != PORTABLE_BUNDLE_FORMAT || bundle.manifest.bundle_kind != "portable_export" {
        return Err(ImportValidationError::UnsupportedFormat);
    }
    if bundle.manifest.format_version != PORTABLE_BUNDLE_VERSION {
        return Err(ImportValidationError::UnsupportedVersion);
    }
    if bundle.manifest.includes_local_metadata {
        return Err(ImportValidationError::LocalMetadataForbidden);
    }
    if bundle.manifest.scope_kind != "board" || bundle.scope.scope_kind != "board" {
        return Err(ImportValidationError::UnsupportedFormat);
    }
    if bundle.manifest.workspace_id != bundle.scope.workspace_id
        || bundle.manifest.board_id != bundle.scope.board_id
    {
        return Err(ImportValidationError::InvalidReference);
    }
    if bundle.payload.workspaces.len() != 1
        || bundle.payload.workspaces[0].id != bundle.scope.workspace_id
        || bundle.payload.boards.len() != 1
        || bundle.payload.boards[0].id != bundle.scope.board_id
        || bundle.payload.boards[0].workspace_id != bundle.scope.workspace_id
        || bundle.payload.columns.iter().any(|column| column.board_id != bundle.scope.board_id)
    {
        return Err(ImportValidationError::InvalidReference);
    }

    let workspace_by_id = bundle
        .payload
        .workspaces
        .iter()
        .map(|workspace| (workspace.id.clone(), workspace.name.clone()))
        .collect::<BTreeMap<_, _>>();
    let board_by_id = bundle
        .payload
        .boards
        .iter()
        .map(|board| (board.id.clone(), (board.workspace_id.clone(), board.name.clone())))
        .collect::<BTreeMap<_, _>>();
    let column_to_board = bundle
        .payload
        .columns
        .iter()
        .map(|column| (column.id.clone(), column.board_id.clone()))
        .collect::<BTreeMap<_, _>>();

    if !workspace_by_id.contains_key(&bundle.scope.workspace_id)
        || !board_by_id.contains_key(&bundle.scope.board_id)
    {
        return Err(ImportValidationError::InvalidReference);
    }

    let workspaces = bundle
        .payload
        .workspaces
        .iter()
        .map(|workspace| ImportedWorkspace {
            id: workspace.id.clone(),
            title: workspace.name.clone(),
            access_epoch: 1,
        })
        .collect::<Vec<_>>();
    let boards = bundle
        .payload
        .boards
        .iter()
        .map(|board| ImportedBoard {
            id: board.id.clone(),
            workspace_id: board.workspace_id.clone(),
            title: board.name.clone(),
        })
        .collect::<Vec<_>>();
    let columns = bundle
        .payload
        .columns
        .iter()
        .map(|column| ImportedColumn {
            id: column.id.clone(),
            board_id: column.board_id.clone(),
            title: column.name.clone(),
            position: column.position,
        })
        .collect::<Vec<_>>();

    let mut cards = Vec::with_capacity(bundle.payload.cards.len());
    for card in &bundle.payload.cards {
        let board_id = column_to_board
            .get(&card.column_id)
            .ok_or(ImportValidationError::InvalidReference)?;
        let workspace_id = board_by_id
            .get(board_id)
            .map(|value| value.0.clone())
            .ok_or(ImportValidationError::InvalidReference)?;
        cards.push(ImportedCard {
            id: card.id.clone(),
            workspace_id,
            board_id: board_id.clone(),
            column_id: card.column_id.clone(),
            title: card.title.clone(),
            position: card.position,
            archived: card.archived_at.is_some(),
        });
    }
    let card_by_id = cards
        .iter()
        .map(|card| (card.id.clone(), (card.workspace_id.clone(), card.board_id.clone())))
        .collect::<BTreeMap<_, _>>();

    let mut checklists = Vec::with_capacity(bundle.payload.checklists.len());
    for checklist in &bundle.payload.checklists {
        let (workspace_id, board_id) = card_by_id
            .get(&checklist.card_id)
            .cloned()
            .ok_or(ImportValidationError::InvalidReference)?;
        checklists.push(ImportedChecklist {
            id: checklist.id.clone(),
            workspace_id,
            board_id,
            card_id: checklist.card_id.clone(),
            title: checklist.title.clone(),
            position: checklist.position,
        });
    }
    let checklist_items = bundle
        .payload
        .checklist_items
        .iter()
        .map(|item| ImportedChecklistItem {
            id: item.id.clone(),
            checklist_id: item.checklist_id.clone(),
            title: item.title.clone(),
            position: item.position,
            is_done: item.is_done,
        })
        .collect::<Vec<_>>();

    let mut entity_extensions = Vec::new();
    for board in &bundle.payload.boards {
        let mut extra = board.extra.clone();
        if let Some(archived) = &board.archived_at {
            extra.insert("archivedAt".into(), archived.clone());
        }
        push_extension(&mut entity_extensions, "board", &board.id, extra)?;
    }
    for column in &bundle.payload.columns {
        push_extension(&mut entity_extensions, "column", &column.id, column.extra.clone())?;
    }
    for card in &bundle.payload.cards {
        let mut extra = card.extra.clone();
        if let Some(archived) = &card.archived_at {
            extra.insert("archivedAt".into(), archived.clone());
        }
        push_extension(&mut entity_extensions, "card", &card.id, extra)?;
    }
    for checklist in &bundle.payload.checklists {
        push_extension(&mut entity_extensions, "checklist", &checklist.id, checklist.extra.clone())?;
    }
    for item in &bundle.payload.checklist_items {
        push_extension(&mut entity_extensions, "checklist_item", &item.id, item.extra.clone())?;
    }

    let opaque_sections = vec![
        opaque("manifestExtra", &bundle.manifest.extra)?,
        opaque("origin", &bundle.origin)?,
        opaque("includes", &bundle.includes)?,
        opaque("restoreHints", &bundle.restore_hints)?,
        opaque("labels", &bundle.payload.labels)?,
        opaque("cardLabels", &bundle.payload.card_labels)?,
        opaque("comments", &bundle.payload.comments)?,
        opaque("boardAppearanceSettings", &bundle.payload.board_appearance_settings)?,
        opaque("activityEntries", &bundle.payload.activity_entries)?,
        opaque("payloadExtra", &bundle.payload.extra)?,
        opaque("bundleExtra", &bundle.extra)?,
    ];

    let plan = ImportPlan {
        receipt: ImportReceiptSpec {
            source_digest: sha256_hex(raw.as_bytes()),
            source_kind: ImportSourceKind::PortableBundleV1,
            format_version: PORTABLE_BUNDLE_VERSION.to_string(),
            user_id: None,
            workspace_id: Some(bundle.scope.workspace_id),
            board_id: Some(bundle.scope.board_id),
            omissions_json: "[\"identity\",\"capabilities\",\"sessions\",\"deployment-state\"]".into(),
        },
        principal: None,
        workspaces,
        boards,
        columns,
        cards,
        checklists,
        checklist_items,
        tombstones: Vec::new(),
        capabilities: Vec::new(),
        entity_extensions,
        opaque_sections,
        // A11 is a migration/import boundary, not the generic destructive restore UI.
        // Preserve stable logical IDs so web/Android/native coexistence does not fork board identity,
        // and require a fresh destination profile instead of remapping IDs behind restoreHints.
        requires_empty_profile: true,
    };
    plan.validate_graph()?;
    Ok(plan)
}


pub fn serialize_portable_bundle_v1(plan: &ImportPlan) -> Result<String, ImportValidationError> {
    plan.validate_graph()?;
    if plan.receipt.source_kind != ImportSourceKind::PortableBundleV1
        || plan.principal.is_some()
        || !plan.capabilities.is_empty()
        || !plan.tombstones.is_empty()
        || plan.workspaces.iter().any(|workspace| workspace.access_epoch != 1)
    {
        return Err(ImportValidationError::UnsupportedFormat);
    }

    let workspace_id = plan
        .receipt
        .workspace_id
        .as_deref()
        .ok_or(ImportValidationError::EmptyScope)?;
    let board_id = plan
        .receipt
        .board_id
        .as_deref()
        .ok_or(ImportValidationError::EmptyScope)?;

    let mut extension_map = BTreeMap::<(String, String), Map<String, Value>>::new();
    for extension in &plan.entity_extensions {
        let value: Value = serde_json::from_str(&extension.payload_json)
            .map_err(|_| ImportValidationError::InvalidJson)?;
        let object = value.as_object().ok_or(ImportValidationError::InvalidJson)?;
        extension_map.insert(
            (extension.entity_type.clone(), extension.entity_id.clone()),
            object.clone(),
        );
    }

    let mut workspace_values = Vec::with_capacity(plan.workspaces.len());
    for workspace in &plan.workspaces {
        let mut object = Map::new();
        object.insert("id".into(), Value::String(workspace.id.clone()));
        object.insert("name".into(), Value::String(workspace.title.clone()));
        workspace_values.push(Value::Object(object));
    }

    let mut board_values = Vec::with_capacity(plan.boards.len());
    for board in &plan.boards {
        let mut object = extension_object(&extension_map, "board", &board.id);
        object.insert("id".into(), Value::String(board.id.clone()));
        object.insert("name".into(), Value::String(board.title.clone()));
        object.insert("workspaceId".into(), Value::String(board.workspace_id.clone()));
        object.entry("archivedAt").or_insert(Value::Null);
        board_values.push(Value::Object(object));
    }

    let mut column_values = Vec::with_capacity(plan.columns.len());
    for column in &plan.columns {
        let mut object = extension_object(&extension_map, "column", &column.id);
        object.insert("id".into(), Value::String(column.id.clone()));
        object.insert("boardId".into(), Value::String(column.board_id.clone()));
        object.insert("name".into(), Value::String(column.title.clone()));
        object.insert("position".into(), finite_number(column.position)?);
        column_values.push(Value::Object(object));
    }

    let mut card_values = Vec::with_capacity(plan.cards.len());
    for card in &plan.cards {
        let mut object = extension_object(&extension_map, "card", &card.id);
        object.insert("id".into(), Value::String(card.id.clone()));
        object.insert("columnId".into(), Value::String(card.column_id.clone()));
        object.insert("title".into(), Value::String(card.title.clone()));
        object.insert("position".into(), finite_number(card.position)?);
        if !object.contains_key("archivedAt") {
            if card.archived {
                return Err(ImportValidationError::UnsupportedFormat);
            }
            object.insert("archivedAt".into(), Value::Null);
        }
        card_values.push(Value::Object(object));
    }

    let mut checklist_values = Vec::with_capacity(plan.checklists.len());
    for checklist in &plan.checklists {
        let mut object = extension_object(&extension_map, "checklist", &checklist.id);
        object.insert("id".into(), Value::String(checklist.id.clone()));
        object.insert("cardId".into(), Value::String(checklist.card_id.clone()));
        object.insert("title".into(), Value::String(checklist.title.clone()));
        object.insert("position".into(), finite_number(checklist.position)?);
        checklist_values.push(Value::Object(object));
    }

    let mut item_values = Vec::with_capacity(plan.checklist_items.len());
    for item in &plan.checklist_items {
        let mut object = extension_object(&extension_map, "checklist_item", &item.id);
        object.insert("id".into(), Value::String(item.id.clone()));
        object.insert("checklistId".into(), Value::String(item.checklist_id.clone()));
        object.insert("title".into(), Value::String(item.title.clone()));
        object.insert("position".into(), finite_number(item.position)?);
        object.insert("isDone".into(), Value::Bool(item.is_done));
        item_values.push(Value::Object(object));
    }

    let mut payload = opaque_object(plan, "payloadExtra")?;
    payload.insert("workspaces".into(), Value::Array(workspace_values));
    payload.insert("boards".into(), Value::Array(board_values));
    payload.insert("columns".into(), Value::Array(column_values));
    payload.insert("cards".into(), Value::Array(card_values));
    payload.insert("labels".into(), opaque_value(plan, "labels", Value::Array(Vec::new()))?);
    payload.insert("cardLabels".into(), opaque_value(plan, "cardLabels", Value::Array(Vec::new()))?);
    payload.insert("checklists".into(), Value::Array(checklist_values));
    payload.insert("checklistItems".into(), Value::Array(item_values));
    payload.insert("comments".into(), opaque_value(plan, "comments", Value::Array(Vec::new()))?);
    payload.insert(
        "boardAppearanceSettings".into(),
        opaque_value(plan, "boardAppearanceSettings", Value::Array(Vec::new()))?,
    );
    payload.insert(
        "activityEntries".into(),
        opaque_value(plan, "activityEntries", Value::Array(Vec::new()))?,
    );

    let mut manifest = opaque_object(plan, "manifestExtra")?;
    manifest.insert("format".into(), Value::String(PORTABLE_BUNDLE_FORMAT.into()));
    manifest.insert("formatVersion".into(), Value::from(PORTABLE_BUNDLE_VERSION));
    manifest.insert("bundleKind".into(), Value::String("portable_export".into()));
    manifest.insert("scopeKind".into(), Value::String("board".into()));
    manifest.insert("workspaceId".into(), Value::String(workspace_id.to_string()));
    manifest.insert("boardId".into(), Value::String(board_id.to_string()));
    manifest.insert("includesLocalMetadata".into(), Value::Bool(false));

    let mut scope = Map::new();
    scope.insert("scopeKind".into(), Value::String("board".into()));
    scope.insert("workspaceId".into(), Value::String(workspace_id.to_string()));
    scope.insert("boardId".into(), Value::String(board_id.to_string()));

    let mut root = opaque_object(plan, "bundleExtra")?;
    root.insert("manifest.json".into(), Value::Object(manifest));
    root.insert("scope".into(), Value::Object(scope));
    root.insert("origin".into(), opaque_value(plan, "origin", Value::Object(Map::new()))?);
    root.insert("includes".into(), opaque_value(plan, "includes", Value::Object(Map::new()))?);
    root.insert("payload".into(), Value::Object(payload));
    root.insert(
        "restoreHints".into(),
        opaque_value(plan, "restoreHints", Value::Object(Map::new()))?,
    );

    let value = Value::Object(root);
    reject_secret_bearing_keys(&value)?;
    serde_json::to_string_pretty(&value).map_err(|_| ImportValidationError::InvalidJson)
}

fn extension_object(
    extensions: &BTreeMap<(String, String), Map<String, Value>>,
    entity_type: &str,
    entity_id: &str,
) -> Map<String, Value> {
    extensions
        .get(&(entity_type.to_string(), entity_id.to_string()))
        .cloned()
        .unwrap_or_default()
}

fn finite_number(value: f64) -> Result<Value, ImportValidationError> {
    serde_json::Number::from_f64(value)
        .map(Value::Number)
        .ok_or(ImportValidationError::InvalidPosition)
}

fn opaque_value(plan: &ImportPlan, name: &str, default: Value) -> Result<Value, ImportValidationError> {
    let Some(section) = plan.opaque_sections.iter().find(|section| section.section_name == name) else {
        return Ok(default);
    };
    serde_json::from_str(&section.payload_json).map_err(|_| ImportValidationError::InvalidJson)
}

fn opaque_object(plan: &ImportPlan, name: &str) -> Result<Map<String, Value>, ImportValidationError> {
    let value = opaque_value(plan, name, Value::Object(Map::new()))?;
    value.as_object().cloned().ok_or(ImportValidationError::InvalidJson)
}

pub fn validate_web_node_link_envelope(raw: &str) -> Result<Value, ImportValidationError> {
    if raw.len() > WEB_NODE_LINK_MAX_BYTES {
        return Err(ImportValidationError::Oversized);
    }
    let value: Value = serde_json::from_str(raw).map_err(|_| ImportValidationError::InvalidJson)?;
    let object = value.as_object().ok_or(ImportValidationError::InvalidJson)?;
    if object.get("format").and_then(Value::as_str) != Some(WEB_NODE_LINK_FORMAT) {
        return Err(ImportValidationError::UnsupportedFormat);
    }
    if object.get("version").and_then(Value::as_u64) != Some(WEB_NODE_LINK_VERSION as u64) {
        return Err(ImportValidationError::UnsupportedVersion);
    }
    reject_web_node_link_forbidden_keys(&value)?;
    Ok(value)
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn opaque<T: serde::Serialize>(name: &str, value: &T) -> Result<OpaqueSectionSpec, ImportValidationError> {
    Ok(OpaqueSectionSpec {
        section_name: name.to_string(),
        payload_json: serde_json::to_string(value).map_err(|_| ImportValidationError::InvalidJson)?,
    })
}

fn push_extension(
    target: &mut Vec<EntityExtensionSpec>,
    entity_type: &str,
    entity_id: &str,
    extra: BTreeMap<String, Value>,
) -> Result<(), ImportValidationError> {
    if extra.is_empty() {
        return Ok(());
    }
    target.push(EntityExtensionSpec {
        entity_type: entity_type.to_string(),
        entity_id: entity_id.to_string(),
        payload_json: serde_json::to_string(&extra).map_err(|_| ImportValidationError::InvalidJson)?,
    });
    Ok(())
}

fn validate_uuid(value: &str) -> Result<(), ImportValidationError> {
    Uuid::parse_str(value)
        .map(|_| ())
        .map_err(|_| ImportValidationError::InvalidIdentifier)
}

fn validate_text(value: &str) -> Result<(), ImportValidationError> {
    if value.len() > MAX_TEXT_BYTES || value.as_bytes().contains(&0) {
        return Err(ImportValidationError::InvalidText);
    }
    Ok(())
}

fn validate_position(value: f64) -> Result<(), ImportValidationError> {
    if value.is_finite() {
        Ok(())
    } else {
        Err(ImportValidationError::InvalidPosition)
    }
}

fn validate_capability_metadata(value: &CapabilityMetadataSpec) -> Result<(), ImportValidationError> {
    validate_uuid(&value.workspace_id)?;
    validate_uuid(&value.board_id)?;
    validate_uuid(&value.user_id)?;
    if value.capability_epoch == 0 || !is_hex_32_byte_key(&value.subject) {
        return Err(ImportValidationError::InvalidCapability);
    }
    if let Some(parent_id) = &value.parent_id {
        if parent_id.trim().is_empty() || parent_id.len() > 512 {
            return Err(ImportValidationError::InvalidCapability);
        }
    }
    if value.expires_at_unix.is_some_and(|value| value <= 0) {
        return Err(ImportValidationError::InvalidCapability);
    }
    Ok(())
}

fn is_hex_32_byte_key(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn reject_web_node_link_forbidden_keys(value: &Value) -> Result<(), ImportValidationError> {
    const FORBIDDEN: &[&str] = &[
        "passwordhash",
        "accesstoken",
        "refreshtoken",
        "sessiontoken",
        "sessions",
        "devicerecords",
        "deviceprivatekey",
        "privatekey",
        "jwtsecret",
        "globalmasterkey",
        "nostrsigningsecret",
        "deploymentsecret",
    ];
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                let normalized = normalized_key(key);
                if FORBIDDEN.contains(&normalized.as_str()) {
                    return Err(ImportValidationError::SecretBearingInput);
                }
                reject_web_node_link_forbidden_keys(child)?;
            }
        }
        Value::Array(items) => {
            for item in items {
                reject_web_node_link_forbidden_keys(item)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn normalized_key(key: &str) -> String {
    key.chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect::<String>()
}

fn reject_secret_bearing_keys(value: &Value) -> Result<(), ImportValidationError> {
    const FORBIDDEN: &[&str] = &[
        "accesstoken",
        "refreshtoken",
        "sessiontoken",
        "passwordhash",
        "boardkey",
        "deviceprivatekey",
        "privatekey",
        "jwtsecret",
        "globalmasterkey",
        "nostrsigningsecret",
        "deploymentsecret",
    ];
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                let normalized = normalized_key(key);
                if FORBIDDEN.contains(&normalized.as_str()) {
                    return Err(ImportValidationError::SecretBearingInput);
                }
                reject_secret_bearing_keys(child)?;
            }
        }
        Value::Array(items) => {
            for item in items {
                reject_secret_bearing_keys(item)?;
            }
        }
        _ => {}
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a11_device_link_fixture_matches_v2_grant_contract() {
        let raw = include_str!("../../../fixtures/protocol/device-link-grant-v2.json");
        let grant = parse_device_link_grant_v2(raw, 1_900_000_000).unwrap();
        assert_eq!(grant.protocol, DEVICE_LINK_PROTOCOL_V2);
        assert_eq!(grant.epoch, 3);
        assert_eq!(DEVICE_LINK_GRANT_KIND, 27_780);
        assert_eq!(DEVICE_LINK_REQUEST_KIND, 27_781);
        assert_eq!(DEVICE_LINK_RESPONSE_KIND, 27_782);
    }

    #[test]
    fn a11_portable_bundle_fixture_normalizes_without_identity_or_secrets() {
        let raw = include_str!("../../../fixtures/export/portable-board-bundle-v1.json");
        let plan = parse_portable_bundle_v1(raw).unwrap();
        assert_eq!(plan.receipt.source_kind, ImportSourceKind::PortableBundleV1);
        assert!(plan.principal.is_none());
        assert!(plan.capabilities.is_empty());
        assert!(plan.requires_empty_profile);
        assert_eq!(plan.workspaces.len(), 1);
        assert_eq!(plan.boards.len(), 1);
        assert_eq!(plan.columns.len(), 1);
        assert_eq!(plan.cards.len(), 1);
    }

    #[test]
    fn a11_portable_bundle_rejects_secret_bearing_smuggling() {
        let raw = include_str!("../../../fixtures/export/portable-board-bundle-v1.json");
        let mut value: Value = serde_json::from_str(raw).unwrap();
        value["payload"]["boardKey"] = Value::String("do-not-import".into());
        assert_eq!(
            parse_portable_bundle_v1(&serde_json::to_string(&value).unwrap()),
            Err(ImportValidationError::SecretBearingInput)
        );
    }

    #[test]
    fn a11_portable_bundle_roundtrip_preserves_core_and_extensions_without_secrets() {
        let raw = include_str!("../../../fixtures/export/portable-board-bundle-v1.json");
        let first = parse_portable_bundle_v1(raw).unwrap();
        let exported = serialize_portable_bundle_v1(&first).unwrap();
        assert!(!exported.contains("boardKey"));
        assert!(!exported.contains("refreshToken"));
        let second = parse_portable_bundle_v1(&exported).unwrap();
        assert_eq!(first.workspaces, second.workspaces);
        assert_eq!(first.boards, second.boards);
        assert_eq!(first.columns, second.columns);
        assert_eq!(first.cards, second.cards);
        assert_eq!(first.checklists, second.checklists);
        assert_eq!(first.checklist_items, second.checklist_items);
        assert_eq!(first.entity_extensions, second.entity_extensions);
        assert_eq!(first.opaque_sections, second.opaque_sections);
    }

    #[test]
    fn a11_portable_archived_at_roundtrip_preserves_exact_value() {
        let raw = include_str!("../../../fixtures/export/portable-board-bundle-v1.json");
        let mut value: Value = serde_json::from_str(raw).unwrap();
        value["payload"]["cards"][0]["archivedAt"] =
            Value::String("2026-09-15T03:00:00Z".into());
        let plan = parse_portable_bundle_v1(&serde_json::to_string(&value).unwrap()).unwrap();
        assert!(plan.cards[0].archived);
        let exported = serialize_portable_bundle_v1(&plan).unwrap();
        let exported: Value = serde_json::from_str(&exported).unwrap();
        assert_eq!(
            exported["payload"]["cards"][0]["archivedAt"],
            Value::String("2026-09-15T03:00:00Z".into())
        );
    }

    #[test]
    fn a11_capability_subject_must_match_native_principal() {
        let raw = include_str!("../../../fixtures/export/portable-board-bundle-v1.json");
        let mut plan = parse_portable_bundle_v1(raw).unwrap();
        plan.receipt.source_kind = ImportSourceKind::WebNodeLinkV1;
        plan.receipt.user_id = Some("018f0000-0000-7000-8000-000000000004".into());
        plan.principal = Some(PrincipalSpec {
            user_id: "018f0000-0000-7000-8000-000000000004".into(),
            replica_id: "018f0000-0000-7000-8000-000000000006".into(),
            device_public_key: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".into(),
            provisioned_by: ImportSourceKind::WebNodeLinkV1,
        });
        plan.capabilities = vec![CapabilityMetadataSpec {
            workspace_id: plan.workspaces[0].id.clone(),
            board_id: plan.boards[0].id.clone(),
            user_id: "018f0000-0000-7000-8000-000000000004".into(),
            capability_epoch: 1,
            subject: "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff".into(),
            can_delegate: false,
            parent_id: None,
            expires_at_unix: None,
        }];
        assert_eq!(plan.validate_graph(), Err(ImportValidationError::InvalidCapability));
    }

    #[test]
    fn a11_web_node_link_envelope_rejects_downgrade_and_oversize() {
        let good = r#"{"format":"p2p-kanban-web-node-link","version":1}"#;
        assert!(validate_web_node_link_envelope(good).is_ok());
        let old = r#"{"format":"p2p-kanban-web-node-link","version":0}"#;
        assert_eq!(validate_web_node_link_envelope(old), Err(ImportValidationError::UnsupportedVersion));
        let oversized = "x".repeat(WEB_NODE_LINK_MAX_BYTES + 1);
        assert_eq!(validate_web_node_link_envelope(&oversized), Err(ImportValidationError::Oversized));
    }
}
