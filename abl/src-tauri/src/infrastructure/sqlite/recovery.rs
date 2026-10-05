use std::{
    collections::BTreeMap,
    fs,
    io::{Read, Write},
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
use rusqlite::{types::ValueRef, Connection, OpenFlags, OptionalExtension};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::{
    application::recovery::{RecoveryBackend, RecoveryError},
    domain::recovery::{
        valid_backup_id, BackupCounts, BackupManifest, BackupSummary, DoctorCheck, DoctorLevel,
        DoctorReport, LogicalExportReport, RecoveryLogicalExport, RestoreReport,
        BACKUP_MANIFEST_FORMAT, BACKUP_MANIFEST_VERSION, RECOVERY_LOGICAL_EXPORT_FORMAT,
        RECOVERY_LOGICAL_EXPORT_VERSION,
    },
    infrastructure::profile::{create_private_dir, write_private_file, ProfileStoragePaths},
};

use super::migration::{
    CURRENT_SCHEMA_VERSION, MIGRATION_V0_TO_V1_ID, MIGRATION_V0_TO_V1_SHA256,
    MIGRATION_V1_TO_V2_ID, MIGRATION_V1_TO_V2_SHA256, MIGRATION_V2_TO_V3_ID,
    MIGRATION_V2_TO_V3_SHA256, MIGRATION_V3_TO_V4_ID, MIGRATION_V3_TO_V4_SHA256,
    MIGRATION_V4_TO_V5_ID, MIGRATION_V4_TO_V5_SHA256, MIGRATION_V5_TO_V6_ID,
    MIGRATION_V5_TO_V6_SHA256, MIN_READER_SCHEMA_VERSION, MIN_WRITER_SCHEMA_VERSION,
};

const DOCTOR_FORMAT_VERSION: u32 = 1;
const RECOVERY_LOGICAL_TABLES: &[&str] = &[
    "workspaces",
    "boards",
    "columns",
    "cards",
    "checklists",
    "checklist_items",
    "card_tombstones",
    "checklist_tombstones",
    "checklist_item_tombstones",
    "labels",
    "card_labels",
    "comments",
    "board_appearance_settings",
    "activity_entries",
    "sync_entity_extensions",
];
const OMITTED_OPERATIONAL_STATE: &[&str] = &[
    "profile_meta",
    "schema_migrations",
    "local_mutation_state",
    "pending_local_changes",
    "sync_outbox",
    "sync_seen_events",
    "sync_field_versions",
    "profile_principal",
    "import_receipts",
    "imported_capability_metadata",
    "import_opaque_sections",
    "parity_local_changes",
];

#[derive(Debug, Clone, PartialEq, Eq)]
struct DatabaseHealth {
    schema_version: u32,
    min_reader: Option<u32>,
    min_writer: Option<u32>,
    integrity: String,
    foreign_key_violations: u64,
    counts: BackupCounts,
}

pub struct SqliteRecoveryBackend {
    layout: ProfileStoragePaths,
}

impl SqliteRecoveryBackend {
    pub fn new(layout: ProfileStoragePaths) -> Self {
        Self { layout }
    }

    pub fn layout(&self) -> &ProfileStoragePaths {
        &self.layout
    }
}

fn epoch_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(i64::MAX as u128) as i64)
        .unwrap_or(0)
}

fn open_read_only(path: &Path) -> Result<Connection, RecoveryError> {
    Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|_| RecoveryError::Database)
}

fn table_exists(conn: &Connection, table: &str) -> Result<bool, RecoveryError> {
    conn.query_row(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1",
        [table],
        |_| Ok(()),
    )
    .optional()
    .map(|row| row.is_some())
    .map_err(|_| RecoveryError::Database)
}

fn count_if_present(conn: &Connection, table: &str) -> Result<Option<u64>, RecoveryError> {
    if !table_exists(conn, table)? {
        return Ok(None);
    }
    let sql = format!("SELECT COUNT(*) FROM \"{table}\"");
    let count: i64 = conn
        .query_row(&sql, [], |row| row.get(0))
        .map_err(|_| RecoveryError::Database)?;
    u64::try_from(count)
        .map(Some)
        .map_err(|_| RecoveryError::Database)
}

fn profile_meta(conn: &Connection) -> Result<(Option<u32>, Option<u32>, Option<u32>), RecoveryError> {
    if !table_exists(conn, "profile_meta")? {
        return Ok((None, None, None));
    }
    let row = conn
        .query_row(
            "SELECT schema_version, min_reader, min_writer FROM profile_meta WHERE singleton=1",
            [],
            |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            },
        )
        .optional()
        .map_err(|_| RecoveryError::Database)?;
    let Some((schema, reader, writer)) = row else {
        return Ok((None, None, None));
    };
    Ok((
        Some(u32::try_from(schema).map_err(|_| RecoveryError::IntegrityFailed)?),
        Some(u32::try_from(reader).map_err(|_| RecoveryError::IntegrityFailed)?),
        Some(u32::try_from(writer).map_err(|_| RecoveryError::IntegrityFailed)?),
    ))
}

fn verify_migration_line_for_schema(conn: &Connection, schema_version: u32) -> Result<(), RecoveryError> {
    let expected = [
        (MIGRATION_V0_TO_V1_ID, MIGRATION_V0_TO_V1_SHA256),
        (MIGRATION_V1_TO_V2_ID, MIGRATION_V1_TO_V2_SHA256),
        (MIGRATION_V2_TO_V3_ID, MIGRATION_V2_TO_V3_SHA256),
        (MIGRATION_V3_TO_V4_ID, MIGRATION_V3_TO_V4_SHA256),
        (MIGRATION_V4_TO_V5_ID, MIGRATION_V4_TO_V5_SHA256),
        (MIGRATION_V5_TO_V6_ID, MIGRATION_V5_TO_V6_SHA256),
    ];
    let expected_len = usize::try_from(schema_version).map_err(|_| RecoveryError::IntegrityFailed)?;
    if expected_len > expected.len() {
        return Ok(());
    }
    if schema_version == 0 && !table_exists(conn, "schema_migrations")? {
        return Ok(());
    }
    if !table_exists(conn, "schema_migrations")? {
        return Err(RecoveryError::IntegrityFailed);
    }
    let mut statement = conn
        .prepare("SELECT id, checksum FROM schema_migrations ORDER BY id")
        .map_err(|_| RecoveryError::Database)?;
    let observed = statement
        .query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)))
        .map_err(|_| RecoveryError::Database)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| RecoveryError::Database)?;
    let expected = expected[..expected_len]
        .iter()
        .map(|(id, checksum)| ((*id).to_owned(), (*checksum).to_owned()))
        .collect::<Vec<_>>();
    if observed != expected {
        return Err(RecoveryError::IntegrityFailed);
    }
    Ok(())
}

