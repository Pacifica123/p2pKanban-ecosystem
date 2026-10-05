use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::{Map, Value};

use crate::{
    application::import::{ImportApplyReport, ImportRepository, ImportRepositoryError},
    domain::import::{ImportPlan, ImportedTombstone},
    infrastructure::profile::ProfileStoragePaths,
};

use super::migration::{open_profile, ProfileOpenError};

pub struct SqliteImportRepository {
    connection: Connection,
}

impl SqliteImportRepository {
    pub fn open(layout: &ProfileStoragePaths) -> Result<Self, ProfileOpenError> {
        let (connection, _) = open_profile(layout)?;
        Ok(Self { connection })
    }
}

fn now_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(i64::MAX as u128) as i64)
        .unwrap_or(0)
}

fn storage<T>(_: T) -> ImportRepositoryError {
    ImportRepositoryError::StorageFailure
}

fn receipt_exists(conn: &Connection, digest: &str) -> Result<bool, ImportRepositoryError> {
    conn.query_row(
        "SELECT 1 FROM import_receipts WHERE source_digest = ?1",
        [digest],
        |_| Ok(()),
    )
    .optional()
    .map(|value| value.is_some())
    .map_err(storage)
}

fn profile_has_portable_state(conn: &Connection) -> Result<bool, ImportRepositoryError> {
    let counts: (i64, i64, i64) = conn
        .query_row(
            "SELECT (SELECT COUNT(*) FROM workspaces), (SELECT COUNT(*) FROM boards), (SELECT COUNT(*) FROM profile_principal)",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .map_err(storage)?;
    Ok(counts.0 != 0 || counts.1 != 0 || counts.2 != 0)
}

fn existing_principal(conn: &Connection) -> Result<Option<(String, String)>, ImportRepositoryError> {
    conn.query_row(
        "SELECT user_id, device_public_key FROM profile_principal WHERE singleton = 1",
        [],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )
    .optional()
    .map_err(storage)
}

fn preflight_on(conn: &Connection, plan: &ImportPlan) -> Result<(), ImportRepositoryError> {
    if receipt_exists(conn, &plan.receipt.source_digest)? {
        return Err(ImportRepositoryError::Replay);
    }
    if plan.requires_empty_profile && profile_has_portable_state(conn)? {
        return Err(ImportRepositoryError::DestinationNotEmpty);
    }
    if let (Some(incoming), Some((user_id, device_public_key))) =
        (&plan.principal, existing_principal(conn)?)
    {
        if incoming.user_id != user_id || incoming.device_public_key != device_public_key {
            return Err(ImportRepositoryError::IdentityConflict);
        }
    }
    Ok(())
}

fn insert_tombstone(tx: &Transaction<'_>, value: &ImportedTombstone) -> Result<(), ImportRepositoryError> {
    match value.entity_kind.as_str() {
        "card" => tx.execute(
            "INSERT INTO card_tombstones(card_id, workspace_id, board_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![value.entity_id, value.workspace_id, value.board_id, value.logical_clock.to_string(), value.replica_id, value.event_id],
        ),
        "checklist" => tx.execute(
            "INSERT INTO checklist_tombstones(checklist_id, workspace_id, board_id, card_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![value.entity_id, value.workspace_id, value.board_id, value.card_id.as_deref().ok_or(ImportRepositoryError::InvalidScope)?, value.logical_clock.to_string(), value.replica_id, value.event_id],
        ),
        "checklist_item" => tx.execute(
            "INSERT INTO checklist_item_tombstones(item_id, workspace_id, board_id, card_id, checklist_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![value.entity_id, value.workspace_id, value.board_id, value.card_id.as_deref().ok_or(ImportRepositoryError::InvalidScope)?, value.checklist_id.as_deref().ok_or(ImportRepositoryError::InvalidScope)?, value.logical_clock.to_string(), value.replica_id, value.event_id],
        ),
        _ => return Err(ImportRepositoryError::InvalidScope),
    }
    .map(|_| ())
    .map_err(storage)
}


fn object_string<'a>(object: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a str> {
    keys.iter().find_map(|key| object.get(*key).and_then(Value::as_str))
}

