use std::path::Path;

use crate::domain::recovery::{
    BackupManifest, BackupSummary, DoctorReport, LogicalExportReport, RestoreReport,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RecoveryError {
    Io,
    Database,
    ProfileMissing,
    InvalidBackupId,
    BackupNotFound,
    InvalidManifest,
    HashMismatch,
    IntegrityFailed,
    ExportDestinationExists,
    UnsupportedSchema { found: u32, max_supported: u32 },
}

pub trait RecoveryBackend: Send + Sync {
    fn doctor(&self) -> Result<DoctorReport, RecoveryError>;
    fn create_manual_backup(&self) -> Result<BackupManifest, RecoveryError>;
    fn create_pre_migration_backup(&self) -> Result<Option<BackupManifest>, RecoveryError>;
    fn list_backups(&self) -> Result<Vec<BackupSummary>, RecoveryError>;
    fn export_logical(&self, destination: &Path, overwrite: bool) -> Result<LogicalExportReport, RecoveryError>;
    fn restore(&self, backup_id: &str) -> Result<RestoreReport, RecoveryError>;
}

pub struct RecoveryService {
    backend: Box<dyn RecoveryBackend>,
}

impl RecoveryService {
    pub fn new(backend: Box<dyn RecoveryBackend>) -> Self {
        Self { backend }
    }

    pub fn doctor(&self) -> Result<DoctorReport, RecoveryError> {
        self.backend.doctor()
    }

    pub fn create_manual_backup(&self) -> Result<BackupManifest, RecoveryError> {
        self.backend.create_manual_backup()
    }

    pub fn create_pre_migration_backup(&self) -> Result<Option<BackupManifest>, RecoveryError> {
        self.backend.create_pre_migration_backup()
    }

    pub fn list_backups(&self) -> Result<Vec<BackupSummary>, RecoveryError> {
        self.backend.list_backups()
    }

    pub fn export_logical(
        &self,
        destination: &Path,
        overwrite: bool,
    ) -> Result<LogicalExportReport, RecoveryError> {
        self.backend.export_logical(destination, overwrite)
    }

    pub fn restore(&self, backup_id: &str) -> Result<RestoreReport, RecoveryError> {
        self.backend.restore(backup_id)
    }
}
