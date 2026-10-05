use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

use rusqlite::{Connection, TransactionBehavior};

use crate::infrastructure::profile::{write_private_file, ProfileStoragePaths};

pub const CURRENT_SCHEMA_VERSION: u32 = 6;
pub const MIN_READER_SCHEMA_VERSION: u32 = 6;
pub const MIN_WRITER_SCHEMA_VERSION: u32 = 6;
pub const BUSY_TIMEOUT_MS: u64 = 2_500;

pub const MIGRATION_V0_TO_V1_ID: &str = "desktop-0001-initial-planner";
pub const MIGRATION_V0_TO_V1_SHA256: &str = "c88155c8d7093f5fe15d076043aebe0359746fadf509fc0acb3883188b103594";
pub const MIGRATION_V1_TO_V2_ID: &str = "desktop-0002-workspace-board-titles";
pub const MIGRATION_V1_TO_V2_SHA256: &str = "01cdfaa3b020e1fbab4abbd45640f0726aa43d08bd1f20837856300dedbe1901";
pub const MIGRATION_V2_TO_V3_ID: &str = "desktop-0003-planner-slice";
pub const MIGRATION_V2_TO_V3_SHA256: &str = "ebcec1f2d34192257a11b497155bfec84937f6fc7de8edbed35bb0a67569dd48";
pub const MIGRATION_V3_TO_V4_ID: &str = "desktop-0004-sync-core";
pub const MIGRATION_V3_TO_V4_SHA256: &str = "d975a65e66c6f4208d97e1a9d8e8c07b3dd6fe1070ebe32e894da3bfc0b0999a";
pub const MIGRATION_V4_TO_V5_ID: &str = "desktop-0005-import-link";
pub const MIGRATION_V4_TO_V5_SHA256: &str = "f32f6c68584c4b43c06fd817bb567cce33064fdceb4dd8452f16249679a62726";
pub const MIGRATION_V5_TO_V6_ID: &str = "desktop-0006-parity-surface";
pub const MIGRATION_V5_TO_V6_SHA256: &str = "b753e298b520e05b493c1e06b3801ea0b528d42635756f8ae0ca2e38e4adac8a";

const SCHEMA_V1: &str = include_str!("../../../migrations/0001_initial.sql");
const SCHEMA_V2: &str = include_str!("../../../migrations/0002_workspace_board_titles.sql");
const SCHEMA_V3: &str = include_str!("../../../migrations/0003_planner_slice.sql");
const SCHEMA_V4: &str = include_str!("../../../migrations/0004_sync_core.sql");
const SCHEMA_V5: &str = include_str!("../../../migrations/0005_import_link.sql");
const SCHEMA_V6: &str = include_str!("../../../migrations/0006_parity_surface.sql");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProfileSchemaInfo {
    pub schema_version: u32,
    pub min_reader: u32,
    pub min_writer: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProfileOpenError {
    Io,
    Database,
    UnsupportedSchema { found: u32, max_writer: u32 },
    InvalidSchemaMetadata,
    IntegrityCheckFailed,
    MigrationRecovered,
    WalUnavailable,
}

impl From<rusqlite::Error> for ProfileOpenError {
    fn from(_: rusqlite::Error) -> Self {
        Self::Database
    }
}

fn epoch_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(i64::MAX as u128) as i64)
        .unwrap_or(0)
}

fn write_journal(
    layout: &ProfileStoragePaths,
    from: u32,
    to: u32,
    state: &str,
) -> Result<(), ProfileOpenError> {
    let body = format!(
        "{{\n  \"formatVersion\": 1,\n  \"fromSchema\": {from},\n  \"toSchema\": {to},\n  \"state\": \"{state}\"\n}}\n"
    );
    write_private_file(layout.migration_journal(), body.as_bytes()).map_err(|_| ProfileOpenError::Io)
}

