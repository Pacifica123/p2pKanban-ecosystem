use std::sync::Mutex;

use uuid::Uuid;

use crate::{
    application::vault::{SecretKind, SecretRecordKey, SecretValue, VaultError, VaultService},
    domain::import::{
        capability_from_device_link_grant, parse_device_link_grant_v2, parse_portable_bundle_v1,
        sha256_hex, validate_web_node_link_envelope, ImportPlan, ImportSourceKind, PrincipalSpec,
    },
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ImportRepositoryError {
    StorageFailure,
    DestinationNotEmpty,
    Replay,
    IdentityConflict,
    InvalidScope,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportApplyReport {
    pub source_kind: ImportSourceKind,
    pub workspaces: usize,
    pub boards: usize,
    pub cards: usize,
    pub tombstones: usize,
    pub omissions: Vec<String>,
}

pub trait ImportRepository: Send {
    fn preflight(&self, plan: &ImportPlan) -> Result<(), ImportRepositoryError>;
    fn apply_plan(&mut self, plan: &ImportPlan) -> Result<ImportApplyReport, ImportRepositoryError>;
}

/// Device identity material is created/verified by the native device-link or
/// node-link transport adapter. It never crosses the WebView boundary.
pub struct DeviceIdentityMaterial {
    public_key: String,
    private_key: SecretValue,
}

impl DeviceIdentityMaterial {
    pub fn new(public_key: impl Into<String>, private_key: Vec<u8>) -> Result<Self, VaultError> {
        let public_key = public_key.into();
        if public_key.len() != 64 || !public_key.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(VaultError::InvalidKey);
        }
        if private_key.len() != 32 {
            return Err(VaultError::InvalidKey);
        }
        Ok(Self {
            public_key,
            private_key: SecretValue::new(private_key)?,
        })
    }

    pub fn public_key(&self) -> &str {
        &self.public_key
    }
}

/// Board capability material is deliberately non-Debug and vault-only.
pub struct BoardCapabilityMaterial {
    board_id: String,
    secret: SecretValue,
}

impl BoardCapabilityMaterial {
    pub fn new(board_id: impl Into<String>, board_key: Vec<u8>) -> Result<Self, VaultError> {
        let board_id = board_id.into();
        if Uuid::parse_str(&board_id).is_err() || board_key.len() != 32 {
            return Err(VaultError::InvalidKey);
        }
        Ok(Self {
            board_id,
            secret: SecretValue::new(board_key)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ImportServiceError {
    Validation,
    Repository(ImportRepositoryError),
    Vault(VaultError),
    AuthenticatedScopeMismatch,
    VaultKeyConflict,
}

impl From<ImportRepositoryError> for ImportServiceError {
    fn from(value: ImportRepositoryError) -> Self {
        Self::Repository(value)
    }
}

impl From<VaultError> for ImportServiceError {
    fn from(value: VaultError) -> Self {
        Self::Vault(value)
    }
}

pub struct ImportService {
    repository: Mutex<Box<dyn ImportRepository>>,
}

impl ImportService {
    pub fn new(repository: Box<dyn ImportRepository>) -> Self {
        Self {
            repository: Mutex::new(repository),
        }
    }

    pub fn import_portable_bundle(&self, raw: &str) -> Result<ImportApplyReport, ImportServiceError> {
        let plan = parse_portable_bundle_v1(raw).map_err(|_| ImportServiceError::Validation)?;
        self.apply_without_secrets(plan)
    }

    /// Consumes a planner snapshot that has already been decrypted and authenticated
    /// by a device-link/2 transport adapter. This layer validates the grant's stable
    /// protocol/scope/expiry contract and binds the vault material to that scope.
    pub fn provision_authenticated_device_link(
        &self,
        grant_json: &str,
        now_unix: i64,
        mut snapshot: ImportPlan,
        identity: DeviceIdentityMaterial,
        board_capability: BoardCapabilityMaterial,
        vault: &VaultService,
    ) -> Result<ImportApplyReport, ImportServiceError> {
        let grant = parse_device_link_grant_v2(grant_json, now_unix)
            .map_err(|_| ImportServiceError::Validation)?;
        if identity.public_key() != grant.subject
            || board_capability.board_id != grant.board_id
            || snapshot.receipt.workspace_id.as_deref() != Some(grant.workspace_id.as_str())
            || snapshot.receipt.board_id.as_deref() != Some(grant.board_id.as_str())
            || snapshot.workspaces.len() != 1
            || snapshot.workspaces[0].id != grant.workspace_id
            || snapshot.boards.len() != 1
            || snapshot.boards[0].id != grant.board_id
            || snapshot.boards[0].workspace_id != grant.workspace_id
            || snapshot.columns.iter().any(|column| column.board_id != grant.board_id)
            || snapshot.cards.iter().any(|card| card.board_id != grant.board_id || card.workspace_id != grant.workspace_id)
            || snapshot.checklists.iter().any(|checklist| checklist.board_id != grant.board_id || checklist.workspace_id != grant.workspace_id)
        {
            return Err(ImportServiceError::AuthenticatedScopeMismatch);
        }

        snapshot.receipt.source_digest = sha256_hex(grant_json.as_bytes());
        snapshot.receipt.source_kind = ImportSourceKind::DeviceLinkV2;
        snapshot.receipt.format_version = "2".into();
        snapshot.receipt.user_id = Some(grant.user_id.clone());
        snapshot.receipt.omissions_json =
            "[\"password-hash\",\"sessions\",\"deployment-state\"]".into();
        snapshot.principal = Some(PrincipalSpec {
            user_id: grant.user_id.clone(),
            replica_id: Uuid::new_v4().to_string(),
            device_public_key: identity.public_key.clone(),
            provisioned_by: ImportSourceKind::DeviceLinkV2,
        });
        snapshot.capabilities = vec![capability_from_device_link_grant(&grant)];
        snapshot.requires_empty_profile = true;
        for workspace in &mut snapshot.workspaces {
            if workspace.id == grant.workspace_id {
                workspace.access_epoch = grant.epoch;
            }
        }
        snapshot.validate_graph().map_err(|_| ImportServiceError::Validation)?;

        self.apply_with_secrets(
            snapshot,
            identity,
            vec![board_capability],
            vault,
        )
    }

    /// Applies destination semantics for the existing web-node-link v1 contract.
    /// Source HTTP/session/Docker mechanics stay outside the native runtime. The
    /// caller supplies a normalized plan plus capability material obtained by the
    /// native migration adapter; deployment/session credentials are never accepted.
    pub fn import_web_node_link_v1(
        &self,
        envelope_json: &str,
        mut plan: ImportPlan,
        identity: DeviceIdentityMaterial,
        board_capabilities: Vec<BoardCapabilityMaterial>,
        vault: &VaultService,
    ) -> Result<ImportApplyReport, ImportServiceError> {
        validate_web_node_link_envelope(envelope_json)
            .map_err(|_| ImportServiceError::Validation)?;
        let principal = plan.principal.as_mut().ok_or(ImportServiceError::Validation)?;
        if principal.device_public_key != identity.public_key {
            return Err(ImportServiceError::AuthenticatedScopeMismatch);
        }
        principal.replica_id = Uuid::new_v4().to_string();
        principal.provisioned_by = ImportSourceKind::WebNodeLinkV1;
        plan.receipt.user_id = Some(principal.user_id.clone());
        plan.receipt.source_digest = sha256_hex(envelope_json.as_bytes());
        plan.receipt.source_kind = ImportSourceKind::WebNodeLinkV1;
        plan.receipt.format_version = "1".into();
        plan.receipt.omissions_json = "[\"password-hash\",\"active-sessions\",\"tokens\",\"device-records\",\"deployment-jwt\",\"global-master\",\"deployment-nostr\",\"shared-workspaces\",\"node-local-hides\"]".into();
        plan.requires_empty_profile = true;
        plan.validate_graph().map_err(|_| ImportServiceError::Validation)?;

        let expected_boards = plan
            .capabilities
            .iter()
            .map(|capability| capability.board_id.as_str())
            .collect::<std::collections::BTreeSet<_>>();
        let supplied_boards = board_capabilities
            .iter()
            .map(|capability| capability.board_id.as_str())
            .collect::<std::collections::BTreeSet<_>>();
        if expected_boards != supplied_boards
            || expected_boards.len() != plan.capabilities.len()
            || supplied_boards.len() != board_capabilities.len()
        {
            return Err(ImportServiceError::AuthenticatedScopeMismatch);
        }

        self.apply_with_secrets(plan, identity, board_capabilities, vault)
    }

    fn apply_without_secrets(&self, plan: ImportPlan) -> Result<ImportApplyReport, ImportServiceError> {
        plan.validate_graph().map_err(|_| ImportServiceError::Validation)?;
        let mut repository = self
            .repository
            .lock()
            .map_err(|_| ImportServiceError::Repository(ImportRepositoryError::StorageFailure))?;
        repository.preflight(&plan)?;
        repository.apply_plan(&plan).map_err(Into::into)
    }

    fn apply_with_secrets(
        &self,
        plan: ImportPlan,
        identity: DeviceIdentityMaterial,
        board_capabilities: Vec<BoardCapabilityMaterial>,
        vault: &VaultService,
    ) -> Result<ImportApplyReport, ImportServiceError> {
        let mut repository = self
            .repository
            .lock()
            .map_err(|_| ImportServiceError::Repository(ImportRepositoryError::StorageFailure))?;
        repository.preflight(&plan)?;

        let device_key = SecretRecordKey::new(
            SecretKind::DevicePrivateKey,
            format!("device:{}", identity.public_key),
        )?;
        let mut capability_keys = Vec::with_capacity(board_capabilities.len());
        for capability in &board_capabilities {
            capability_keys.push(SecretRecordKey::new(SecretKind::BoardCapability, &capability.board_id)?);
        }
        if vault.provider().get(&device_key)?.is_some() {
            return Err(ImportServiceError::VaultKeyConflict);
        }
        for key in &capability_keys {
            if vault.provider().get(key)?.is_some() {
                return Err(ImportServiceError::VaultKeyConflict);
            }
        }

        let mut written = Vec::new();
        vault.provider().put(device_key.clone(), identity.private_key)?;
        written.push(device_key);

        for (capability, key) in board_capabilities.into_iter().zip(capability_keys) {
            if let Err(error) = vault.provider().put(key.clone(), capability.secret) {
                cleanup_vault_writes(vault, &written);
                return Err(ImportServiceError::Vault(error));
            }
            written.push(key);
        }

        match repository.apply_plan(&plan) {
            Ok(report) => Ok(report),
            Err(error) => {
                cleanup_vault_writes(vault, &written);
                Err(ImportServiceError::Repository(error))
            }
        }
    }
}

fn cleanup_vault_writes(vault: &VaultService, keys: &[SecretRecordKey]) {
    for key in keys.iter().rev() {
        let _ = vault.provider().delete(key);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        application::vault::SessionVault,
        domain::import::{
            CapabilityMetadataSpec, ImportReceiptSpec, ImportedBoard, ImportedColumn,
            ImportedWorkspace,
        },
    };

    struct RejectingRepository;

    impl ImportRepository for RejectingRepository {
        fn preflight(&self, _: &ImportPlan) -> Result<(), ImportRepositoryError> {
            Ok(())
        }

        fn apply_plan(&mut self, _: &ImportPlan) -> Result<ImportApplyReport, ImportRepositoryError> {
            Err(ImportRepositoryError::StorageFailure)
        }
    }

    fn minimal_device_plan() -> ImportPlan {
        ImportPlan {
            receipt: ImportReceiptSpec {
                source_digest: "0".repeat(64),
                source_kind: ImportSourceKind::DeviceLinkV2,
                format_version: "2".into(),
                user_id: None,
                workspace_id: Some("018f0000-0000-7000-8000-000000000001".into()),
                board_id: Some("018f0000-0000-7000-8000-000000000002".into()),
                omissions_json: "[]".into(),
            },
            principal: None,
            workspaces: vec![ImportedWorkspace {
                id: "018f0000-0000-7000-8000-000000000001".into(),
                title: "linked".into(),
                access_epoch: 1,
            }],
            boards: vec![ImportedBoard {
                id: "018f0000-0000-7000-8000-000000000002".into(),
                workspace_id: "018f0000-0000-7000-8000-000000000001".into(),
                title: "linked".into(),
            }],
            columns: vec![ImportedColumn {
                id: "018f0000-0000-7000-8000-000000000005".into(),
                board_id: "018f0000-0000-7000-8000-000000000002".into(),
                title: "Todo".into(),
                position: 1000.0,
            }],
            cards: vec![],
            checklists: vec![],
            checklist_items: vec![],
            tombstones: vec![],
            capabilities: vec![CapabilityMetadataSpec {
                workspace_id: "018f0000-0000-7000-8000-000000000001".into(),
                board_id: "018f0000-0000-7000-8000-000000000002".into(),
                user_id: "018f0000-0000-7000-8000-000000000004".into(),
                capability_epoch: 3,
                subject: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".into(),
                can_delegate: false,
                parent_id: None,
                expires_at_unix: Some(2_000_000_000),
            }],
            entity_extensions: vec![],
            opaque_sections: vec![],
            requires_empty_profile: true,
        }
    }

    #[test]
    fn a11_existing_vault_material_blocks_import_without_overwrite() {
        let service = ImportService::new(Box::new(RejectingRepository));
        let vault = VaultService::from_provider(SessionVault::default());
        let board_key = SecretRecordKey::new(
            SecretKind::BoardCapability,
            "018f0000-0000-7000-8000-000000000002",
        )
        .unwrap();
        vault
            .provider()
            .put(board_key.clone(), SecretValue::new(vec![3; 32]).unwrap())
            .unwrap();
        let identity = DeviceIdentityMaterial::new(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            vec![7; 32],
        )
        .unwrap();
        let capability = BoardCapabilityMaterial::new(
            "018f0000-0000-7000-8000-000000000002",
            vec![9; 32],
        )
        .unwrap();
        let raw = include_str!("../../../fixtures/protocol/device-link-grant-v2.json");
        assert_eq!(
            service.provision_authenticated_device_link(
                raw,
                1_900_000_000,
                minimal_device_plan(),
                identity,
                capability,
                &vault,
            ),
            Err(ImportServiceError::VaultKeyConflict)
        );
        let existing = vault.provider().get(&board_key).unwrap().unwrap();
        assert_eq!(existing.expose(), &[3; 32]);
    }

    #[test]
    fn a11_repository_failure_compensates_new_vault_material() {
        let service = ImportService::new(Box::new(RejectingRepository));
        let vault = VaultService::from_provider(SessionVault::default());
        let identity = DeviceIdentityMaterial::new(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            vec![7; 32],
        )
        .unwrap();
        let capability = BoardCapabilityMaterial::new(
            "018f0000-0000-7000-8000-000000000002",
            vec![9; 32],
        )
        .unwrap();
        let raw = include_str!("../../../fixtures/protocol/device-link-grant-v2.json");
        assert_eq!(
            service.provision_authenticated_device_link(
                raw,
                1_900_000_000,
                minimal_device_plan(),
                identity,
                capability,
                &vault,
            ),
            Err(ImportServiceError::Repository(ImportRepositoryError::StorageFailure))
        );
        let board_key = SecretRecordKey::new(
            SecretKind::BoardCapability,
            "018f0000-0000-7000-8000-000000000002",
        )
        .unwrap();
        assert!(vault.provider().get(&board_key).unwrap().is_none());
        let device_key = SecretRecordKey::new(
            SecretKind::DevicePrivateKey,
            "device:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )
        .unwrap();
        assert!(vault.provider().get(&device_key).unwrap().is_none());
    }
}