fn inspect_database(path: &Path) -> Result<DatabaseHealth, RecoveryError> {
    let conn = open_read_only(path)?;
    let schema: i64 = conn
        .query_row("PRAGMA user_version", [], |row| row.get(0))
        .map_err(|_| RecoveryError::Database)?;
    let schema_version = u32::try_from(schema).map_err(|_| RecoveryError::Database)?;

    let integrity: String = conn
        .query_row("PRAGMA integrity_check", [], |row| row.get(0))
        .map_err(|_| RecoveryError::IntegrityFailed)?;
    if integrity != "ok" {
        return Err(RecoveryError::IntegrityFailed);
    }
    let foreign_key_violations: i64 = conn
        .query_row("SELECT COUNT(*) FROM pragma_foreign_key_check", [], |row| row.get(0))
        .map_err(|_| RecoveryError::IntegrityFailed)?;
    if foreign_key_violations != 0 {
        return Err(RecoveryError::IntegrityFailed);
    }

    let (profile_schema, min_reader, min_writer) = profile_meta(&conn)?;
    if schema_version == 0 {
        if profile_schema.is_some() || min_reader.is_some() || min_writer.is_some() {
            return Err(RecoveryError::IntegrityFailed);
        }
    } else if profile_schema != Some(schema_version) || min_reader.is_none() || min_writer.is_none() {
        return Err(RecoveryError::IntegrityFailed);
    }
    verify_migration_line_for_schema(&conn, schema_version)?;
    Ok(DatabaseHealth {
        schema_version,
        min_reader,
        min_writer,
        integrity,
        foreign_key_violations: u64::try_from(foreign_key_violations).map_err(|_| RecoveryError::IntegrityFailed)?,
        counts: BackupCounts {
            workspaces: count_if_present(&conn, "workspaces")?,
            boards: count_if_present(&conn, "boards")?,
            cards: count_if_present(&conn, "cards")?,
            pending_local_changes: count_if_present(&conn, "pending_local_changes")?,
            sync_outbox: count_if_present(&conn, "sync_outbox")?,
        },
    })
}