fn configure_connection(conn: &Connection, file_backed: bool) -> Result<(), ProfileOpenError> {
    conn.busy_timeout(std::time::Duration::from_millis(BUSY_TIMEOUT_MS))?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    conn.pragma_update(None, "synchronous", "FULL")?;

    if file_backed {
        let mode: String = conn.query_row("PRAGMA journal_mode=WAL", [], |row| row.get(0))?;
        if !mode.eq_ignore_ascii_case("wal") {
            return Err(ProfileOpenError::WalUnavailable);
        }
    }
    Ok(())
}

fn pragma_user_version(conn: &Connection) -> Result<u32, ProfileOpenError> {
    let version: i64 = conn.query_row("PRAGMA user_version", [], |row| row.get(0))?;
    u32::try_from(version).map_err(|_| ProfileOpenError::InvalidSchemaMetadata)
}

fn schema_info(conn: &Connection) -> Result<ProfileSchemaInfo, ProfileOpenError> {
    let (schema, reader, writer): (i64, i64, i64) = conn.query_row(
        "SELECT schema_version, min_reader, min_writer FROM profile_meta WHERE singleton = 1",
        [],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    )?;
    let info = ProfileSchemaInfo {
        schema_version: u32::try_from(schema).map_err(|_| ProfileOpenError::InvalidSchemaMetadata)?,
        min_reader: u32::try_from(reader).map_err(|_| ProfileOpenError::InvalidSchemaMetadata)?,
        min_writer: u32::try_from(writer).map_err(|_| ProfileOpenError::InvalidSchemaMetadata)?,
    };
    if info.schema_version == 0 || info.min_reader == 0 || info.min_writer == 0 {
        return Err(ProfileOpenError::InvalidSchemaMetadata);
    }
    Ok(info)
}

fn check_integrity(conn: &Connection) -> Result<(), ProfileOpenError> {
    let integrity: String = conn.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
    if integrity != "ok" {
        return Err(ProfileOpenError::IntegrityCheckFailed);
    }
    let fk_rows: i64 = conn.query_row(
        "SELECT COUNT(*) FROM pragma_foreign_key_check",
        [],
        |row| row.get(0),
    )?;
    if fk_rows != 0 {
        return Err(ProfileOpenError::IntegrityCheckFailed);
    }
    Ok(())
}

fn backup_is_valid(path: &Path) -> Result<(), ProfileOpenError> {
    let conn = Connection::open(path)?;
    check_integrity(&conn)
}

fn record_migration(
    tx: &rusqlite::Transaction<'_>,
    id: &str,
    checksum: &str,
    applied_at: i64,
) -> Result<(), ProfileOpenError> {
    tx.execute(
        "INSERT INTO schema_migrations(id, checksum, applied_at_unix_ms) VALUES (?1, ?2, ?3)",
        rusqlite::params![id, checksum, applied_at],
    )?;
    Ok(())
}

fn apply_v0_to_v1(conn: &mut Connection) -> Result<(), ProfileOpenError> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(SCHEMA_V1)?;
    let applied_at = epoch_millis();
    tx.execute(
        "UPDATE profile_meta SET created_at_unix_ms = ?1 WHERE singleton = 1",
        [applied_at],
    )?;
    record_migration(&tx, MIGRATION_V0_TO_V1_ID, MIGRATION_V0_TO_V1_SHA256, applied_at)?;
    tx.commit()?;
    Ok(())
}

fn apply_v1_to_v2(conn: &mut Connection) -> Result<(), ProfileOpenError> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(SCHEMA_V2)?;
    let applied_at = epoch_millis();
    record_migration(&tx, MIGRATION_V1_TO_V2_ID, MIGRATION_V1_TO_V2_SHA256, applied_at)?;
    tx.commit()?;
    Ok(())
}

fn apply_v2_to_v3(conn: &mut Connection) -> Result<(), ProfileOpenError> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(SCHEMA_V3)?;
    let applied_at = epoch_millis();
    record_migration(&tx, MIGRATION_V2_TO_V3_ID, MIGRATION_V2_TO_V3_SHA256, applied_at)?;
    tx.commit()?;
    Ok(())
}

