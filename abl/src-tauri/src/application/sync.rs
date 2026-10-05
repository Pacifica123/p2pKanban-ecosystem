use std::sync::Mutex;

use crate::{
    application::vault::{SecretKind, SecretRecordKey, SecretValue, VaultError, VaultService},
    domain::sync::{RoamingBoardEvent, RoamingScope, SyncCoreError},
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncMaterializeReport {
    pub pending_markers: u64,
    pub materialized_events: u64,
    pub already_materialized_markers: u64,
    pub blocked_markers: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncApplyReport {
    pub received: u64,
    pub applied: u64,
    pub duplicates: u64,
    pub stale: u64,
    pub tombstone_blocked: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SyncRepositoryError {
    StorageFailure,
    WorkspaceNotFound,
    BoardNotFound,
    ScopeMismatch,
    StaleCapabilityEpoch,
    InvalidEvent,
    ReplayConflict,
    UnsupportedPendingKind(String),
}

pub trait SyncRepository: Send {
    fn materialize_pending(
        &mut self,
        scope: &RoamingScope,
    ) -> Result<SyncMaterializeReport, SyncRepositoryError>;

    fn list_outbox(
        &self,
        scope: &RoamingScope,
    ) -> Result<Vec<RoamingBoardEvent>, SyncRepositoryError>;

    fn apply_remote_batch(
        &mut self,
        scope: &RoamingScope,
        events: &[RoamingBoardEvent],
    ) -> Result<SyncApplyReport, SyncRepositoryError>;
}

pub struct SyncService {
    repository: Mutex<Box<dyn SyncRepository>>,
}

impl SyncService {
    pub fn new(repository: Box<dyn SyncRepository>) -> Self {
        Self {
            repository: Mutex::new(repository),
        }
    }

    pub fn materialize_pending(
        &self,
        scope: &RoamingScope,
    ) -> Result<SyncMaterializeReport, SyncRepositoryError> {
        self.repository
            .lock()
            .map_err(|_| SyncRepositoryError::StorageFailure)?
            .materialize_pending(scope)
    }

    pub fn list_outbox(
        &self,
        scope: &RoamingScope,
    ) -> Result<Vec<RoamingBoardEvent>, SyncRepositoryError> {
        self.repository
            .lock()
            .map_err(|_| SyncRepositoryError::StorageFailure)?
            .list_outbox(scope)
    }

    pub fn apply_remote_batch(
        &self,
        scope: &RoamingScope,
        events: &[RoamingBoardEvent],
    ) -> Result<SyncApplyReport, SyncRepositoryError> {
        self.repository
            .lock()
            .map_err(|_| SyncRepositoryError::StorageFailure)?
            .apply_remote_batch(scope, events)
    }
}

pub fn persist_board_capability_secret(
    vault: &VaultService,
    board_id: &str,
    board_key: &[u8],
) -> Result<(), VaultError> {
    if board_key.len() != 32 {
        return Err(VaultError::InvalidKey);
    }
    let key = SecretRecordKey::new(SecretKind::BoardCapability, board_id)?;
    vault
        .provider()
        .put(key, SecretValue::new(board_key.to_vec())?)
}

pub fn load_board_capability_secret(
    vault: &VaultService,
    board_id: &str,
) -> Result<Option<SecretValue>, VaultError> {
    let key = SecretRecordKey::new(SecretKind::BoardCapability, board_id)?;
    vault.provider().get(&key)
}

impl From<SyncCoreError> for SyncRepositoryError {
    fn from(_: SyncCoreError) -> Self {
        Self::InvalidEvent
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::vault::SessionVault;

    #[test]
    fn a10_board_key_only_crosses_existing_typed_vault_boundary() {
        let vault = VaultService::from_provider(SessionVault::default());
        let board_key = [7_u8; 32];
        persist_board_capability_secret(&vault, "board-a", &board_key).unwrap();
        let loaded = load_board_capability_secret(&vault, "board-a")
            .unwrap()
            .unwrap();
        assert_eq!(loaded.expose(), &board_key);
    }

    #[test]
    fn a10_invalid_board_key_is_not_persisted() {
        let vault = VaultService::from_provider(SessionVault::default());
        assert_eq!(
            persist_board_capability_secret(&vault, "board-a", &[1, 2, 3]),
            Err(VaultError::InvalidKey)
        );
    }
}