fn sha256_file(path: &Path) -> Result<String, RecoveryError> {
    let mut file = fs::File::open(path).map_err(|_| RecoveryError::Io)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer).map_err(|_| RecoveryError::Io)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let digest = hasher.finalize();
    Ok(digest.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn sha256_bytes(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn quote_identifier(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}

fn json_value(value: ValueRef<'_>) -> Result<serde_json::Value, RecoveryError> {
    Ok(match value {
        ValueRef::Null => serde_json::Value::Null,
        ValueRef::Integer(value) => serde_json::Value::Number(value.into()),
        ValueRef::Real(value) => serde_json::Number::from_f64(value)
            .map(serde_json::Value::Number)
            .ok_or(RecoveryError::Database)?,
        ValueRef::Text(value) => match std::str::from_utf8(value) {
            Ok(value) => serde_json::Value::String(value.to_owned()),
            Err(_) => serde_json::json!({"$sqliteTextBase64": BASE64_STANDARD.encode(value)}),
        },
        ValueRef::Blob(value) => serde_json::json!({"$sqliteBlobBase64": BASE64_STANDARD.encode(value)}),
    })
}

fn export_table(
    conn: &Connection,
    table: &str,
) -> Result<Option<Vec<BTreeMap<String, serde_json::Value>>>, RecoveryError> {
    if !table_exists(conn, table)? {
        return Ok(None);
    }
    let pragma = format!("PRAGMA table_info({})", quote_identifier(table));
    let mut pragma_statement = conn.prepare(&pragma).map_err(|_| RecoveryError::Database)?;
    let columns = pragma_statement
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(|_| RecoveryError::Database)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| RecoveryError::Database)?;
    if columns.is_empty() {
        return Ok(Some(Vec::new()));
    }
    let order = columns
        .iter()
        .map(|column| quote_identifier(column))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!("SELECT * FROM {} ORDER BY {order}", quote_identifier(table));
    let mut statement = conn.prepare(&sql).map_err(|_| RecoveryError::Database)?;
    let mut query = statement.query([]).map_err(|_| RecoveryError::Database)?;
    let mut exported = Vec::new();
    while let Some(row) = query.next().map_err(|_| RecoveryError::Database)? {
        let mut item = BTreeMap::new();
        for (index, column) in columns.iter().enumerate() {
            item.insert(
                column.clone(),
                json_value(row.get_ref(index).map_err(|_| RecoveryError::Database)?)?,
            );
        }
        exported.push(item);
    }
    Ok(Some(exported))
}

fn build_logical_export(layout: &ProfileStoragePaths) -> Result<RecoveryLogicalExport, RecoveryError> {
    let metadata = fs::symlink_metadata(layout.database()).map_err(|error| match error.kind() {
        std::io::ErrorKind::NotFound => RecoveryError::ProfileMissing,
        _ => RecoveryError::Io,
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(RecoveryError::IntegrityFailed);
    }
    let health = inspect_database(layout.database())?;
    let conn = open_read_only(layout.database())?;
    let mut tables = BTreeMap::new();
    for table in RECOVERY_LOGICAL_TABLES {
        if let Some(rows) = export_table(&conn, table)? {
            tables.insert((*table).to_owned(), rows);
        }
    }
    Ok(RecoveryLogicalExport {
        format: RECOVERY_LOGICAL_EXPORT_FORMAT.to_owned(),
        format_version: RECOVERY_LOGICAL_EXPORT_VERSION,
        created_at_unix_ms: epoch_millis(),
        app_version: env!("CARGO_PKG_VERSION").to_owned(),
        schema_version: health.schema_version,
        source_database_sha256: sha256_file(layout.database())?,
        tables,
        omitted_operational_state: OMITTED_OPERATIONAL_STATE
            .iter()
            .map(|value| (*value).to_owned())
            .collect(),
    })
}

fn write_logical_export(
    layout: &ProfileStoragePaths,
    destination: &Path,
    overwrite: bool,
) -> Result<LogicalExportReport, RecoveryError> {
    let export = build_logical_export(layout)?;
    let mut bytes = serde_json::to_vec_pretty(&export).map_err(|_| RecoveryError::Database)?;
    bytes.push(b'\n');
    let mut options = fs::OpenOptions::new();
    options.write(true).mode(0o600).custom_flags(libc::O_NOFOLLOW);
    if overwrite {
        options.create(true).truncate(true);
    } else {
        options.create_new(true);
    }
    let mut file = options.open(destination).map_err(|error| {
        if error.kind() == std::io::ErrorKind::AlreadyExists {
            RecoveryError::ExportDestinationExists
        } else {
            RecoveryError::Io
        }
    })?;
    file.write_all(&bytes).map_err(|_| RecoveryError::Io)?;
    file.sync_all().map_err(|_| RecoveryError::Io)?;
    fs::set_permissions(destination, fs::Permissions::from_mode(0o600)).map_err(|_| RecoveryError::Io)?;
    let row_count = export.tables.values().map(Vec::len).sum();
    Ok(LogicalExportReport {
        path: destination.to_string_lossy().into_owned(),
        bytes: u64::try_from(bytes.len()).map_err(|_| RecoveryError::Io)?,
        sha256: sha256_bytes(&bytes),
        schema_version: export.schema_version,
        table_count: export.tables.len(),
        row_count,
    })
}

fn backup_id_from_database_path(path: &Path) -> Result<String, RecoveryError> {
    let file = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(RecoveryError::InvalidBackupId)?;
    let backup_id = file
        .strip_suffix(".sqlite")
        .ok_or(RecoveryError::InvalidBackupId)?;
    if !valid_backup_id(backup_id) {
        return Err(RecoveryError::InvalidBackupId);
    }
    Ok(backup_id.to_owned())
}

fn database_path(layout: &ProfileStoragePaths, backup_id: &str) -> Result<PathBuf, RecoveryError> {
    if !valid_backup_id(backup_id) {
        return Err(RecoveryError::InvalidBackupId);
    }
    Ok(layout.backups().join(format!("{backup_id}.sqlite")))
}

fn manifest_path(layout: &ProfileStoragePaths, backup_id: &str) -> Result<PathBuf, RecoveryError> {
    if !valid_backup_id(backup_id) {
        return Err(RecoveryError::InvalidBackupId);
    }
    Ok(layout.backups().join(format!("{backup_id}.manifest.json")))
}

fn fsync_dir(path: &Path) -> Result<(), RecoveryError> {
    fs::File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|_| RecoveryError::Io)
}

fn write_manifest_atomic(layout: &ProfileStoragePaths, manifest: &BackupManifest) -> Result<(), RecoveryError> {
    let final_path = manifest_path(layout, &manifest.backup_id)?;
    let temporary = layout
        .backups()
        .join(format!(".{}.manifest.{}.tmp", manifest.backup_id, std::process::id()));
    let bytes = serde_json::to_vec_pretty(manifest).map_err(|_| RecoveryError::InvalidManifest)?;
    let mut with_newline = bytes;
    with_newline.push(b'\n');
    write_private_file(&temporary, &with_newline).map_err(|_| RecoveryError::Io)?;
    fs::rename(&temporary, &final_path).map_err(|_| RecoveryError::Io)?;
    fsync_dir(layout.backups())
}

fn finalize_existing_snapshot(
    layout: &ProfileStoragePaths,
    path: &Path,
    reason: &str,
    app_version: &str,
) -> Result<BackupManifest, RecoveryError> {
    let backup_id = backup_id_from_database_path(path)?;
    let health = inspect_database(path)?;
    let metadata = fs::metadata(path).map_err(|_| RecoveryError::Io)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).map_err(|_| RecoveryError::Io)?;
    let manifest = BackupManifest {
        format: BACKUP_MANIFEST_FORMAT.to_owned(),
        format_version: BACKUP_MANIFEST_VERSION,
        backup_id,
        created_at_unix_ms: epoch_millis(),
        reason: reason.to_owned(),
        app_version: app_version.to_owned(),
        schema_version: health.schema_version,
        min_reader: health.min_reader,
        min_writer: health.min_writer,
        database_sha256: sha256_file(path)?,
        database_bytes: metadata.len(),
        integrity_check: health.integrity,
        foreign_key_violations: health.foreign_key_violations,
        counts: health.counts,
    };
    write_manifest_atomic(layout, &manifest)?;
    Ok(manifest)
}

fn create_snapshot(
    layout: &ProfileStoragePaths,
    source: &Connection,
    backup_id: &str,
    reason: &str,
) -> Result<BackupManifest, RecoveryError> {
    if !valid_backup_id(backup_id) {
        return Err(RecoveryError::InvalidBackupId);
    }
    layout.prepare().map_err(|_| RecoveryError::Io)?;
    let final_database = database_path(layout, backup_id)?;
    let temporary = layout
        .backups()
        .join(format!(".{backup_id}.{}.sqlite.tmp", std::process::id()));
    let _ = fs::remove_file(&temporary);
    source
        .backup("main", &temporary, None)
        .map_err(|_| RecoveryError::Database)?;
    fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600)).map_err(|_| RecoveryError::Io)?;
    inspect_database(&temporary)?;
    fs::rename(&temporary, &final_database).map_err(|_| RecoveryError::Io)?;
    fsync_dir(layout.backups())?;
    match finalize_existing_snapshot(layout, &final_database, reason, env!("CARGO_PKG_VERSION")) {
        Ok(manifest) => Ok(manifest),
        Err(error) => {
            let _ = fs::remove_file(&final_database);
            Err(error)
        }
    }
}