fn apply_v3_to_v4(conn: &mut Connection, force_failure: bool) -> Result<(), ProfileOpenError> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(SCHEMA_V4)?;
    let applied_at = epoch_millis();
    record_migration(&tx, MIGRATION_V3_TO_V4_ID, MIGRATION_V3_TO_V4_SHA256, applied_at)?;
    if force_failure {
        return Err(ProfileOpenError::MigrationRecovered);
    }
    tx.commit()?;
    Ok(())
}

fn apply_v4_to_v5(conn: &mut Connection, force_failure: bool) -> Result<(), ProfileOpenError> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(SCHEMA_V5)?;
    let applied_at = epoch_millis();
    record_migration(&tx, MIGRATION_V4_TO_V5_ID, MIGRATION_V4_TO_V5_SHA256, applied_at)?;
    if force_failure {
        return Err(ProfileOpenError::MigrationRecovered);
    }
    tx.commit()?;
    Ok(())
}


fn apply_v5_to_v6(conn: &mut Connection, force_failure: bool) -> Result<(), ProfileOpenError> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(SCHEMA_V6)?;
    let applied_at = epoch_millis();
    record_migration(&tx, MIGRATION_V5_TO_V6_ID, MIGRATION_V5_TO_V6_SHA256, applied_at)?;
    if force_failure {
        return Err(ProfileOpenError::MigrationRecovered);
    }
    tx.commit()?;
    Ok(())
}

fn migrate_if_needed(
    conn: &mut Connection,
    layout: &ProfileStoragePaths,
    existed_before_open: bool,
    force_failure: bool,
) -> Result<(), ProfileOpenError> {
    let from = pragma_user_version(conn)?;
    if from > CURRENT_SCHEMA_VERSION {
        return Err(ProfileOpenError::UnsupportedSchema {
            found: from,
            max_writer: CURRENT_SCHEMA_VERSION,
        });
    }
    if from == CURRENT_SCHEMA_VERSION {
        return Ok(());
    }
    if from > 5 {
        return Err(ProfileOpenError::UnsupportedSchema {
            found: from,
            max_writer: CURRENT_SCHEMA_VERSION,
        });
    }

    let journal = layout.migration_journal();
    let backup = layout.migration_backup(from);
    let should_backup = existed_before_open;
    if should_backup {
        let _ = fs::remove_file(&backup);
        conn.backup("main", &backup, None)?;
        fs::set_permissions(&backup, fs::Permissions::from_mode(0o600))
            .map_err(|_| ProfileOpenError::Io)?;
        backup_is_valid(&backup)?;
    }
    write_journal(layout, from, CURRENT_SCHEMA_VERSION, "prepared")?;

    let migration_result = (|| -> Result<(), ProfileOpenError> {
        let mut current = pragma_user_version(conn)?;
        if current == 0 {
            apply_v0_to_v1(conn)?;
            current = pragma_user_version(conn)?;
        }
        if current == 1 {
            apply_v1_to_v2(conn)?;
            current = pragma_user_version(conn)?;
        }
        if current == 2 {
            apply_v2_to_v3(conn)?;
            current = pragma_user_version(conn)?;
        }
        if current == 3 {
            apply_v3_to_v4(conn, false)?;
            current = pragma_user_version(conn)?;
        }
        if current == 4 {
            apply_v4_to_v5(conn, false)?;
            current = pragma_user_version(conn)?;
        }
        if current == 5 {
            apply_v5_to_v6(conn, force_failure)?;
        }
        if pragma_user_version(conn)? != CURRENT_SCHEMA_VERSION {
            return Err(ProfileOpenError::InvalidSchemaMetadata);
        }
        check_integrity(conn)
    })();

    if let Err(err) = migration_result {
        if should_backup {
            conn.restore("main", &backup, None::<fn(rusqlite::backup::Progress)>)?;
            backup_is_valid(&backup)?;
        }
        write_journal(layout, from, CURRENT_SCHEMA_VERSION, "restored-after-failure")?;
        return Err(err);
    }

    write_journal(layout, from, CURRENT_SCHEMA_VERSION, "completed")?;
    let _ = fs::remove_file(journal);
    Ok(())
}