fn section_array(plan: &ImportPlan, name: &str) -> Result<Vec<Map<String, Value>>, ImportRepositoryError> {
    let Some(section) = plan.opaque_sections.iter().find(|value| value.section_name == name) else {
        return Ok(Vec::new());
    };
    let value: Value = serde_json::from_str(&section.payload_json).map_err(storage)?;
    let values = value.as_array().ok_or(ImportRepositoryError::InvalidScope)?;
    values
        .iter()
        .map(|value| value.as_object().cloned().ok_or(ImportRepositoryError::InvalidScope))
        .collect()
}

fn board_workspace(tx: &Transaction<'_>, board_id: &str) -> Result<String, ImportRepositoryError> {
    tx.query_row("SELECT workspace_id FROM boards WHERE id=?1", [board_id], |row| row.get(0))
        .optional().map_err(storage)?.ok_or(ImportRepositoryError::InvalidScope)
}

fn card_scope(tx: &Transaction<'_>, card_id: &str) -> Result<(String, String), ImportRepositoryError> {
    tx.query_row("SELECT workspace_id,board_id FROM cards WHERE id=?1", [card_id], |row| Ok((row.get(0)?,row.get(1)?)))
        .optional().map_err(storage)?.ok_or(ImportRepositoryError::InvalidScope)
}