fn read_manifest(layout: &ProfileStoragePaths, backup_id: &str) -> Result<BackupManifest, RecoveryError> {
    let path = manifest_path(layout, backup_id)?;
    let metadata = fs::symlink_metadata(&path).map_err(|error| match error.kind() {
        std::io::ErrorKind::NotFound => RecoveryError::BackupNotFound,
        _ => RecoveryError::Io,
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(RecoveryError::InvalidManifest);
    }
    let bytes = fs::read(path).map_err(|_| RecoveryError::Io)?;
    let manifest: BackupManifest = serde_json::from_slice(&bytes).map_err(|_| RecoveryError::InvalidManifest)?;
    if manifest.format != BACKUP_MANIFEST_FORMAT
        || manifest.format_version != BACKUP_MANIFEST_VERSION
        || manifest.backup_id != backup_id
        || !valid_backup_id(&manifest.backup_id)
        || manifest.created_at_unix_ms < 0
        || manifest.reason.is_empty()
        || manifest.app_version.is_empty()
        || manifest.database_sha256.len() != 64
        || !manifest.database_sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
        || manifest.integrity_check != "ok"
        || manifest.foreign_key_violations != 0
    {
        return Err(RecoveryError::InvalidManifest);
    }
    Ok(manifest)
}

fn verify_restore_point(
    layout: &ProfileStoragePaths,
    backup_id: &str,
) -> Result<BackupManifest, RecoveryError> {
    let manifest = read_manifest(layout, backup_id)?;
    let database = database_path(layout, backup_id)?;
    let metadata = fs::symlink_metadata(&database).map_err(|error| match error.kind() {
        std::io::ErrorKind::NotFound => RecoveryError::BackupNotFound,
        _ => RecoveryError::Io,
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() != manifest.database_bytes {
        return Err(RecoveryError::HashMismatch);
    }
    if sha256_file(&database)? != manifest.database_sha256 {
        return Err(RecoveryError::HashMismatch);
    }
    let health = inspect_database(&database)?;
    if health.schema_version != manifest.schema_version
        || health.min_reader != manifest.min_reader
        || health.min_writer != manifest.min_writer
        || health.counts != manifest.counts
        || health.integrity != "ok"
        || health.foreign_key_violations != 0
    {
        return Err(RecoveryError::IntegrityFailed);
    }
    if health.schema_version > CURRENT_SCHEMA_VERSION
        || health.min_reader.is_some_and(|value| value > CURRENT_SCHEMA_VERSION)
        || health.min_writer.is_some_and(|value| value > CURRENT_SCHEMA_VERSION)
    {
        return Err(RecoveryError::UnsupportedSchema {
            found: health.schema_version,
            max_supported: CURRENT_SCHEMA_VERSION,
        });
    }
    Ok(manifest)
}

fn backup_summary_from_error(backup_id: String, error: RecoveryError) -> BackupSummary {
    BackupSummary {
        backup_id,
        created_at_unix_ms: None,
        reason: None,
        schema_version: None,
        database_bytes: None,
        verified: false,
        verification_error: Some(format!("{error:?}")),
    }
}

fn list_backup_ids(layout: &ProfileStoragePaths) -> Result<Vec<String>, RecoveryError> {
    let mut ids = Vec::new();
    let entries = fs::read_dir(layout.backups()).map_err(|_| RecoveryError::Io)?;
    for entry in entries {
        let entry = entry.map_err(|_| RecoveryError::Io)?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        let Some(id) = name.strip_suffix(".manifest.json") else {
            continue;
        };
        if valid_backup_id(id) {
            ids.push(id.to_owned());
        }
    }
    ids.sort();
    ids.dedup();
    Ok(ids)
}

fn read_migration_journal_state(layout: &ProfileStoragePaths) -> Result<Option<String>, RecoveryError> {
    let metadata = match fs::symlink_metadata(layout.migration_journal()) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(RecoveryError::Io),
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(RecoveryError::InvalidManifest);
    }
    let bytes = fs::read(layout.migration_journal()).map_err(|_| RecoveryError::Io)?;
    let value: serde_json::Value = serde_json::from_slice(&bytes).map_err(|_| RecoveryError::InvalidManifest)?;
    value
        .get("state")
        .and_then(serde_json::Value::as_str)
        .map(|value| Some(value.to_owned()))
        .ok_or(RecoveryError::InvalidManifest)
}

fn check_private_file(path: &Path, id: &str, checks: &mut Vec<DoctorCheck>) -> bool {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return false,
        Err(_) => {
            checks.push(DoctorCheck {
                id: id.to_owned(),
                level: DoctorLevel::Error,
                message: "metadata unavailable".to_owned(),
            });
            return true;
        }
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        checks.push(DoctorCheck {
            id: id.to_owned(),
            level: DoctorLevel::Error,
            message: "sensitive profile path is not a regular file".to_owned(),
        });
        return true;
    }
    if metadata.permissions().mode() & 0o077 != 0 {
        checks.push(DoctorCheck {
            id: id.to_owned(),
            level: DoctorLevel::Error,
            message: "sensitive profile file is accessible by group/other".to_owned(),
        });
        return true;
    }
    checks.push(DoctorCheck {
        id: id.to_owned(),
        level: DoctorLevel::Ok,
        message: "private regular file".to_owned(),
    });
    false
}

fn doctor(layout: &ProfileStoragePaths) -> Result<DoctorReport, RecoveryError> {
    let mut checks = Vec::new();
    let mut safe_mode_required = false;
    let mut schema_version = None;
    let mut min_reader = None;
    let mut min_writer = None;
    let database = layout.database();
    let database_metadata = match fs::symlink_metadata(database) {
        Ok(metadata) => Some(metadata),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(_) => return Err(RecoveryError::Io),
    };
    let profile_exists = database_metadata.is_some();

    if let Some(metadata) = database_metadata {
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            checks.push(DoctorCheck {
                id: "profile-database-path".to_owned(),
                level: DoctorLevel::Error,
                message: "profile.db is not a regular file".to_owned(),
            });
            safe_mode_required = true;
        } else {
            if metadata.permissions().mode() & 0o077 != 0 {
                checks.push(DoctorCheck {
                    id: "profile-database-permissions".to_owned(),
                    level: DoctorLevel::Warning,
                    message: "profile.db permissions will be tightened to 0600 before writable open".to_owned(),
                });
            } else {
                checks.push(DoctorCheck {
                    id: "profile-database-permissions".to_owned(),
                    level: DoctorLevel::Ok,
                    message: "profile.db is user-private".to_owned(),
                });
            }
            match inspect_database(database) {
                Ok(health) => {
                    schema_version = Some(health.schema_version);
                    min_reader = health.min_reader;
                    min_writer = health.min_writer;
                    checks.push(DoctorCheck {
                        id: "sqlite-integrity".to_owned(),
                        level: DoctorLevel::Ok,
                        message: "PRAGMA integrity_check and foreign_key_check passed".to_owned(),
                    });
                    if health.schema_version > CURRENT_SCHEMA_VERSION
                        || health.min_reader.is_some_and(|value| value > CURRENT_SCHEMA_VERSION)
                        || health.min_writer.is_some_and(|value| value > CURRENT_SCHEMA_VERSION)
                    {
                        safe_mode_required = true;
                        checks.push(DoctorCheck {
                            id: "schema-compatibility".to_owned(),
                            level: DoctorLevel::Error,
                            message: format!(
                                "profile schema {} is not writable by this build (max {})",
                                health.schema_version, CURRENT_SCHEMA_VERSION
                            ),
                        });
                    } else if health.schema_version < CURRENT_SCHEMA_VERSION {
                        checks.push(DoctorCheck {
                            id: "schema-compatibility".to_owned(),
                            level: DoctorLevel::Warning,
                            message: format!(
                                "profile schema {} requires verified migration to {}",
                                health.schema_version, CURRENT_SCHEMA_VERSION
                            ),
                        });
                    } else if health.min_reader != Some(MIN_READER_SCHEMA_VERSION)
                        || health.min_writer != Some(MIN_WRITER_SCHEMA_VERSION)
                    {
                        safe_mode_required = true;
                        checks.push(DoctorCheck {
                            id: "schema-metadata".to_owned(),
                            level: DoctorLevel::Error,
                            message: "current-schema profile_meta reader/writer metadata is inconsistent".to_owned(),
                        });
                    } else {
                        checks.push(DoctorCheck {
                            id: "schema-compatibility".to_owned(),
                            level: DoctorLevel::Ok,
                            message: format!("schema {} is compatible", health.schema_version),
                        });
                    }
                }
                Err(error) => {
                    safe_mode_required = true;
                    checks.push(DoctorCheck {
                        id: "sqlite-integrity".to_owned(),
                        level: DoctorLevel::Error,
                        message: format!("profile database failed read-only verification: {error:?}"),
                    });
                }
            }
        }
    } else {
        checks.push(DoctorCheck {
            id: "profile-database".to_owned(),
            level: DoctorLevel::Ok,
            message: "no profile.db exists yet; first writable open may create a fresh profile".to_owned(),
        });
    }

    let migration_journal_state = match read_migration_journal_state(layout) {
        Ok(state) => state,
        Err(error) => {
            safe_mode_required = true;
            checks.push(DoctorCheck {
                id: "migration-journal".to_owned(),
                level: DoctorLevel::Error,
                message: format!("migration journal is unreadable: {error:?}"),
            });
            Some("invalid".to_owned())
        }
    };
    match migration_journal_state.as_deref() {
        None => checks.push(DoctorCheck {
            id: "migration-journal".to_owned(),
            level: DoctorLevel::Ok,
            message: "no interrupted migration journal".to_owned(),
        }),
        Some("completed") => checks.push(DoctorCheck {
            id: "migration-journal".to_owned(),
            level: DoctorLevel::Warning,
            message: "stale completed migration journal should be reviewed".to_owned(),
        }),
        Some(state) => {
            safe_mode_required = true;
            checks.push(DoctorCheck {
                id: "migration-journal".to_owned(),
                level: DoctorLevel::Error,
                message: format!("migration journal state {state:?} requires explicit recovery"),
            });
        }
    }

    safe_mode_required |= check_private_file(layout.encrypted_vault(), "encrypted-vault", &mut checks);
    safe_mode_required |= check_private_file(layout.passphrase_root_wrap(), "passphrase-root-wrap", &mut checks);
    safe_mode_required |= check_private_file(layout.migration_journal(), "migration-journal-permissions", &mut checks);

    let restore_point_count = list_backup_ids(layout)?.len();
    checks.push(DoctorCheck {
        id: "restore-points".to_owned(),
        level: if restore_point_count == 0 { DoctorLevel::Warning } else { DoctorLevel::Ok },
        message: format!("{restore_point_count} backup manifest(s) present; use backups to verify them"),
    });

    Ok(DoctorReport {
        format_version: DOCTOR_FORMAT_VERSION,
        profile_database: database.to_string_lossy().into_owned(),
        profile_exists,
        safe_mode_required,
        schema_version,
        min_reader,
        min_writer,
        migration_journal_state,
        restore_point_count,
        checks,
    })
}