fn verify_migration_line(conn: &Connection) -> Result<(), ProfileOpenError> {
    let mut stmt = conn.prepare(
        "SELECT id, checksum FROM schema_migrations ORDER BY id",
    )?;
    let rows = stmt.query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)))?;
    let observed = rows.collect::<Result<Vec<_>, _>>()?;
    let expected = vec![
        (MIGRATION_V0_TO_V1_ID.to_owned(), MIGRATION_V0_TO_V1_SHA256.to_owned()),
        (MIGRATION_V1_TO_V2_ID.to_owned(), MIGRATION_V1_TO_V2_SHA256.to_owned()),
        (MIGRATION_V2_TO_V3_ID.to_owned(), MIGRATION_V2_TO_V3_SHA256.to_owned()),
        (MIGRATION_V3_TO_V4_ID.to_owned(), MIGRATION_V3_TO_V4_SHA256.to_owned()),
        (MIGRATION_V4_TO_V5_ID.to_owned(), MIGRATION_V4_TO_V5_SHA256.to_owned()),
        (MIGRATION_V5_TO_V6_ID.to_owned(), MIGRATION_V5_TO_V6_SHA256.to_owned()),
    ];
    if observed != expected {
        return Err(ProfileOpenError::InvalidSchemaMetadata);
    }
    Ok(())
}

pub(crate) fn open_profile(
    layout: &ProfileStoragePaths,
) -> Result<(Connection, ProfileSchemaInfo), ProfileOpenError> {
    layout.prepare().map_err(|_| ProfileOpenError::Io)?;
    let existed_before_open = layout.database().exists();
    let mut conn = Connection::open(layout.database())?;
    layout
        .enforce_database_permissions()
        .map_err(|_| ProfileOpenError::Io)?;
    configure_connection(&conn, true)?;
    migrate_if_needed(&mut conn, layout, existed_before_open, false)?;
    let info = schema_info(&conn)?;
    verify_migration_line(&conn)?;
    if info.schema_version != CURRENT_SCHEMA_VERSION
        || info.min_reader > CURRENT_SCHEMA_VERSION
        || info.min_writer > CURRENT_SCHEMA_VERSION
    {
        return Err(ProfileOpenError::UnsupportedSchema {
            found: info.schema_version,
            max_writer: CURRENT_SCHEMA_VERSION,
        });
    }
    check_integrity(&conn)?;
    Ok((conn, info))
}

