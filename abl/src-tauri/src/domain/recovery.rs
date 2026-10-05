use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const BACKUP_MANIFEST_FORMAT: &str = "p2pkanban-profile-backup";
pub const BACKUP_MANIFEST_VERSION: u32 = 1;
pub const RECOVERY_LOGICAL_EXPORT_FORMAT: &str = "p2pkanban-recovery-logical";
pub const RECOVERY_LOGICAL_EXPORT_VERSION: u32 = 1;
pub const MAX_BACKUP_ID_BYTES: usize = 128;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum DoctorLevel {
    Ok,
    Warning,
    Error,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DoctorCheck {
    pub id: String,
    pub level: DoctorLevel,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DoctorReport {
    pub format_version: u32,
    pub profile_database: String,
    pub profile_exists: bool,
    pub safe_mode_required: bool,
    pub schema_version: Option<u32>,
    pub min_reader: Option<u32>,
    pub min_writer: Option<u32>,
    pub migration_journal_state: Option<String>,
    pub restore_point_count: usize,
    pub checks: Vec<DoctorCheck>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct BackupCounts {
    pub workspaces: Option<u64>,
    pub boards: Option<u64>,
    pub cards: Option<u64>,
    pub pending_local_changes: Option<u64>,
    pub sync_outbox: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BackupManifest {
    pub format: String,
    pub format_version: u32,
    pub backup_id: String,
    pub created_at_unix_ms: i64,
    pub reason: String,
    pub app_version: String,
    pub schema_version: u32,
    pub min_reader: Option<u32>,
    pub min_writer: Option<u32>,
    pub database_sha256: String,
    pub database_bytes: u64,
    pub integrity_check: String,
    pub foreign_key_violations: u64,
    pub counts: BackupCounts,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BackupSummary {
    pub backup_id: String,
    pub created_at_unix_ms: Option<i64>,
    pub reason: Option<String>,
    pub schema_version: Option<u32>,
    pub database_bytes: Option<u64>,
    pub verified: bool,
    pub verification_error: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RestoreReport {
    pub backup_id: String,
    pub restored_schema_version: u32,
    pub quarantine_path: Option<String>,
    pub post_restore_integrity: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecoveryLogicalExport {
    pub format: String,
    pub format_version: u32,
    pub created_at_unix_ms: i64,
    pub app_version: String,
    pub schema_version: u32,
    pub source_database_sha256: String,
    pub tables: BTreeMap<String, Vec<BTreeMap<String, Value>>>,
    pub omitted_operational_state: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LogicalExportReport {
    pub path: String,
    pub bytes: u64,
    pub sha256: String,
    pub schema_version: u32,
    pub table_count: usize,
    pub row_count: usize,
}

pub fn valid_backup_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_BACKUP_ID_BYTES
        && !value.starts_with('.')
        && !value.contains("..")
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a16_backup_ids_are_bounded_and_path_safe() {
        assert!(valid_backup_id("manual-1700000000000"));
        assert!(valid_backup_id("pre-migration-v5"));
        for invalid in ["", "../profile", "a/b", "a\\b", ".hidden", "two..dots", "white space"] {
            assert!(!valid_backup_id(invalid), "unexpectedly accepted {invalid:?}");
        }
        assert!(!valid_backup_id(&"a".repeat(MAX_BACKUP_ID_BYTES + 1)));
    }
}