fn quarantine_current_profile(layout: &ProfileStoragePaths) -> Result<Option<PathBuf>, RecoveryError> {
    let mut existing = Vec::new();
    for path in [
        layout.database().to_path_buf(),
        PathBuf::from(format!("{}-wal", layout.database().to_string_lossy())),
        PathBuf::from(format!("{}-shm", layout.database().to_string_lossy())),
        layout.migration_journal().to_path_buf(),
    ] {
        if fs::symlink_metadata(&path).is_ok() {
            existing.push(path);
        }
    }
    if existing.is_empty() {
        return Ok(None);
    }
    let quarantine = layout
        .backups()
        .join(format!("quarantine-{}-{}", epoch_millis(), Uuid::new_v4()));
    create_private_dir(&quarantine).map_err(|_| RecoveryError::Io)?;
    let mut moved: Vec<(PathBuf, PathBuf)> = Vec::new();
    for path in existing {
        let name = path.file_name().ok_or(RecoveryError::Io)?;
        let destination = quarantine.join(name);
        if fs::rename(&path, &destination).is_err() {
            for (original, quarantined) in moved.iter().rev() {
                let _ = fs::rename(quarantined, original);
            }
            let _ = fs::remove_dir(&quarantine);
            return Err(RecoveryError::Io);
        }
        moved.push((path, destination));
    }
    let sync_result = fsync_dir(layout.root()).and_then(|_| fsync_dir(layout.backups()));
    if let Err(error) = sync_result {
        let mut rollback_failed = false;
        for (original, quarantined) in moved.iter().rev() {
            if fs::rename(quarantined, original).is_err() {
                rollback_failed = true;
            }
        }
        let _ = fsync_dir(layout.root());
        let _ = fsync_dir(layout.backups());
        if !rollback_failed {
            let _ = fs::remove_dir(&quarantine);
        }
        return Err(error);
    }
    Ok(Some(quarantine))
}