#[cfg(test)]
pub(crate) fn open_profile_with_forced_migration_failure(
    layout: &ProfileStoragePaths,
) -> Result<(), ProfileOpenError> {
    layout.prepare().map_err(|_| ProfileOpenError::Io)?;
    let existed_before_open = layout.database().exists();
    let mut conn = Connection::open(layout.database())?;
    layout
        .enforce_database_permissions()
        .map_err(|_| ProfileOpenError::Io)?;
    configure_connection(&conn, true)?;
    migrate_if_needed(&mut conn, layout, existed_before_open, true)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{path::PathBuf, sync::atomic::{AtomicU64, Ordering}};

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn temp_profile(name: &str) -> ProfileStoragePaths {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        ProfileStoragePaths::new(std::env::temp_dir().join(format!(
            "p2pkanban-a07-{name}-{}-{n}/profiles/default",
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

    #[test]
    fn new_profile_reaches_current_schema_and_durability_pragmas() {
        let layout = temp_profile("pragmas");
        cleanup(&layout);
        let (conn, info) = open_profile(&layout).unwrap();
        assert_eq!(info.schema_version, 6);
        assert_eq!(info.min_reader, 6);
        assert_eq!(info.min_writer, 6);
        let fk: i64 = conn.query_row("PRAGMA foreign_keys", [], |row| row.get(0)).unwrap();
        let sync: i64 = conn.query_row("PRAGMA synchronous", [], |row| row.get(0)).unwrap();
        let mode: String = conn.query_row("PRAGMA journal_mode", [], |row| row.get(0)).unwrap();
        assert_eq!(fk, 1);
        assert_eq!(sync, 2);
        assert_eq!(mode.to_ascii_lowercase(), "wal");
        assert_eq!(fs::metadata(layout.database()).unwrap().permissions().mode() & 0o777, 0o600);
        check_integrity(&conn).unwrap();
        drop(conn);
        cleanup(&layout);
    }

    #[test]
    fn v1_profile_migrates_to_v6_and_preserves_workspace_board_identity() {
        let layout = temp_profile("v1-to-v2");
        cleanup(&layout);
        layout.prepare().unwrap();
        {
            let mut conn = Connection::open(layout.database()).unwrap();
            configure_connection(&conn, true).unwrap();
            apply_v0_to_v1(&mut conn).unwrap();
            conn.execute(
                "INSERT INTO workspaces(id, access_epoch) VALUES ('workspace-a', '1')",
                [],
            ).unwrap();
            conn.execute(
                "INSERT INTO boards(id, workspace_id) VALUES ('board-a', 'workspace-a')",
                [],
            ).unwrap();
        }
        let (conn, info) = open_profile(&layout).unwrap();
        assert_eq!(info.schema_version, 6);
        let row: (String, String, String, String) = conn.query_row(
            "SELECT w.id, w.title, b.id, b.title FROM workspaces w JOIN boards b ON b.workspace_id=w.id",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        ).unwrap();
        assert_eq!(row, ("workspace-a".into(), "".into(), "board-a".into(), "".into()));
        drop(conn);
        cleanup(&layout);
    }


    #[test]
    fn a08_v2_profile_migrates_to_v3_preserving_existing_planner_identity() {
        let layout = temp_profile("a08-v2-to-v3-regression");
        cleanup(&layout);
        layout.prepare().unwrap();
        let mut conn = Connection::open(layout.database()).unwrap();
        configure_connection(&conn, true).unwrap();
        apply_v0_to_v1(&mut conn).unwrap();
        apply_v1_to_v2(&mut conn).unwrap();
        conn.execute(
            "INSERT INTO workspaces(id, access_epoch, title) VALUES ('workspace-a08-regression', '7', 'workspace')",
            [],
        ).unwrap();
        conn.execute(
            "INSERT INTO boards(id, workspace_id, title) VALUES ('board-a08-regression', 'workspace-a08-regression', 'board')",
            [],
        ).unwrap();
        conn.execute(
            "INSERT INTO columns(id, board_id) VALUES ('column-a08-regression', 'board-a08-regression')",
            [],
        ).unwrap();
        conn.execute(
            "INSERT INTO cards(id, workspace_id, board_id, column_id, title, position, lifecycle) VALUES ('card-a08-regression', 'workspace-a08-regression', 'board-a08-regression', 'column-a08-regression', 'card', 1000.0, 'active')",
            [],
        ).unwrap();

        apply_v2_to_v3(&mut conn).unwrap();
        let version: i64 = conn.query_row("PRAGMA user_version", [], |row| row.get(0)).unwrap();
        assert_eq!(version, 3);
        let row: (String, String, String, String) = conn.query_row(
            "SELECT w.id, b.id, c.id, k.id FROM workspaces w JOIN boards b ON b.workspace_id=w.id JOIN columns c ON c.board_id=b.id JOIN cards k ON k.column_id=c.id",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        ).unwrap();
        assert_eq!(row, (
            "workspace-a08-regression".into(),
            "board-a08-regression".into(),
            "column-a08-regression".into(),
            "card-a08-regression".into(),
        ));
        check_integrity(&conn).unwrap();
        drop(conn);
        cleanup(&layout);
    }

    #[test]
    fn a12_v2_profile_migrates_to_v6_preserving_existing_planner_identity() {
        let layout = temp_profile("v2-to-v3");
        cleanup(&layout);
        layout.prepare().unwrap();
        {
            let mut conn = Connection::open(layout.database()).unwrap();
            configure_connection(&conn, true).unwrap();
            apply_v0_to_v1(&mut conn).unwrap();
            apply_v1_to_v2(&mut conn).unwrap();
            conn.execute(
                "INSERT INTO workspaces(id, access_epoch, title) VALUES ('workspace-a08', '7', 'workspace')",
                [],
            ).unwrap();
            conn.execute(
                "INSERT INTO boards(id, workspace_id, title) VALUES ('board-a08', 'workspace-a08', 'board')",
                [],
            ).unwrap();
            conn.execute(
                "INSERT INTO columns(id, board_id) VALUES ('column-a08', 'board-a08')",
                [],
            ).unwrap();
            conn.execute(
                "INSERT INTO cards(id, workspace_id, board_id, column_id, title, position, lifecycle) VALUES ('card-a08', 'workspace-a08', 'board-a08', 'column-a08', 'card', 1000.0, 'active')",
                [],
            ).unwrap();
        }

        let (conn, info) = open_profile(&layout).unwrap();
        assert_eq!(info.schema_version, 6);
        let row: (String, String, String, String) = conn.query_row(
            "SELECT w.id, b.id, c.id, k.id FROM workspaces w JOIN boards b ON b.workspace_id=w.id JOIN columns c ON c.board_id=b.id JOIN cards k ON k.column_id=c.id",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        ).unwrap();
        assert_eq!(row, ("workspace-a08".into(), "board-a08".into(), "column-a08".into(), "card-a08".into()));
        let title: String = conn.query_row(
            "SELECT title FROM columns WHERE id='column-a08'", [], |row| row.get(0),
        ).unwrap();
        let position: f64 = conn.query_row(
            "SELECT position FROM columns WHERE id='column-a08'", [], |row| row.get(0),
        ).unwrap();
        assert_eq!(title, "");
        assert_eq!(position, 0.0);
        check_integrity(&conn).unwrap();
        drop(conn);
        cleanup(&layout);
    }

    #[test]
    fn newer_writer_schema_is_refused() {
        let layout = temp_profile("future");
        cleanup(&layout);
        let (conn, _) = open_profile(&layout).unwrap();
        conn.pragma_update(None, "user_version", 99).unwrap();
        drop(conn);
        let result = open_profile(&layout);
        assert!(matches!(
            result,
            Err(ProfileOpenError::UnsupportedSchema { found: 99, max_writer: 6 })
        ));
        cleanup(&layout);
    }

    #[test]
    fn forced_migration_failure_restores_existing_v0_profile() {
        let layout = temp_profile("restore");
        cleanup(&layout);
        layout.prepare().unwrap();
        {
            let conn = Connection::open(layout.database()).unwrap();
            conn.execute_batch(
                "CREATE TABLE legacy_marker(value TEXT NOT NULL);\nINSERT INTO legacy_marker(value) VALUES ('keep-me');\nPRAGMA user_version=0;",
            )
            .unwrap();
        }
        assert_eq!(
            open_profile_with_forced_migration_failure(&layout),
            Err(ProfileOpenError::MigrationRecovered)
        );
        let conn = Connection::open(layout.database()).unwrap();
        let marker: String = conn
            .query_row("SELECT value FROM legacy_marker", [], |row| row.get(0))
            .unwrap();
        assert_eq!(marker, "keep-me");
        assert_eq!(pragma_user_version(&conn).unwrap(), 0);
        drop(conn);
        assert!(layout.migration_backup(0).is_file());
        let journal = fs::read_to_string(layout.migration_journal()).unwrap();
        assert!(journal.contains("restored-after-failure"));
        cleanup(&layout);
    }

    #[test]
    fn migration_artifacts_use_final_profile_recovery_layout() {
        let layout = temp_profile("layout");
        assert!(layout.migration_backup(0).ends_with("backups/pre-migration-v0.sqlite"));
        assert!(layout.migration_journal().ends_with("migration-journal.json"));
    }
}