fn materialize_parity_sections(tx: &Transaction<'_>, plan: &ImportPlan) -> Result<(), ImportRepositoryError> {
    for (index, object) in section_array(plan, "labels")?.into_iter().enumerate() {
        let id = object_string(&object, &["id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let board_id = object_string(&object, &["boardId", "board_id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        board_workspace(tx, board_id)?;
        let name = object_string(&object, &["name", "title", "label"]).unwrap_or("");
        let color = object_string(&object, &["color", "colorToken"]);
        let position = object.get("position").and_then(Value::as_f64).unwrap_or((index as f64 + 1.0) * 1000.0);
        let raw = serde_json::to_string(&Value::Object(object.clone())).map_err(storage)?;
        tx.execute("INSERT INTO labels(id,board_id,name,color,position,raw_json) VALUES (?1,?2,?3,?4,?5,?6)", params![id,board_id,name,color,position,raw]).map_err(storage)?;
    }
    for object in section_array(plan, "cardLabels")? {
        let card_id = object_string(&object, &["cardId", "card_id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let label_id = object_string(&object, &["labelId", "label_id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let (_, card_board) = card_scope(tx, card_id)?;
        let label_board: String = tx.query_row("SELECT board_id FROM labels WHERE id=?1", [label_id], |row| row.get(0)).map_err(storage)?;
        if card_board != label_board { return Err(ImportRepositoryError::InvalidScope); }
        tx.execute("INSERT INTO card_labels(card_id,label_id) VALUES (?1,?2)", params![card_id,label_id]).map_err(storage)?;
    }
    for object in section_array(plan, "comments")? {
        let id = object_string(&object, &["id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let card_id = object_string(&object, &["cardId", "card_id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let (workspace_id, board_id) = card_scope(tx, card_id)?;
        let body = object_string(&object, &["body", "content", "text"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let author = object_string(&object, &["authorUserId", "userId", "authorId"]);
        let created = object_string(&object, &["createdAt", "occurredAt"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let updated = object_string(&object, &["updatedAt"]).unwrap_or(created);
        let raw = serde_json::to_string(&Value::Object(object.clone())).map_err(storage)?;
        tx.execute("INSERT INTO comments(id,workspace_id,board_id,card_id,author_user_id,body,created_at,updated_at,raw_json) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)", params![id,workspace_id,board_id,card_id,author,body,created,updated,raw]).map_err(storage)?;
    }
    for object in section_array(plan, "boardAppearanceSettings")? {
        let board_id = object_string(&object, &["boardId", "board_id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        board_workspace(tx, board_id)?;
        let mut normalized = object.clone();
        normalized.insert("boardId".into(), Value::String(board_id.to_owned()));
        let raw = serde_json::to_string(&Value::Object(normalized)).map_err(storage)?;
        let updated = object_string(&object, &["updatedAt", "createdAt"]).unwrap_or("");
        tx.execute("INSERT INTO board_appearance_settings(board_id,settings_json,updated_at) VALUES (?1,?2,?3)", params![board_id,raw,updated]).map_err(storage)?;
    }
    for object in section_array(plan, "activityEntries")? {
        let id = object_string(&object, &["id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let board_id = object_string(&object, &["boardId", "board_id"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let workspace_id = board_workspace(tx, board_id)?;
        let card_id = object_string(&object, &["cardId", "card_id"]);
        if let Some(card_id) = card_id {
            let (card_workspace, card_board) = card_scope(tx, card_id)?;
            if card_workspace != workspace_id || card_board != board_id { return Err(ImportRepositoryError::InvalidScope); }
        }
        let actor = object_string(&object, &["actorUserId", "userId", "actorId"]);
        let kind = object_string(&object, &["kind", "action", "type"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let entity_type = object_string(&object, &["entityType", "entity_type"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let entity_id = object_string(&object, &["entityId", "entity_id"]);
        let occurred = object_string(&object, &["occurredAt", "createdAt"]).ok_or(ImportRepositoryError::InvalidScope)?;
        let raw = serde_json::to_string(&Value::Object(object.clone())).map_err(storage)?;
        tx.execute("INSERT INTO activity_entries(id,workspace_id,board_id,card_id,actor_user_id,kind,entity_type,entity_id,payload_json,occurred_at) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)", params![id,workspace_id,board_id,card_id,actor,kind,entity_type,entity_id,raw,occurred]).map_err(storage)?;
    }
    Ok(())
}

fn advance_lamport_floor(tx: &Transaction<'_>, plan: &ImportPlan) -> Result<(), ImportRepositoryError> {
    let imported_max = plan
        .tombstones
        .iter()
        .map(|value| value.logical_clock)
        .max()
        .unwrap_or(0);
    if imported_max == 0 {
        return Ok(());
    }
    let current: String = tx
        .query_row(
            "SELECT logical_clock FROM local_mutation_state WHERE singleton = 1",
            [],
            |row| row.get(0),
        )
        .map_err(storage)?;
    let current = current.parse::<u64>().map_err(storage)?;
    if imported_max > current {
        tx.execute(
            "UPDATE local_mutation_state SET logical_clock = ?1 WHERE singleton = 1",
            [imported_max.to_string()],
        )
        .map_err(storage)?;
    }
    Ok(())
}

impl ImportRepository for SqliteImportRepository {
    fn preflight(&self, plan: &ImportPlan) -> Result<(), ImportRepositoryError> {
        preflight_on(&self.connection, plan)
    }

    fn apply_plan(&mut self, plan: &ImportPlan) -> Result<ImportApplyReport, ImportRepositoryError> {
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        preflight_on(&tx, plan)?;

        tx.execute(
            "INSERT INTO import_receipts(source_digest, source_kind, format_version, user_id, workspace_id, board_id, omissions_json, imported_at_unix_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                plan.receipt.source_digest,
                plan.receipt.source_kind.stable_name(),
                plan.receipt.format_version,
                plan.receipt.user_id,
                plan.receipt.workspace_id,
                plan.receipt.board_id,
                plan.receipt.omissions_json,
                now_millis(),
            ],
        )
        .map_err(storage)?;

        if let Some(principal) = &plan.principal {
            match existing_principal(&tx)? {
                None => {
                    tx.execute(
                        "INSERT INTO profile_principal(singleton, user_id, replica_id, device_public_key, provisioned_by, created_at_unix_ms) VALUES (1, ?1, ?2, ?3, ?4, ?5)",
                        params![principal.user_id, principal.replica_id, principal.device_public_key, principal.provisioned_by.stable_name(), now_millis()],
                    )
                    .map_err(storage)?;
                }
                Some(_) => {}
            }
        }

        for workspace in &plan.workspaces {
            tx.execute(
                "INSERT INTO workspaces(id, access_epoch, title) VALUES (?1, ?2, ?3)",
                params![workspace.id, workspace.access_epoch.to_string(), workspace.title],
            )
            .map_err(storage)?;
        }
        for board in &plan.boards {
            tx.execute(
                "INSERT INTO boards(id, workspace_id, title) VALUES (?1, ?2, ?3)",
                params![board.id, board.workspace_id, board.title],
            )
            .map_err(storage)?;
        }
        for column in &plan.columns {
            tx.execute(
                "INSERT INTO columns(id, board_id, title, position) VALUES (?1, ?2, ?3, ?4)",
                params![column.id, column.board_id, column.title, column.position],
            )
            .map_err(storage)?;
        }
        for card in &plan.cards {
            tx.execute(
                "INSERT INTO cards(id, workspace_id, board_id, column_id, title, position, lifecycle) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![card.id, card.workspace_id, card.board_id, card.column_id, card.title, card.position, if card.archived { "archived" } else { "active" }],
            )
            .map_err(storage)?;
        }
        for checklist in &plan.checklists {
            tx.execute(
                "INSERT INTO checklists(id, workspace_id, board_id, card_id, title, position) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![checklist.id, checklist.workspace_id, checklist.board_id, checklist.card_id, checklist.title, checklist.position],
            )
            .map_err(storage)?;
        }
        for item in &plan.checklist_items {
            tx.execute(
                "INSERT INTO checklist_items(id, checklist_id, title, position, is_done) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![item.id, item.checklist_id, item.title, item.position, if item.is_done { 1 } else { 0 }],
            )
            .map_err(storage)?;
        }
        for tombstone in &plan.tombstones {
            insert_tombstone(&tx, tombstone)?;
        }
        for capability in &plan.capabilities {
            tx.execute(
                "INSERT INTO imported_capability_metadata(board_id, workspace_id, user_id, capability_epoch, subject, can_delegate, parent_id, expires_at_unix, source_digest) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
                params![capability.board_id, capability.workspace_id, capability.user_id, capability.capability_epoch.to_string(), capability.subject, if capability.can_delegate { 1 } else { 0 }, capability.parent_id, capability.expires_at_unix, plan.receipt.source_digest],
            )
            .map_err(storage)?;
        }
        for extension in &plan.entity_extensions {
            tx.execute(
                "INSERT INTO sync_entity_extensions(entity_type, entity_id, payload_json) VALUES (?1, ?2, ?3)",
                params![extension.entity_type, extension.entity_id, extension.payload_json],
            )
            .map_err(storage)?;
        }
        materialize_parity_sections(&tx, plan)?;

        for section in &plan.opaque_sections {
            tx.execute(
                "INSERT INTO import_opaque_sections(source_digest, section_name, payload_json) VALUES (?1, ?2, ?3)",
                params![plan.receipt.source_digest, section.section_name, section.payload_json],
            )
            .map_err(storage)?;
        }

        advance_lamport_floor(&tx, plan)?;
        tx.commit().map_err(storage)?;

        Ok(ImportApplyReport {
            source_kind: plan.receipt.source_kind,
            workspaces: plan.workspaces.len(),
            boards: plan.boards.len(),
            cards: plan.cards.len(),
            tombstones: plan.tombstones.len(),
            omissions: serde_json::from_str(&plan.receipt.omissions_json).unwrap_or_default(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        application::import::ImportRepository,
        domain::import::{parse_portable_bundle_v1, ImportSourceKind, ImportedBoard, ImportedColumn, ImportedWorkspace},
    };
    use std::{fs, path::PathBuf, sync::atomic::{AtomicU64, Ordering}};

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn temp_profile(name: &str) -> ProfileStoragePaths {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        ProfileStoragePaths::new(std::env::temp_dir().join(format!(
            "p2pkanban-a11-import-{name}-{}-{n}/profiles/default",
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
    fn a11_portable_bundle_import_is_durable_seed_without_local_outbox() {
        let layout = temp_profile("portable");
        cleanup(&layout);
        let raw = include_str!("../../../../fixtures/export/portable-board-bundle-v1.json");
        let plan = parse_portable_bundle_v1(raw).unwrap();
        let digest = plan.receipt.source_digest.clone();
        {
            let mut repository = SqliteImportRepository::open(&layout).unwrap();
            let report = repository.apply_plan(&plan).unwrap();
            assert_eq!(report.cards, 1);
            assert_eq!(
                repository.connection.query_row("SELECT COUNT(*) FROM pending_local_changes", [], |row| row.get::<_, i64>(0)).unwrap(),
                0
            );
        }
        {
            let repository = SqliteImportRepository::open(&layout).unwrap();
            assert_eq!(repository.connection.query_row("SELECT COUNT(*) FROM cards", [], |row| row.get::<_, i64>(0)).unwrap(), 1);
            assert_eq!(repository.connection.query_row("SELECT source_digest FROM import_receipts", [], |row| row.get::<_, String>(0)).unwrap(), digest);
        }
        cleanup(&layout);
    }

    #[test]
    fn a12_portable_parity_sections_materialize_without_local_mutation_markers() {
        let layout = temp_profile("portable-parity");
        cleanup(&layout);
        let raw = include_str!("../../../../fixtures/export/portable-board-bundle-v1-parity.json");
        let plan = parse_portable_bundle_v1(raw).unwrap();
        let mut repository = SqliteImportRepository::open(&layout).unwrap();
        repository.apply_plan(&plan).unwrap();
        for (table, expected) in [
            ("labels", 1_i64),
            ("card_labels", 1),
            ("comments", 1),
            ("board_appearance_settings", 1),
            ("activity_entries", 1),
        ] {
            let count: i64 = repository.connection.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| row.get(0)).unwrap();
            assert_eq!(count, expected, "unexpected {table} count");
        }
        assert_eq!(repository.connection.query_row("SELECT COUNT(*) FROM pending_local_changes", [], |row| row.get::<_, i64>(0)).unwrap(), 0);
        assert_eq!(repository.connection.query_row("SELECT COUNT(*) FROM parity_local_changes", [], |row| row.get::<_, i64>(0)).unwrap(), 0);
        let settings: String = repository.connection.query_row("SELECT settings_json FROM board_appearance_settings", [], |row| row.get(0)).unwrap();
        assert!(settings.contains("violet"));
        cleanup(&layout);
    }

    #[test]
    fn a12_import_rejects_fabricated_activity_provenance() {
        let layout = temp_profile("parity-provenance");
        cleanup(&layout);
        let mut raw: serde_json::Value = serde_json::from_str(include_str!("../../../../fixtures/export/portable-board-bundle-v1-parity.json")).unwrap();
        raw["payload"]["activityEntries"][0].as_object_mut().unwrap().remove("occurredAt");
        let encoded = serde_json::to_string(&raw).unwrap();
        let plan = parse_portable_bundle_v1(&encoded).unwrap();
        let mut repository = SqliteImportRepository::open(&layout).unwrap();
        assert_eq!(repository.apply_plan(&plan), Err(ImportRepositoryError::InvalidScope));
        assert_eq!(repository.connection.query_row("SELECT COUNT(*) FROM import_receipts", [], |row| row.get::<_, i64>(0)).unwrap(), 0);
        cleanup(&layout);
    }

    #[test]
    fn a11_portable_migration_requires_fresh_profile_without_id_remap() {
        let layout = temp_profile("portable-fresh");
        cleanup(&layout);
        let raw = include_str!("../../../../fixtures/export/portable-board-bundle-v1.json");
        let plan = parse_portable_bundle_v1(raw).unwrap();
        assert!(plan.requires_empty_profile);
        let repository = SqliteImportRepository::open(&layout).unwrap();
        repository.connection.execute(
            "INSERT INTO workspaces(id, access_epoch, title) VALUES (?1, '1', 'existing')",
            ["018f0000-0000-7000-8000-000000009901"],
        ).unwrap();
        assert_eq!(repository.preflight(&plan), Err(ImportRepositoryError::DestinationNotEmpty));
        cleanup(&layout);
    }

    #[test]
    fn a11_same_source_digest_is_replay_rejected() {
        let layout = temp_profile("replay");
        cleanup(&layout);
        let raw = include_str!("../../../../fixtures/export/portable-board-bundle-v1.json");
        let plan = parse_portable_bundle_v1(raw).unwrap();
        let mut repository = SqliteImportRepository::open(&layout).unwrap();
        repository.apply_plan(&plan).unwrap();
        assert_eq!(repository.preflight(&plan), Err(ImportRepositoryError::Replay));
        cleanup(&layout);
    }

    #[test]
    fn a11_failed_import_rolls_back_receipt_and_partial_graph() {
        let layout = temp_profile("rollback");
        cleanup(&layout);
        let mut repository = SqliteImportRepository::open(&layout).unwrap();
        let plan = ImportPlan {
            receipt: crate::domain::import::ImportReceiptSpec {
                source_digest: "a".repeat(64),
                source_kind: ImportSourceKind::PortableBundleV1,
                format_version: "1".into(), user_id: None, workspace_id: None, board_id: None, omissions_json: "[]".into(),
            },
            principal: None,
            workspaces: vec![ImportedWorkspace { id: "018f0000-0000-7000-8000-000000001101".into(), title: "ws".into(), access_epoch: 1 }],
            boards: vec![ImportedBoard { id: "018f0000-0000-7000-8000-000000001102".into(), workspace_id: "018f0000-0000-7000-8000-000000001101".into(), title: "board".into() }],
            columns: vec![ImportedColumn { id: "018f0000-0000-7000-8000-000000001103".into(), board_id: "018f0000-0000-7000-8000-000000009999".into(), title: "broken".into(), position: 1.0 }],
            cards: vec![], checklists: vec![], checklist_items: vec![], tombstones: vec![], capabilities: vec![], entity_extensions: vec![], opaque_sections: vec![], requires_empty_profile: false,
        };
        assert_eq!(repository.apply_plan(&plan), Err(ImportRepositoryError::StorageFailure));
        assert_eq!(repository.connection.query_row("SELECT COUNT(*) FROM workspaces", [], |row| row.get::<_, i64>(0)).unwrap(), 0);
        assert_eq!(repository.connection.query_row("SELECT COUNT(*) FROM import_receipts", [], |row| row.get::<_, i64>(0)).unwrap(), 0);
        cleanup(&layout);
    }

    #[test]
    fn a11_import_schema_has_metadata_but_no_secret_columns() {
        let layout = temp_profile("schema");
        cleanup(&layout);
        let repository = SqliteImportRepository::open(&layout).unwrap();
        let text = repository.connection.prepare("SELECT lower(name || ' ' || sql) FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name").unwrap()
            .query_map([], |row| row.get::<_, String>(0)).unwrap()
            .collect::<Result<Vec<_>, _>>().unwrap().join("\n");
        assert!(text.contains("imported_capability_metadata"));
        for forbidden in ["board_key", "device_private_key", "refresh_token", "password_hash", "jwt_secret", "global_master_key"] {
            assert!(!text.contains(forbidden), "secret-bearing schema token leaked: {forbidden}");
        }
        cleanup(&layout);
    }
}