fn try_pre_restore_backup(layout: &ProfileStoragePaths) -> Result<Option<BackupManifest>, RecoveryError> {
    let regular = fs::symlink_metadata(layout.database())
        .map(|metadata| metadata.is_file() && !metadata.file_type().is_symlink())
        .unwrap_or(false);
    if !regular || inspect_database(layout.database()).is_err() {
        return Ok(None);
    }
    let source = open_read_only(layout.database())?;
    let id = format!("pre-restore-{}-{}", epoch_millis(), Uuid::new_v4());
    create_snapshot(layout, &source, &id, "pre-restore")
        .map(Some)
}

fn rollback_quarantine(
    layout: &ProfileStoragePaths,
    quarantine: Option<&Path>,
    preserve_failed_restore: bool,
) -> Result<(), RecoveryError> {
    if preserve_failed_restore {
        if fs::symlink_metadata(layout.database()).is_ok() {
            if let Some(quarantine) = quarantine {
                let failed = quarantine.join("failed-restored-profile.db");
                fs::rename(layout.database(), failed).map_err(|_| RecoveryError::Io)?;
            } else {
                fs::remove_file(layout.database()).map_err(|_| RecoveryError::Io)?;
            }
        }
    }
    let Some(quarantine) = quarantine else {
        fsync_dir(layout.root())?;
        return Ok(());
    };
    for (name, original) in [
        ("profile.db", layout.database().to_path_buf()),
        (
            "profile.db-wal",
            PathBuf::from(format!("{}-wal", layout.database().to_string_lossy())),
        ),
        (
            "profile.db-shm",
            PathBuf::from(format!("{}-shm", layout.database().to_string_lossy())),
        ),
        ("migration-journal.json", layout.migration_journal().to_path_buf()),
    ] {
        let quarantined = quarantine.join(name);
        if fs::symlink_metadata(&quarantined).is_ok() {
            fs::rename(quarantined, original).map_err(|_| RecoveryError::Io)?;
        }
    }
    fsync_dir(layout.root())?;
    fsync_dir(layout.backups())?;
    Ok(())
}

impl RecoveryBackend for SqliteRecoveryBackend {
    fn doctor(&self) -> Result<DoctorReport, RecoveryError> {
        doctor(&self.layout)
    }

    fn create_manual_backup(&self) -> Result<BackupManifest, RecoveryError> {
        let metadata = fs::symlink_metadata(self.layout.database()).map_err(|error| match error.kind() {
            std::io::ErrorKind::NotFound => RecoveryError::ProfileMissing,
            _ => RecoveryError::Io,
        })?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(RecoveryError::ProfileMissing);
        }
        let report = doctor(&self.layout)?;
        if report.safe_mode_required {
            return Err(RecoveryError::IntegrityFailed);
        }
        let source = open_read_only(self.layout.database())?;
        let backup_id = format!("manual-{}-{}", epoch_millis(), Uuid::new_v4());
        create_snapshot(&self.layout, &source, &backup_id, "manual")
    }

    fn create_pre_migration_backup(&self) -> Result<Option<BackupManifest>, RecoveryError> {
        let metadata = match fs::symlink_metadata(self.layout.database()) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(RecoveryError::Io),
        };
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(RecoveryError::IntegrityFailed);
        }
        let health = inspect_database(self.layout.database())?;
        if health.schema_version >= CURRENT_SCHEMA_VERSION {
            return Ok(None);
        }
        let source = open_read_only(self.layout.database())?;
        let backup_id = format!(
            "pre-migration-v{}-to-v{}-{}",
            health.schema_version,
            CURRENT_SCHEMA_VERSION,
            Uuid::new_v4()
        );
        create_snapshot(
            &self.layout,
            &source,
            &backup_id,
            &format!(
                "pre-migration-v{}-to-v{}",
                health.schema_version, CURRENT_SCHEMA_VERSION
            ),
        )
        .map(Some)
    }

    fn list_backups(&self) -> Result<Vec<BackupSummary>, RecoveryError> {
        let mut summaries = Vec::new();
        for backup_id in list_backup_ids(&self.layout)? {
            match verify_restore_point(&self.layout, &backup_id) {
                Ok(manifest) => summaries.push(BackupSummary {
                    backup_id: manifest.backup_id,
                    created_at_unix_ms: Some(manifest.created_at_unix_ms),
                    reason: Some(manifest.reason),
                    schema_version: Some(manifest.schema_version),
                    database_bytes: Some(manifest.database_bytes),
                    verified: true,
                    verification_error: None,
                }),
                Err(error) => summaries.push(backup_summary_from_error(backup_id, error)),
            }
        }
        summaries.sort_by(|left, right| {
            right
                .created_at_unix_ms
                .unwrap_or(i64::MIN)
                .cmp(&left.created_at_unix_ms.unwrap_or(i64::MIN))
                .then_with(|| left.backup_id.cmp(&right.backup_id))
        });
        Ok(summaries)
    }

    fn export_logical(
        &self,
        destination: &Path,
        overwrite: bool,
    ) -> Result<LogicalExportReport, RecoveryError> {
        write_logical_export(&self.layout, destination, overwrite)
    }

    fn restore(&self, backup_id: &str) -> Result<RestoreReport, RecoveryError> {
        let manifest = verify_restore_point(&self.layout, backup_id)?;
        self.layout.prepare().map_err(|_| RecoveryError::Io)?;
        let source = database_path(&self.layout, backup_id)?;
        let temporary = self
            .layout
            .root()
            .join(format!(".restore-{}-{}.sqlite.tmp", epoch_millis(), Uuid::new_v4()));
        let _ = fs::remove_file(&temporary);
        fs::copy(&source, &temporary).map_err(|_| RecoveryError::Io)?;
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600)).map_err(|_| RecoveryError::Io)?;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .open(&temporary)
            .map_err(|_| RecoveryError::Io)?;
        file.flush().map_err(|_| RecoveryError::Io)?;
        file.sync_all().map_err(|_| RecoveryError::Io)?;
        drop(file);
        let temporary_health = inspect_database(&temporary)?;
        if sha256_file(&temporary)? != manifest.database_sha256 {
            let _ = fs::remove_file(&temporary);
            return Err(RecoveryError::HashMismatch);
        }

        let _ = try_pre_restore_backup(&self.layout)?;
        let quarantine = quarantine_current_profile(&self.layout)?;
        if let Err(error) = fs::rename(&temporary, self.layout.database()) {
            let _ = fs::remove_file(&temporary);
            rollback_quarantine(&self.layout, quarantine.as_deref(), false)?;
            return Err(match error.kind() {
                std::io::ErrorKind::NotFound => RecoveryError::ProfileMissing,
                _ => RecoveryError::Io,
            });
        }
        let post_restore = (|| -> Result<DatabaseHealth, RecoveryError> {
            fs::set_permissions(self.layout.database(), fs::Permissions::from_mode(0o600))
                .map_err(|_| RecoveryError::Io)?;
            fsync_dir(self.layout.root())?;
            let restored = inspect_database(self.layout.database())?;
            if restored.schema_version != temporary_health.schema_version
                || sha256_file(self.layout.database())? != manifest.database_sha256
            {
                return Err(RecoveryError::IntegrityFailed);
            }
            Ok(restored)
        })();
        let restored = match post_restore {
            Ok(restored) => restored,
            Err(error) => {
                rollback_quarantine(&self.layout, quarantine.as_deref(), true)?;
                return Err(error);
            }
        };

        Ok(RestoreReport {
            backup_id: backup_id.to_owned(),
            restored_schema_version: restored.schema_version,
            quarantine_path: quarantine.map(|path| path.to_string_lossy().into_owned()),
            post_restore_integrity: restored.integrity,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::infrastructure::sqlite::migration::open_profile;
    use std::{
        os::unix::fs::symlink,
        sync::atomic::{AtomicU64, Ordering},
    };

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn temp_profile(name: &str) -> ProfileStoragePaths {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        ProfileStoragePaths::new(std::env::temp_dir().join(format!(
            "p2pkanban-a16-{name}-{}-{n}/profiles/default",
            std::process::id()
        )))
    }

    fn cleanup(layout: &ProfileStoragePaths) {
        let root = layout
            .root()
            .ancestors()
            .nth(2)
            .map(PathBuf::from)
            .unwrap_or_else(|| layout.root().to_path_buf());
        let _ = fs::remove_dir_all(root);
    }

    fn current_profile(layout: &ProfileStoragePaths, marker: &str) {
        let (conn, _) = open_profile(layout).unwrap();
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS a16_marker(value TEXT NOT NULL); DELETE FROM a16_marker;",
        )
        .unwrap();
        conn.execute("INSERT INTO a16_marker(value) VALUES (?1)", [marker])
            .unwrap();
    }

    #[test]
    fn a16_manual_backup_is_verified_and_manifest_bound() {
        let layout = temp_profile("manual");
        cleanup(&layout);
        current_profile(&layout, "before");
        let backend = SqliteRecoveryBackend::new(layout.clone());
        let manifest = backend.create_manual_backup().unwrap();
        assert_eq!(manifest.format, BACKUP_MANIFEST_FORMAT);
        assert_eq!(manifest.schema_version, CURRENT_SCHEMA_VERSION);
        assert_eq!(manifest.integrity_check, "ok");
        assert_eq!(manifest.foreign_key_violations, 0);
        assert_eq!(backend.list_backups().unwrap()[0].verified, true);
        cleanup(&layout);
    }

    #[test]
    fn a16_corrupt_profile_enters_safe_mode_without_mutation() {
        let layout = temp_profile("corrupt");
        cleanup(&layout);
        layout.prepare().unwrap();
        let corrupt = b"not a sqlite database";
        write_private_file(layout.database(), corrupt).unwrap();
        let backend = SqliteRecoveryBackend::new(layout.clone());
        let report = backend.doctor().unwrap();
        assert!(report.safe_mode_required);
        assert_eq!(fs::read(layout.database()).unwrap(), corrupt);
        cleanup(&layout);
    }

    #[test]
    fn a16_restore_replaces_profile_and_quarantines_later_state() {
        let layout = temp_profile("restore");
        cleanup(&layout);
        current_profile(&layout, "before");
        let backend = SqliteRecoveryBackend::new(layout.clone());
        let backup = backend.create_manual_backup().unwrap();
        {
            let conn = Connection::open(layout.database()).unwrap();
            conn.execute("UPDATE a16_marker SET value='after'", []).unwrap();
        }
        let restored = backend.restore(&backup.backup_id).unwrap();
        assert_eq!(restored.post_restore_integrity, "ok");
        assert!(restored.quarantine_path.as_ref().is_some_and(|path| Path::new(path).is_dir()));
        let conn = open_read_only(layout.database()).unwrap();
        let value: String = conn
            .query_row("SELECT value FROM a16_marker", [], |row| row.get(0))
            .unwrap();
        assert_eq!(value, "before");
        cleanup(&layout);
    }

    #[test]
    fn a16_tampered_restore_point_is_rejected_before_profile_mutation() {
        let layout = temp_profile("tamper");
        cleanup(&layout);
        current_profile(&layout, "before");
        let backend = SqliteRecoveryBackend::new(layout.clone());
        let backup = backend.create_manual_backup().unwrap();
        let backup_path = database_path(&layout, &backup.backup_id).unwrap();
        fs::OpenOptions::new()
            .append(true)
            .open(&backup_path)
            .unwrap()
            .write_all(b"tamper")
            .unwrap();
        assert!(matches!(backend.restore(&backup.backup_id), Err(RecoveryError::HashMismatch)));
        let conn = open_read_only(layout.database()).unwrap();
        let value: String = conn
            .query_row("SELECT value FROM a16_marker", [], |row| row.get(0))
            .unwrap();
        assert_eq!(value, "before");
        cleanup(&layout);
    }

    #[test]
    fn a16_logical_export_is_read_only_content_salvage_without_operational_state() {
        let layout = temp_profile("logical-export");
        cleanup(&layout);
        {
            let (conn, _) = open_profile(&layout).unwrap();
            conn.execute(
                "INSERT INTO workspaces(id, access_epoch, title) VALUES ('w-a16', '1', 'Recovery workspace')",
                [],
            )
            .unwrap();
            conn.execute(
                "INSERT INTO boards(id, workspace_id, title) VALUES ('b-a16', 'w-a16', 'Recovery board')",
                [],
            )
            .unwrap();
        }
        let destination = layout.root().join("a16-logical-export.json");
        let backend = SqliteRecoveryBackend::new(layout.clone());
        let report = backend.export_logical(&destination, false).unwrap();
        assert!(report.row_count >= 2);
        assert_eq!(fs::metadata(&destination).unwrap().permissions().mode() & 0o777, 0o600);
        let export: RecoveryLogicalExport =
            serde_json::from_slice(&fs::read(&destination).unwrap()).unwrap();
        assert_eq!(export.format, RECOVERY_LOGICAL_EXPORT_FORMAT);
        assert_eq!(export.format_version, RECOVERY_LOGICAL_EXPORT_VERSION);
        assert_eq!(export.tables["workspaces"][0]["title"], "Recovery workspace");
        assert_eq!(export.tables["boards"][0]["title"], "Recovery board");
        assert!(!export.tables.contains_key("sync_outbox"));
        assert!(export.omitted_operational_state.iter().any(|name| name == "sync_outbox"));
        assert!(matches!(
            backend.export_logical(&destination, false),
            Err(RecoveryError::ExportDestinationExists)
        ));
        cleanup(&layout);
    }

    #[test]
    fn a16_dangling_profile_symlink_is_not_treated_as_fresh_profile() {
        let layout = temp_profile("dangling-profile");
        cleanup(&layout);
        layout.prepare().unwrap();
        symlink(layout.root().join("missing-target.sqlite"), layout.database()).unwrap();
        let report = SqliteRecoveryBackend::new(layout.clone()).doctor().unwrap();
        assert!(report.profile_exists);
        assert!(report.safe_mode_required);
        assert!(report
            .checks
            .iter()
            .any(|check| check.id == "profile-database-path" && check.level == DoctorLevel::Error));
        cleanup(&layout);
    }

    #[test]
    fn a16_old_schema_gets_verified_snapshot_before_writable_migration() {
        let layout = temp_profile("pre-migration");
        cleanup(&layout);
        layout.prepare().unwrap();
        {
            let conn = Connection::open(layout.database()).unwrap();
            conn.pragma_update(None, "foreign_keys", "ON").unwrap();
            let historical = [
                (
                    include_str!("../../../migrations/0001_initial.sql"),
                    MIGRATION_V0_TO_V1_ID,
                    MIGRATION_V0_TO_V1_SHA256,
                ),
                (
                    include_str!("../../../migrations/0002_workspace_board_titles.sql"),
                    MIGRATION_V1_TO_V2_ID,
                    MIGRATION_V1_TO_V2_SHA256,
                ),
                (
                    include_str!("../../../migrations/0003_planner_slice.sql"),
                    MIGRATION_V2_TO_V3_ID,
                    MIGRATION_V2_TO_V3_SHA256,
                ),
                (
                    include_str!("../../../migrations/0004_sync_core.sql"),
                    MIGRATION_V3_TO_V4_ID,
                    MIGRATION_V3_TO_V4_SHA256,
                ),
                (
                    include_str!("../../../migrations/0005_import_link.sql"),
                    MIGRATION_V4_TO_V5_ID,
                    MIGRATION_V4_TO_V5_SHA256,
                ),
            ];
            for (index, (migration, id, checksum)) in historical.into_iter().enumerate() {
                conn.execute_batch(migration).unwrap();
                let applied_at = i64::try_from(index + 1).unwrap();
                if index == 0 {
                    conn.execute(
                        "UPDATE profile_meta SET created_at_unix_ms=?1 WHERE singleton=1",
                        [applied_at],
                    )
                    .unwrap();
                }
                conn.execute(
                    "INSERT INTO schema_migrations(id, checksum, applied_at_unix_ms) VALUES (?1, ?2, ?3)",
                    rusqlite::params![id, checksum, applied_at],
                )
                .unwrap();
            }
            conn.execute(
                "INSERT INTO workspaces(id, access_epoch, title) VALUES ('w-old', '1', 'old schema')",
                [],
            )
            .unwrap();
        }
        fs::set_permissions(layout.database(), fs::Permissions::from_mode(0o600)).unwrap();
        let before_snapshot_sha256 = sha256_file(layout.database()).unwrap();
        let backend = SqliteRecoveryBackend::new(layout.clone());
        let doctor_before = backend.doctor().unwrap();
        assert!(!doctor_before.safe_mode_required);
        assert_eq!(doctor_before.schema_version, Some(5));

        let snapshot = backend
            .create_pre_migration_backup()
            .unwrap()
            .expect("old schema must receive a verified snapshot");
        assert_eq!(snapshot.schema_version, 5);
        assert!(snapshot.backup_id.starts_with("pre-migration-v5-to-v6-"));
        assert_eq!(sha256_file(layout.database()).unwrap(), before_snapshot_sha256);
        let verified_before = verify_restore_point(&layout, &snapshot.backup_id).unwrap();
        assert_eq!(verified_before.schema_version, 5);

        let (migrated, info) = open_profile(&layout).unwrap();
        assert_eq!(info.schema_version, CURRENT_SCHEMA_VERSION);
        let title: String = migrated
            .query_row(
                "SELECT title FROM workspaces WHERE id='w-old'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(title, "old schema");
        drop(migrated);

        let verified_after = verify_restore_point(&layout, &snapshot.backup_id).unwrap();
        assert_eq!(verified_after.schema_version, 5);
        let backup_path = database_path(&layout, &snapshot.backup_id).unwrap();
        let backup_conn = open_read_only(&backup_path).unwrap();
        let backup_title: String = backup_conn
            .query_row(
                "SELECT title FROM workspaces WHERE id='w-old'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(backup_title, "old schema");

        let listed = backend.list_backups().unwrap();
        assert!(listed
            .iter()
            .any(|item| item.backup_id == snapshot.backup_id && item.verified));
        cleanup(&layout);
    }
}
