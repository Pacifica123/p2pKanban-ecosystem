use std::{cmp::Ordering, collections::BTreeSet, time::{SystemTime, UNIX_EPOCH}};

use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::{json, Map, Value};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};
use uuid::Uuid;

use crate::{
    application::sync::{
        SyncApplyReport, SyncMaterializeReport, SyncRepository, SyncRepositoryError,
    },
    domain::{
        planner::VersionStamp,
        sync::{
            canonical_event_digest, stamp_of, validate_roaming_event, RoamingBoardEvent,
            RoamingScope, ROAMING_PROTOCOL_VERSION,
        },
    },
    infrastructure::profile::ProfileStoragePaths,
};

use super::migration::{open_profile, ProfileOpenError};

pub struct SqliteSyncRepository {
    connection: Connection,
}

#[derive(Debug, Clone)]
struct PendingMarker {
    id: String,
    sequence: u64,
    kind: String,
    entity_id: String,
    created_at_unix_ms: i64,
}

impl SqliteSyncRepository {
    pub fn open(layout: &ProfileStoragePaths) -> Result<Self, ProfileOpenError> {
        let (connection, _) = open_profile(layout)?;
        Ok(Self { connection })
    }
}

fn storage_failure<T>(_: T) -> SyncRepositoryError {
    SyncRepositoryError::StorageFailure
}

fn now_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(i64::MAX as u128) as i64)
        .unwrap_or(0)
}

fn rfc3339_from_millis(value: i64) -> Result<String, SyncRepositoryError> {
    if value < 0 {
        return Err(SyncRepositoryError::InvalidEvent);
    }
    let nanos = i128::from(value)
        .checked_mul(1_000_000)
        .ok_or(SyncRepositoryError::InvalidEvent)?;
    OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(storage_failure)?
        .format(&Rfc3339)
        .map_err(storage_failure)
}

fn ensure_scope(conn: &Connection, scope: &RoamingScope) -> Result<(), SyncRepositoryError> {
    let row: Option<(String, String)> = conn
        .query_row(
            "SELECT b.workspace_id, w.access_epoch FROM boards b JOIN workspaces w ON w.id = b.workspace_id WHERE b.id = ?1",
            [scope.board_id.as_str()],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()
        .map_err(storage_failure)?;
    let (workspace_id, epoch) = row.ok_or(SyncRepositoryError::BoardNotFound)?;
    if workspace_id != scope.workspace_id {
        return Err(SyncRepositoryError::ScopeMismatch);
    }
    let epoch = epoch.parse::<u64>().map_err(storage_failure)?;
    if epoch != scope.capability_epoch {
        return Err(SyncRepositoryError::StaleCapabilityEpoch);
    }
    Ok(())
}

fn observe_remote_clock(
    tx: &Transaction<'_>,
    observed: u64,
) -> Result<(), SyncRepositoryError> {
    let current: String = tx
        .query_row(
            "SELECT logical_clock FROM local_mutation_state WHERE singleton = 1",
            [],
            |row| row.get(0),
        )
        .map_err(storage_failure)?;
    let current = current.parse::<u64>().map_err(storage_failure)?;
    if observed > current {
        tx.execute(
            "UPDATE local_mutation_state SET logical_clock = ?1 WHERE singleton = 1",
            [observed.to_string()],
        )
        .map_err(storage_failure)?;
    }
    Ok(())
}

fn local_replica_id(conn: &Connection) -> Result<String, SyncRepositoryError> {
    let origin: String = conn
        .query_row(
            "SELECT origin_id FROM local_mutation_state WHERE singleton = 1",
            [],
            |row| row.get(0),
        )
        .map_err(storage_failure)?;
    if origin.trim().is_empty() {
        return Err(SyncRepositoryError::StorageFailure);
    }
    Ok(origin)
}

fn pending_markers(
    conn: &Connection,
    board_id: &str,
) -> Result<Vec<PendingMarker>, SyncRepositoryError> {
    let mut stmt = conn
        .prepare(
            "SELECT id, sequence, kind, entity_id, created_at_unix_ms FROM pending_local_changes WHERE board_id = ?1 ORDER BY created_at_unix_ms, id",
        )
        .map_err(storage_failure)?;
    let rows = stmt
        .query_map([board_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, i64>(4)?,
            ))
        })
        .map_err(storage_failure)?;
    let mut markers = Vec::new();
    for row in rows {
        let (id, sequence, kind, entity_id, created_at_unix_ms) = row.map_err(storage_failure)?;
        markers.push(PendingMarker {
            id,
            sequence: sequence.parse::<u64>().map_err(storage_failure)?,
            kind,
            entity_id,
            created_at_unix_ms,
        });
    }
    markers.sort_by(|left, right| {
        left.sequence
            .cmp(&right.sequence)
            .then_with(|| left.id.cmp(&right.id))
    });
    Ok(markers)
}

fn load_extension(
    conn: &Connection,
    entity_type: &str,
    entity_id: &str,
) -> Result<Map<String, Value>, SyncRepositoryError> {
    let raw: Option<String> = conn
        .query_row(
            "SELECT payload_json FROM sync_entity_extensions WHERE entity_type = ?1 AND entity_id = ?2",
            params![entity_type, entity_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage_failure)?;
    let Some(raw) = raw else { return Ok(Map::new()); };
    match serde_json::from_str::<Value>(&raw).map_err(storage_failure)? {
        Value::Object(map) => Ok(map),
        _ => Err(SyncRepositoryError::StorageFailure),
    }
}

fn store_extension(
    tx: &Transaction<'_>,
    entity_type: &str,
    entity_id: &str,
    object: &Map<String, Value>,
) -> Result<(), SyncRepositoryError> {
    let payload = serde_json::to_string(&Value::Object(object.clone())).map_err(storage_failure)?;
    tx.execute(
        "INSERT INTO sync_entity_extensions(entity_type, entity_id, payload_json) VALUES (?1, ?2, ?3) ON CONFLICT(entity_type, entity_id) DO UPDATE SET payload_json = excluded.payload_json",
        params![entity_type, entity_id, payload],
    )
    .map_err(storage_failure)?;
    Ok(())
}

fn card_payload(
    conn: &Connection,
    card_id: &str,
    occurred_at: &str,
) -> Result<Value, SyncRepositoryError> {
    let row: Option<(String, String, String, String, f64, String)> = conn
        .query_row(
            "SELECT id, board_id, column_id, title, position, lifecycle FROM cards WHERE id = ?1",
            [card_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?, row.get(5)?)),
        )
        .optional()
        .map_err(storage_failure)?;
    let (id, board_id, column_id, title, position, lifecycle) =
        row.ok_or(SyncRepositoryError::InvalidEvent)?;
    let mut object = load_extension(conn, "card", card_id)?;
    object.insert("id".into(), Value::String(id));
    object.insert("boardId".into(), Value::String(board_id));
    object.insert("columnId".into(), Value::String(column_id));
    object.entry("parentCardId").or_insert(Value::Null);
    object.insert("title".into(), Value::String(title));
    object.entry("description").or_insert(Value::Null);
    object.entry("priority").or_insert(Value::Null);
    object.insert("position".into(), json!(position));
    object.entry("startAt").or_insert(Value::Null);
    object.entry("dueAt").or_insert(Value::Null);
    let archived = lifecycle == "archived";
    object.insert("isArchived".into(), Value::Bool(archived));
    object.entry("labelIds").or_insert_with(|| json!([]));
    object.entry("createdAt").or_insert_with(|| Value::String(occurred_at.to_owned()));
    object.insert("updatedAt".into(), Value::String(occurred_at.to_owned()));
    object.insert(
        "archivedAt".into(),
        if archived { Value::String(occurred_at.to_owned()) } else { Value::Null },
    );
    Ok(Value::Object(object))
}

fn checklist_payload(
    conn: &Connection,
    checklist_id: &str,
    occurred_at: &str,
) -> Result<(String, Value), SyncRepositoryError> {
    let row: Option<(String, String, String, f64)> = conn
        .query_row(
            "SELECT id, card_id, title, position FROM checklists WHERE id = ?1",
            [checklist_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .optional()
        .map_err(storage_failure)?;
    let (id, card_id, title, position) = row.ok_or(SyncRepositoryError::InvalidEvent)?;
    let mut object = load_extension(conn, "checklist", checklist_id)?;
    object.insert("id".into(), Value::String(id));
    object.insert("cardId".into(), Value::String(card_id.clone()));
    object.insert("title".into(), Value::String(title));
    object.insert("position".into(), json!(position));
    object.insert("items".into(), json!([]));
    object.entry("createdAt").or_insert_with(|| Value::String(occurred_at.to_owned()));
    object.insert("updatedAt".into(), Value::String(occurred_at.to_owned()));
    Ok((card_id, Value::Object(object)))
}

fn checklist_item_payload(
    conn: &Connection,
    item_id: &str,
    occurred_at: &str,
) -> Result<(String, String, Value), SyncRepositoryError> {
    let row: Option<(String, String, String, f64, i64)> = conn
        .query_row(
            "SELECT id, checklist_id, title, position, is_done FROM checklist_items WHERE id = ?1",
            [item_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)),
        )
        .optional()
        .map_err(storage_failure)?;
    let (id, checklist_id, title, position, is_done) =
        row.ok_or(SyncRepositoryError::InvalidEvent)?;
    let card_id: String = conn
        .query_row(
            "SELECT card_id FROM checklists WHERE id = ?1",
            [checklist_id.as_str()],
            |row| row.get(0),
        )
        .map_err(storage_failure)?;
    let mut object = load_extension(conn, "checklist_item", item_id)?;
    object.insert("id".into(), Value::String(id));
    object.insert("checklistId".into(), Value::String(checklist_id.clone()));
    object.insert("title".into(), Value::String(title));
    object.insert("position".into(), json!(position));
    object.insert("isDone".into(), Value::Bool(is_done != 0));
    object.insert(
        "completedAt".into(),
        if is_done != 0 { Value::String(occurred_at.to_owned()) } else { Value::Null },
    );
    object.entry("createdAt").or_insert_with(|| Value::String(occurred_at.to_owned()));
    object.insert("updatedAt".into(), Value::String(occurred_at.to_owned()));
    Ok((card_id, checklist_id, Value::Object(object)))
}

fn appearance_payload(
    conn: &Connection,
    board_id: &str,
) -> Result<Value, SyncRepositoryError> {
    let raw: Option<String> = conn
        .query_row(
            "SELECT settings_json FROM board_appearance_settings WHERE board_id = ?1",
            [board_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage_failure)?;
    let raw = raw.ok_or(SyncRepositoryError::InvalidEvent)?;
    let value: Value = serde_json::from_str(&raw).map_err(storage_failure)?;
    let object = value.as_object().ok_or(SyncRepositoryError::InvalidEvent)?;
    if object.get("boardId").and_then(Value::as_str) != Some(board_id) {
        return Err(SyncRepositoryError::ScopeMismatch);
    }
    Ok(value)
}

fn event(
    scope: &RoamingScope,
    event_id: String,
    replica_id: &str,
    sequence: u64,
    entity_type: &str,
    entity_id: String,
    operation: &str,
    field_mask: Vec<&str>,
    payload: Value,
    occurred_at: &str,
) -> RoamingBoardEvent {
    RoamingBoardEvent {
        protocol_version: ROAMING_PROTOCOL_VERSION.to_owned(),
        event_id,
        workspace_id: scope.workspace_id.clone(),
        board_id: scope.board_id.clone(),
        capability_epoch: scope.capability_epoch,
        replica_id: replica_id.to_owned(),
        replica_seq: sequence,
        logical_clock: sequence,
        entity_type: entity_type.to_owned(),
        entity_id,
        operation: operation.to_owned(),
        field_mask: field_mask.into_iter().map(str::to_owned).collect(),
        payload,
        occurred_at: occurred_at.to_owned(),
    }
}

fn events_for_marker(
    tx: &Transaction<'_>,
    scope: &RoamingScope,
    replica_id: &str,
    marker: &PendingMarker,
) -> Result<Vec<RoamingBoardEvent>, SyncRepositoryError> {
    let occurred_at = rfc3339_from_millis(marker.created_at_unix_ms)?;
    let card_event = |field_mask: Vec<&str>, payload: Value| {
        event(
            scope,
            marker.id.clone(),
            replica_id,
            marker.sequence,
            "card",
            marker.entity_id.clone(),
            "card.put",
            field_mask,
            payload,
            &occurred_at,
        )
    };
    match marker.kind.as_str() {
        "card.create" => Ok(vec![card_event(
            vec!["*"],
            json!({"card": card_payload(tx, &marker.entity_id, &occurred_at)?}),
        )]),
        "card.move" => Ok(vec![card_event(
            vec!["columnId", "position", "updatedAt"],
            json!({"card": card_payload(tx, &marker.entity_id, &occurred_at)?}),
        )]),
        "card.archive" | "card.unarchive" => Ok(vec![card_event(
            vec!["isArchived", "archivedAt", "updatedAt"],
            json!({"card": card_payload(tx, &marker.entity_id, &occurred_at)?}),
        )]),
        "card.delete" => Ok(vec![event(
            scope,
            marker.id.clone(),
            replica_id,
            marker.sequence,
            "card",
            marker.entity_id.clone(),
            "card.delete",
            vec!["__lifecycle"],
            json!({"deletedAt": occurred_at}),
            &occurred_at,
        )]),
        "card.reorder" => {
            let mut stmt = tx
                .prepare(
                    "SELECT id FROM cards WHERE board_id = ?1 AND column_id = ?2 ORDER BY position, id",
                )
                .map_err(storage_failure)?;
            let ids = stmt
                .query_map(params![scope.board_id, marker.entity_id], |row| row.get::<_, String>(0))
                .map_err(storage_failure)?
                .collect::<Result<Vec<_>, _>>()
                .map_err(storage_failure)?;
            let mut values = Vec::new();
            for card_id in ids {
                values.push(event(
                    scope,
                    Uuid::new_v4().to_string(),
                    replica_id,
                    marker.sequence,
                    "card",
                    card_id.clone(),
                    "card.put",
                    vec!["position", "updatedAt"],
                    json!({"card": card_payload(tx, &card_id, &occurred_at)?}),
                    &occurred_at,
                ));
            }
            Ok(values)
        }
        "board.appearance.put" => Ok(vec![event(
            scope,
            marker.id.clone(),
            replica_id,
            marker.sequence,
            "board",
            scope.board_id.clone(),
            "board.appearance.put",
            vec!["appearance"],
            json!({"appearance": appearance_payload(tx, &scope.board_id)?}),
            &occurred_at,
        )]),
        "checklist.create" => {
            let (card_id, checklist) = checklist_payload(tx, &marker.entity_id, &occurred_at)?;
            Ok(vec![event(
                scope,
                marker.id.clone(),
                replica_id,
                marker.sequence,
                "card",
                card_id.clone(),
                "card.put",
                vec!["checklists"],
                json!({
                    "card": card_payload(tx, &card_id, &occurred_at)?,
                    "checklistDelta": {
                        "kind": "checklist.put",
                        "cardId": card_id,
                        "checklistId": marker.entity_id,
                        "fieldMask": ["*"],
                        "checklist": checklist
                    }
                }),
                &occurred_at,
            )])
        }
        "checklist.item.create" | "checklist.item.update" => {
            let (card_id, checklist_id, item) = checklist_item_payload(tx, &marker.entity_id, &occurred_at)?;
            let fields = if marker.kind == "checklist.item.create" {
                json!(["*"])
            } else {
                json!(["isDone"])
            };
            Ok(vec![event(
                scope,
                marker.id.clone(),
                replica_id,
                marker.sequence,
                "card",
                card_id.clone(),
                "card.put",
                vec!["checklists"],
                json!({
                    "card": card_payload(tx, &card_id, &occurred_at)?,
                    "checklistDelta": {
                        "kind": "checklist_item.put",
                        "cardId": card_id,
                        "checklistId": checklist_id,
                        "itemId": marker.entity_id,
                        "fieldMask": fields,
                        "item": item
                    }
                }),
                &occurred_at,
            )])
        }
        "checklist.delete" => {
            let row: Option<(String, String)> = tx
                .query_row(
                    "SELECT card_id, checklist_id FROM checklist_tombstones WHERE checklist_id = ?1 AND board_id = ?2",
                    params![marker.entity_id, scope.board_id],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .optional()
                .map_err(storage_failure)?;
            let (card_id, checklist_id) = row.ok_or(SyncRepositoryError::InvalidEvent)?;
            Ok(vec![event(
                scope,
                marker.id.clone(),
                replica_id,
                marker.sequence,
                "card",
                card_id.clone(),
                "card.put",
                vec!["checklists"],
                json!({
                    "card": card_payload(tx, &card_id, &occurred_at)?,
                    "checklistDelta": {
                        "kind": "checklist.delete",
                        "cardId": card_id,
                        "checklistId": checklist_id,
                        "fieldMask": ["__lifecycle"],
                        "deletedAt": occurred_at
                    }
                }),
                &occurred_at,
            )])
        }
        "checklist.item.delete" => {
            let row: Option<(String, String, String)> = tx
                .query_row(
                    "SELECT card_id, checklist_id, item_id FROM checklist_item_tombstones WHERE item_id = ?1 AND board_id = ?2",
                    params![marker.entity_id, scope.board_id],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                )
                .optional()
                .map_err(storage_failure)?;
            let (card_id, checklist_id, item_id) = row.ok_or(SyncRepositoryError::InvalidEvent)?;
            Ok(vec![event(
                scope,
                marker.id.clone(),
                replica_id,
                marker.sequence,
                "card",
                card_id.clone(),
                "card.put",
                vec!["checklists"],
                json!({
                    "card": card_payload(tx, &card_id, &occurred_at)?,
                    "checklistDelta": {
                        "kind": "checklist_item.delete",
                        "cardId": card_id,
                        "checklistId": checklist_id,
                        "itemId": item_id,
                        "fieldMask": ["__lifecycle"],
                        "deletedAt": occurred_at
                    }
                }),
                &occurred_at,
            )])
        }
        other => Err(SyncRepositoryError::UnsupportedPendingKind(other.to_owned())),
    }
}

fn insert_outbox(
    tx: &Transaction<'_>,
    source_change_id: &str,
    event: &RoamingBoardEvent,
    created_at_unix_ms: i64,
) -> Result<(), SyncRepositoryError> {
    let field_mask = serde_json::to_string(&event.field_mask).map_err(storage_failure)?;
    let payload = serde_json::to_string(&event.payload).map_err(storage_failure)?;
    tx.execute(
        "INSERT INTO sync_outbox(event_id, source_change_id, workspace_id, board_id, protocol_version, capability_epoch, replica_id, replica_seq, logical_clock, entity_type, entity_id, operation, field_mask_json, payload_json, occurred_at, state, created_at_unix_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, 'pending', ?16)",
        params![
            event.event_id,
            source_change_id,
            event.workspace_id,
            event.board_id,
            event.protocol_version,
            event.capability_epoch.to_string(),
            event.replica_id,
            event.replica_seq.to_string(),
            event.logical_clock.to_string(),
            event.entity_type,
            event.entity_id,
            event.operation,
            field_mask,
            payload,
            event.occurred_at,
            created_at_unix_ms,
        ],
    )
    .map_err(storage_failure)?;
    Ok(())
}

fn record_local_event_versions(
    tx: &Transaction<'_>,
    scope: &RoamingScope,
    event: &RoamingBoardEvent,
) -> Result<(), SyncRepositoryError> {
    let version = stamp_of(event)?;
    match event.operation.as_str() {
        "card.delete" => {
            let current = card_tombstone(tx, &event.entity_id)?;
            if current.as_ref().is_none_or(|value| &version >= value) {
                tx.execute(
                    "INSERT INTO card_tombstones(card_id, workspace_id, board_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6) ON CONFLICT(card_id) DO UPDATE SET workspace_id=excluded.workspace_id, board_id=excluded.board_id, logical_clock=excluded.logical_clock, replica_id=excluded.replica_id, event_id=excluded.event_id",
                    params![event.entity_id, scope.workspace_id, scope.board_id, version.logical_clock.to_string(), version.replica_id, version.event_id],
                ).map_err(storage_failure)?;
            }
            save_version(tx, &scope.board_id, &event.entity_id, "__lifecycle", &version)?;
        }
        "card.put" => {
            save_version(tx, &scope.board_id, &event.entity_id, "checklists", &version)?;
            if let Some(delta) = event.payload.get("checklistDelta").and_then(Value::as_object) {
                let kind = value_string(delta, "kind")?;
                match kind.as_str() {
                    "checklist.delete" => {
                        let checklist_id = value_string(delta, "checklistId")?;
                        save_version(tx, &scope.board_id, &checklist_id, "checklist.__lifecycle", &version)?;
                    }
                    "checklist.put" => {
                        let checklist_id = value_string(delta, "checklistId")?;
                        let fields = delta.get("fieldMask").and_then(Value::as_array)
                            .ok_or(SyncRepositoryError::InvalidEvent)?;
                        let all = fields.iter().any(|value| value.as_str() == Some("*"));
                        if all {
                            for field in ["checklist.__lifecycle", "checklist.title", "checklist.position"] {
                                save_version(tx, &scope.board_id, &checklist_id, field, &version)?;
                            }
                        } else {
                            for raw in fields {
                                let field = raw.as_str().ok_or(SyncRepositoryError::InvalidEvent)?;
                                save_version(tx, &scope.board_id, &checklist_id, &format!("checklist.{field}"), &version)?;
                            }
                        }
                    }
                    "checklist_item.delete" => {
                        let item_id = value_string(delta, "itemId")?;
                        save_version(tx, &scope.board_id, &item_id, "checklist_item.__lifecycle", &version)?;
                    }
                    "checklist_item.put" => {
                        let item_id = value_string(delta, "itemId")?;
                        let fields = delta.get("fieldMask").and_then(Value::as_array)
                            .ok_or(SyncRepositoryError::InvalidEvent)?;
                        let all = fields.iter().any(|value| value.as_str() == Some("*"));
                        if all {
                            for field in ["checklist_item.__lifecycle", "checklist_item.title", "checklist_item.position", "checklist_item.isDone"] {
                                save_version(tx, &scope.board_id, &item_id, field, &version)?;
                            }
                        } else {
                            for raw in fields {
                                let field = raw.as_str().ok_or(SyncRepositoryError::InvalidEvent)?;
                                save_version(tx, &scope.board_id, &item_id, &format!("checklist_item.{field}"), &version)?;
                            }
                        }
                    }
                    _ => return Err(SyncRepositoryError::InvalidEvent),
                }
            } else {
                let incoming = event.payload.get("card").and_then(Value::as_object)
                    .ok_or(SyncRepositoryError::InvalidEvent)?;
                let fields = if event.field_mask.iter().any(|field| field == "*") {
                    incoming.keys().cloned().collect::<Vec<_>>()
                } else {
                    event.field_mask.clone()
                };
                for field in fields {
                    save_version(tx, &scope.board_id, &event.entity_id, &field, &version)?;
                }
            }
        }
        "board.appearance.put" => {
            save_version(tx, &scope.board_id, &scope.board_id, "appearance", &version)?;
        }
        _ => {}
    }
    Ok(())
}

fn stored_version(
    tx: &Transaction<'_>,
    board_id: &str,
    entity_id: &str,
    field: &str,
) -> Result<Option<VersionStamp>, SyncRepositoryError> {
    let raw: Option<(String, String, String)> = tx
        .query_row(
            "SELECT logical_clock, replica_id, event_id FROM sync_field_versions WHERE board_id = ?1 AND entity_id = ?2 AND field_name = ?3",
            params![board_id, entity_id, field],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()
        .map_err(storage_failure)?;
    raw.map(|(clock, replica, event)| {
        VersionStamp::new(clock.parse::<u64>().map_err(storage_failure)?, replica, event)
            .map_err(storage_failure)
    })
    .transpose()
}

fn event_wins(
    tx: &Transaction<'_>,
    board_id: &str,
    entity_id: &str,
    field: &str,
    candidate: &VersionStamp,
) -> Result<bool, SyncRepositoryError> {
    Ok(stored_version(tx, board_id, entity_id, field)?
        .is_none_or(|current| candidate > &current))
}

fn save_version(
    tx: &Transaction<'_>,
    board_id: &str,
    entity_id: &str,
    field: &str,
    version: &VersionStamp,
) -> Result<(), SyncRepositoryError> {
    tx.execute(
        "INSERT INTO sync_field_versions(board_id, entity_id, field_name, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6) ON CONFLICT(board_id, entity_id, field_name) DO UPDATE SET logical_clock = excluded.logical_clock, replica_id = excluded.replica_id, event_id = excluded.event_id",
        params![board_id, entity_id, field, version.logical_clock.to_string(), version.replica_id, version.event_id],
    )
    .map_err(storage_failure)?;
    Ok(())
}

fn card_tombstone(
    tx: &Transaction<'_>,
    card_id: &str,
) -> Result<Option<VersionStamp>, SyncRepositoryError> {
    let raw: Option<(String, String, String)> = tx
        .query_row(
            "SELECT logical_clock, replica_id, event_id FROM card_tombstones WHERE card_id = ?1",
            [card_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()
        .map_err(storage_failure)?;
    raw.map(|(clock, replica, event)| {
        VersionStamp::new(clock.parse::<u64>().map_err(storage_failure)?, replica, event)
            .map_err(storage_failure)
    })
    .transpose()
}

fn value_string(object: &Map<String, Value>, key: &str) -> Result<String, SyncRepositoryError> {
    object.get(key).and_then(Value::as_str).map(str::to_owned).ok_or(SyncRepositoryError::InvalidEvent)
}

fn value_f64(object: &Map<String, Value>, key: &str) -> Result<f64, SyncRepositoryError> {
    let value = object.get(key).and_then(Value::as_f64).ok_or(SyncRepositoryError::InvalidEvent)?;
    if !value.is_finite() { return Err(SyncRepositoryError::InvalidEvent); }
    Ok(value)
}

fn value_bool(object: &Map<String, Value>, key: &str) -> Result<bool, SyncRepositoryError> {
    object.get(key).and_then(Value::as_bool).ok_or(SyncRepositoryError::InvalidEvent)
}

fn column_in_board(tx: &Transaction<'_>, column_id: &str, board_id: &str) -> Result<bool, SyncRepositoryError> {
    tx.query_row(
        "SELECT 1 FROM columns WHERE id = ?1 AND board_id = ?2",
        params![column_id, board_id],
        |_| Ok(()),
    )
    .optional()
    .map(|row| row.is_some())
    .map_err(storage_failure)
}

fn apply_checklist_delta(
    tx: &Transaction<'_>,
    scope: &RoamingScope,
    event: &RoamingBoardEvent,
    candidate: &VersionStamp,
    delta: &Map<String, Value>,
) -> Result<bool, SyncRepositoryError> {
    let kind = value_string(delta, "kind")?;
    let card_id = value_string(delta, "cardId")?;
    if card_id != event.entity_id {
        return Err(SyncRepositoryError::InvalidEvent);
    }
    let card_exists = tx
        .query_row(
            "SELECT 1 FROM cards WHERE id = ?1 AND board_id = ?2",
            params![card_id, scope.board_id],
            |_| Ok(()),
        )
        .optional()
        .map_err(storage_failure)?
        .is_some();
    if !card_exists {
        return Ok(false);
    }
    let fields = delta
        .get("fieldMask")
        .and_then(Value::as_array)
        .ok_or(SyncRepositoryError::InvalidEvent)?
        .iter()
        .map(|value| value.as_str().map(str::to_owned).ok_or(SyncRepositoryError::InvalidEvent))
        .collect::<Result<Vec<_>, _>>()?;
    let all_fields = fields.iter().any(|field| field == "*");
    let wants = |field: &str| all_fields || fields.iter().any(|candidate| candidate == field);

    match kind.as_str() {
        "checklist.delete" => {
            let checklist_id = value_string(delta, "checklistId")?;
            if !event_wins(tx, &scope.board_id, &checklist_id, "checklist.__lifecycle", candidate)? {
                return Ok(false);
            }
            tx.execute("DELETE FROM checklists WHERE id = ?1", [checklist_id.as_str()])
                .map_err(storage_failure)?;
            tx.execute(
                "INSERT INTO checklist_tombstones(checklist_id, workspace_id, board_id, card_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7) ON CONFLICT(checklist_id) DO UPDATE SET workspace_id = excluded.workspace_id, board_id = excluded.board_id, card_id = excluded.card_id, logical_clock = excluded.logical_clock, replica_id = excluded.replica_id, event_id = excluded.event_id",
                params![checklist_id, scope.workspace_id, scope.board_id, card_id, candidate.logical_clock.to_string(), candidate.replica_id, candidate.event_id],
            )
            .map_err(storage_failure)?;
            save_version(tx, &scope.board_id, &checklist_id, "checklist.__lifecycle", candidate)?;
            Ok(true)
        }
        "checklist.put" => {
            let checklist_id = value_string(delta, "checklistId")?;
            let incoming = delta.get("checklist").and_then(Value::as_object).ok_or(SyncRepositoryError::InvalidEvent)?;
            if value_string(incoming, "id")? != checklist_id || value_string(incoming, "cardId")? != card_id {
                return Err(SyncRepositoryError::InvalidEvent);
            }
            let tombstone: Option<(String, String, String)> = tx
                .query_row(
                    "SELECT logical_clock, replica_id, event_id FROM checklist_tombstones WHERE checklist_id = ?1",
                    [checklist_id.as_str()],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                )
                .optional()
                .map_err(storage_failure)?;
            if let Some((clock, replica, id)) = tombstone {
                let tomb = VersionStamp::new(clock.parse::<u64>().map_err(storage_failure)?, replica, id).map_err(storage_failure)?;
                if !all_fields || candidate <= &tomb {
                    return Ok(false);
                }
            }
            let exists = tx
                .query_row("SELECT 1 FROM checklists WHERE id = ?1", [checklist_id.as_str()], |_| Ok(()))
                .optional().map_err(storage_failure)?.is_some();
            let mut changed = false;
            if !exists {
                if !event_wins(tx, &scope.board_id, &checklist_id, "checklist.__lifecycle", candidate)? {
                    return Ok(false);
                }
                let title = value_string(incoming, "title")?;
                let position = value_f64(incoming, "position")?;
                tx.execute(
                    "INSERT INTO checklists(id, workspace_id, board_id, card_id, title, position) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                    params![checklist_id, scope.workspace_id, scope.board_id, card_id, title, position],
                ).map_err(storage_failure)?;
                for field in ["checklist.__lifecycle", "checklist.title", "checklist.position"] {
                    save_version(tx, &scope.board_id, &checklist_id, field, candidate)?;
                }
                tx.execute("DELETE FROM checklist_tombstones WHERE checklist_id = ?1", [checklist_id.as_str()]).map_err(storage_failure)?;
                changed = true;
            } else {
                if wants("title") && event_wins(tx, &scope.board_id, &checklist_id, "checklist.title", candidate)? {
                    let title = value_string(incoming, "title")?;
                    tx.execute("UPDATE checklists SET title = ?1 WHERE id = ?2", params![title, checklist_id]).map_err(storage_failure)?;
                    save_version(tx, &scope.board_id, &checklist_id, "checklist.title", candidate)?;
                    changed = true;
                }
                if wants("position") && event_wins(tx, &scope.board_id, &checklist_id, "checklist.position", candidate)? {
                    let position = value_f64(incoming, "position")?;
                    tx.execute("UPDATE checklists SET position = ?1 WHERE id = ?2", params![position, checklist_id]).map_err(storage_failure)?;
                    save_version(tx, &scope.board_id, &checklist_id, "checklist.position", candidate)?;
                    changed = true;
                }
                if all_fields && event_wins(tx, &scope.board_id, &checklist_id, "checklist.__lifecycle", candidate)? {
                    save_version(tx, &scope.board_id, &checklist_id, "checklist.__lifecycle", candidate)?;
                    tx.execute("DELETE FROM checklist_tombstones WHERE checklist_id = ?1", [checklist_id.as_str()]).map_err(storage_failure)?;
                }
            }
            store_extension(tx, "checklist", &checklist_id, incoming)?;
            Ok(changed)
        }
        "checklist_item.delete" => {
            let checklist_id = value_string(delta, "checklistId")?;
            let item_id = value_string(delta, "itemId")?;
            if !event_wins(tx, &scope.board_id, &item_id, "checklist_item.__lifecycle", candidate)? {
                return Ok(false);
            }
            tx.execute("DELETE FROM checklist_items WHERE id = ?1", [item_id.as_str()]).map_err(storage_failure)?;
            tx.execute(
                "INSERT INTO checklist_item_tombstones(item_id, workspace_id, board_id, card_id, checklist_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8) ON CONFLICT(item_id) DO UPDATE SET workspace_id = excluded.workspace_id, board_id = excluded.board_id, card_id = excluded.card_id, checklist_id = excluded.checklist_id, logical_clock = excluded.logical_clock, replica_id = excluded.replica_id, event_id = excluded.event_id",
                params![item_id, scope.workspace_id, scope.board_id, card_id, checklist_id, candidate.logical_clock.to_string(), candidate.replica_id, candidate.event_id],
            ).map_err(storage_failure)?;
            save_version(tx, &scope.board_id, &item_id, "checklist_item.__lifecycle", candidate)?;
            Ok(true)
        }
        "checklist_item.put" => {
            let checklist_id = value_string(delta, "checklistId")?;
            let item_id = value_string(delta, "itemId")?;
            let incoming = delta.get("item").and_then(Value::as_object).ok_or(SyncRepositoryError::InvalidEvent)?;
            if value_string(incoming, "id")? != item_id || value_string(incoming, "checklistId")? != checklist_id {
                return Err(SyncRepositoryError::InvalidEvent);
            }
            let checklist_exists = tx.query_row(
                "SELECT 1 FROM checklists WHERE id = ?1 AND card_id = ?2",
                params![checklist_id, card_id], |_| Ok(())
            ).optional().map_err(storage_failure)?.is_some();
            if !checklist_exists { return Ok(false); }
            let checklist_deleted = tx.query_row(
                "SELECT 1 FROM checklist_tombstones WHERE checklist_id = ?1",
                [checklist_id.as_str()], |_| Ok(())
            ).optional().map_err(storage_failure)?.is_some();
            if checklist_deleted { return Ok(false); }
            let tombstone: Option<(String, String, String)> = tx.query_row(
                "SELECT logical_clock, replica_id, event_id FROM checklist_item_tombstones WHERE item_id = ?1",
                [item_id.as_str()], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?))
            ).optional().map_err(storage_failure)?;
            if let Some((clock, replica, id)) = tombstone {
                let tomb = VersionStamp::new(clock.parse::<u64>().map_err(storage_failure)?, replica, id).map_err(storage_failure)?;
                if !all_fields || candidate <= &tomb { return Ok(false); }
            }
            let exists = tx.query_row("SELECT 1 FROM checklist_items WHERE id = ?1", [item_id.as_str()], |_| Ok(()))
                .optional().map_err(storage_failure)?.is_some();
            let mut changed = false;
            if !exists {
                if !event_wins(tx, &scope.board_id, &item_id, "checklist_item.__lifecycle", candidate)? { return Ok(false); }
                let title=value_string(incoming,"title")?;
                let position=value_f64(incoming,"position")?;
                let done=value_bool(incoming,"isDone")?;
                tx.execute(
                    "INSERT INTO checklist_items(id, checklist_id, title, position, is_done) VALUES (?1, ?2, ?3, ?4, ?5)",
                    params![item_id, checklist_id, title, position, if done {1} else {0}],
                ).map_err(storage_failure)?;
                for field in ["checklist_item.__lifecycle","checklist_item.title","checklist_item.position","checklist_item.isDone"] {
                    save_version(tx,&scope.board_id,&item_id,field,candidate)?;
                }
                tx.execute("DELETE FROM checklist_item_tombstones WHERE item_id = ?1", [item_id.as_str()]).map_err(storage_failure)?;
                changed=true;
            } else {
                if wants("title") && event_wins(tx,&scope.board_id,&item_id,"checklist_item.title",candidate)? {
                    let title=value_string(incoming,"title")?;
                    tx.execute("UPDATE checklist_items SET title = ?1 WHERE id = ?2",params![title,item_id]).map_err(storage_failure)?;
                    save_version(tx,&scope.board_id,&item_id,"checklist_item.title",candidate)?; changed=true;
                }
                if wants("position") && event_wins(tx,&scope.board_id,&item_id,"checklist_item.position",candidate)? {
                    let position=value_f64(incoming,"position")?;
                    tx.execute("UPDATE checklist_items SET position = ?1 WHERE id = ?2",params![position,item_id]).map_err(storage_failure)?;
                    save_version(tx,&scope.board_id,&item_id,"checklist_item.position",candidate)?; changed=true;
                }
                if wants("isDone") && event_wins(tx,&scope.board_id,&item_id,"checklist_item.isDone",candidate)? {
                    let done=value_bool(incoming,"isDone")?;
                    tx.execute("UPDATE checklist_items SET is_done = ?1 WHERE id = ?2",params![if done {1}else{0},item_id]).map_err(storage_failure)?;
                    save_version(tx,&scope.board_id,&item_id,"checklist_item.isDone",candidate)?; changed=true;
                }
                if all_fields && event_wins(tx,&scope.board_id,&item_id,"checklist_item.__lifecycle",candidate)? {
                    save_version(tx,&scope.board_id,&item_id,"checklist_item.__lifecycle",candidate)?;
                    tx.execute("DELETE FROM checklist_item_tombstones WHERE item_id = ?1",[item_id.as_str()]).map_err(storage_failure)?;
                }
            }
            store_extension(tx,"checklist_item",&item_id,incoming)?;
            Ok(changed)
        }
        _ => Err(SyncRepositoryError::InvalidEvent),
    }
}

fn apply_board_snapshot(
    tx: &Transaction<'_>,
    scope: &RoamingScope,
    event: &RoamingBoardEvent,
    candidate: &VersionStamp,
) -> Result<bool, SyncRepositoryError> {
    let snapshot = event.payload.get("snapshot").and_then(Value::as_object)
        .ok_or(SyncRepositoryError::InvalidEvent)?;
    if value_string(snapshot, "workspaceId")? != scope.workspace_id {
        return Err(SyncRepositoryError::ScopeMismatch);
    }
    let board = snapshot.get("board").and_then(Value::as_object)
        .ok_or(SyncRepositoryError::InvalidEvent)?;
    if value_string(board, "id")? != scope.board_id {
        return Err(SyncRepositoryError::ScopeMismatch);
    }

    // Android roaming/1 seeds a snapshot only when no current snapshot exists. Native mirrors
    // that contract: an already-populated planner is not overwritten by a later board.snapshot.
    let local_content: i64 = tx.query_row(
        "SELECT (SELECT COUNT(*) FROM columns WHERE board_id=?1) + (SELECT COUNT(*) FROM cards WHERE board_id=?1)",
        [scope.board_id.as_str()], |row| row.get(0),
    ).map_err(storage_failure)?;
    if local_content != 0 {
        return Ok(false);
    }

    if let Some(name) = board.get("name").and_then(Value::as_str) {
        tx.execute("UPDATE boards SET title=?1 WHERE id=?2", params![name, scope.board_id])
            .map_err(storage_failure)?;
    }
    store_extension(tx, "board", &scope.board_id, board)?;

    if let Some(appearance) = snapshot.get("appearance").and_then(Value::as_object) {
        if appearance.get("boardId").and_then(Value::as_str) != Some(scope.board_id.as_str()) {
            return Err(SyncRepositoryError::ScopeMismatch);
        }
        let settings_json = serde_json::to_string(&Value::Object(appearance.clone())).map_err(storage_failure)?;
        tx.execute(
            "INSERT INTO board_appearance_settings(board_id, settings_json, updated_at) VALUES (?1, ?2, ?3) ON CONFLICT(board_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at",
            params![scope.board_id, settings_json, event.occurred_at],
        ).map_err(storage_failure)?;
        save_version(tx, &scope.board_id, &scope.board_id, "appearance", candidate)?;
    }

    let columns = snapshot.get("columns").and_then(Value::as_array)
        .ok_or(SyncRepositoryError::InvalidEvent)?;
    for value in columns {
        let column = value.as_object().ok_or(SyncRepositoryError::InvalidEvent)?;
        let id = value_string(column, "id")?;
        if value_string(column, "boardId")? != scope.board_id {
            return Err(SyncRepositoryError::ScopeMismatch);
        }
        let title = value_string(column, "name")?;
        let position = value_f64(column, "position")?;
        tx.execute(
            "INSERT INTO columns(id, board_id, title, position) VALUES (?1, ?2, ?3, ?4)",
            params![id, scope.board_id, title, position],
        ).map_err(storage_failure)?;
        store_extension(tx, "column", &id, column)?;
    }

    let cards = snapshot.get("cards").and_then(Value::as_array)
        .ok_or(SyncRepositoryError::InvalidEvent)?;
    for value in cards {
        let card = value.as_object().ok_or(SyncRepositoryError::InvalidEvent)?;
        let card_id = value_string(card, "id")?;
        if value_string(card, "boardId")? != scope.board_id {
            return Err(SyncRepositoryError::ScopeMismatch);
        }
        if card_tombstone(tx, &card_id)?.is_some() {
            continue;
        }
        let column_id = value_string(card, "columnId")?;
        if !column_in_board(tx, &column_id, &scope.board_id)? {
            return Err(SyncRepositoryError::InvalidEvent);
        }
        let title = value_string(card, "title")?;
        let position = value_f64(card, "position")?;
        let archived = value_bool(card, "isArchived")?;
        tx.execute(
            "INSERT INTO cards(id, workspace_id, board_id, column_id, title, position, lifecycle) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![card_id, scope.workspace_id, scope.board_id, column_id, title, position, if archived {"archived"} else {"active"}],
        ).map_err(storage_failure)?;
        store_extension(tx, "card", &card_id, card)?;
        for field in card.keys() {
            save_version(tx, &scope.board_id, &card_id, field, candidate)?;
        }
        save_version(tx, &scope.board_id, &card_id, "checklists", candidate)?;
    }

    let checklists = snapshot.get("checklistsByCardId").and_then(Value::as_object)
        .ok_or(SyncRepositoryError::InvalidEvent)?;
    for (card_id, raw_lists) in checklists {
        let card_exists = tx.query_row(
            "SELECT 1 FROM cards WHERE id=?1 AND board_id=?2",
            params![card_id, scope.board_id], |_| Ok(()),
        ).optional().map_err(storage_failure)?.is_some();
        if !card_exists { continue; }
        let lists = raw_lists.as_array().ok_or(SyncRepositoryError::InvalidEvent)?;
        for raw in lists {
            let checklist = raw.as_object().ok_or(SyncRepositoryError::InvalidEvent)?;
            let checklist_id = value_string(checklist, "id")?;
            if value_string(checklist, "cardId")? != card_id.as_str() { return Err(SyncRepositoryError::ScopeMismatch); }
            let tombstoned = tx.query_row(
                "SELECT 1 FROM checklist_tombstones WHERE checklist_id=?1",
                [checklist_id.as_str()], |_| Ok(()),
            ).optional().map_err(storage_failure)?.is_some();
            if tombstoned { continue; }
            let title = value_string(checklist, "title")?;
            let position = value_f64(checklist, "position")?;
            tx.execute(
                "INSERT INTO checklists(id, workspace_id, board_id, card_id, title, position) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![checklist_id, scope.workspace_id, scope.board_id, card_id, title, position],
            ).map_err(storage_failure)?;
            store_extension(tx, "checklist", &checklist_id, checklist)?;
            for field in ["checklist.__lifecycle", "checklist.title", "checklist.position"] {
                save_version(tx, &scope.board_id, &checklist_id, field, candidate)?;
            }
            let items = checklist.get("items").and_then(Value::as_array)
                .ok_or(SyncRepositoryError::InvalidEvent)?;
            for raw_item in items {
                let item = raw_item.as_object().ok_or(SyncRepositoryError::InvalidEvent)?;
                let item_id = value_string(item, "id")?;
                if value_string(item, "checklistId")? != checklist_id.as_str() { return Err(SyncRepositoryError::ScopeMismatch); }
                let item_tombstoned = tx.query_row(
                    "SELECT 1 FROM checklist_item_tombstones WHERE item_id=?1",
                    [item_id.as_str()], |_| Ok(()),
                ).optional().map_err(storage_failure)?.is_some();
                if item_tombstoned { continue; }
                let item_title = value_string(item, "title")?;
                let item_position = value_f64(item, "position")?;
                let done = value_bool(item, "isDone")?;
                tx.execute(
                    "INSERT INTO checklist_items(id, checklist_id, title, position, is_done) VALUES (?1, ?2, ?3, ?4, ?5)",
                    params![item_id, checklist_id, item_title, item_position, if done {1} else {0}],
                ).map_err(storage_failure)?;
                store_extension(tx, "checklist_item", &item_id, item)?;
                for field in ["checklist_item.__lifecycle", "checklist_item.title", "checklist_item.position", "checklist_item.isDone"] {
                    save_version(tx, &scope.board_id, &item_id, field, candidate)?;
                }
            }
        }
    }
    Ok(true)
}

fn apply_board_appearance(
    tx: &Transaction<'_>,
    scope: &RoamingScope,
    event: &RoamingBoardEvent,
    candidate: &VersionStamp,
) -> Result<bool, SyncRepositoryError> {
    if !event_wins(tx, &scope.board_id, &scope.board_id, "appearance", candidate)? {
        return Ok(false);
    }
    let appearance = event
        .payload
        .get("appearance")
        .and_then(Value::as_object)
        .ok_or(SyncRepositoryError::InvalidEvent)?;
    if appearance.get("boardId").and_then(Value::as_str) != Some(scope.board_id.as_str()) {
        return Err(SyncRepositoryError::ScopeMismatch);
    }
    let settings_json = serde_json::to_string(&Value::Object(appearance.clone())).map_err(storage_failure)?;
    tx.execute(
        "INSERT INTO board_appearance_settings(board_id, settings_json, updated_at) VALUES (?1, ?2, ?3) ON CONFLICT(board_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at",
        params![scope.board_id, settings_json, event.occurred_at],
    )
    .map_err(storage_failure)?;
    save_version(tx, &scope.board_id, &scope.board_id, "appearance", candidate)?;
    Ok(true)
}

fn apply_card_put(
    tx: &Transaction<'_>,
    scope: &RoamingScope,
    event: &RoamingBoardEvent,
    candidate: &VersionStamp,
) -> Result<(bool, bool), SyncRepositoryError> {
    if card_tombstone(tx, &event.entity_id)?.is_some() {
        return Ok((false, true));
    }
    if let Some(delta) = event.payload.get("checklistDelta").and_then(Value::as_object) {
        return apply_checklist_delta(tx, scope, event, candidate, delta).map(|changed| (changed, false));
    }
    let incoming = event.payload.get("card").and_then(Value::as_object).ok_or(SyncRepositoryError::InvalidEvent)?;
    if value_string(incoming, "id")? != event.entity_id || value_string(incoming, "boardId")? != scope.board_id {
        return Err(SyncRepositoryError::InvalidEvent);
    }
    let all_fields = event.field_mask.iter().any(|field| field == "*");
    let requested = if all_fields {
        incoming.keys().cloned().collect::<BTreeSet<_>>()
    } else {
        event.field_mask.iter().cloned().collect::<BTreeSet<_>>()
    };
    let exists = tx.query_row("SELECT 1 FROM cards WHERE id = ?1", [event.entity_id.as_str()], |_| Ok(()))
        .optional().map_err(storage_failure)?.is_some();
    let mut extension = load_extension(tx, "card", &event.entity_id)?;
    let mut changed = false;
    if !exists {
        if !all_fields { return Ok((false, false)); }
        let column_id=value_string(incoming,"columnId")?;
        if !column_in_board(tx,&column_id,&scope.board_id)? { return Err(SyncRepositoryError::InvalidEvent); }
        let title=value_string(incoming,"title")?;
        let position=value_f64(incoming,"position")?;
        let archived=value_bool(incoming,"isArchived")?;
        tx.execute(
            "INSERT INTO cards(id, workspace_id, board_id, column_id, title, position, lifecycle) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![event.entity_id,scope.workspace_id,scope.board_id,column_id,title,position,if archived {"archived"} else {"active"}],
        ).map_err(storage_failure)?;
        for field in requested.iter() { save_version(tx,&scope.board_id,&event.entity_id,field,candidate)?; }
        extension = incoming.clone();
        changed=true;
    } else {
        for field in requested {
            if !event_wins(tx,&scope.board_id,&event.entity_id,&field,candidate)? { continue; }
            let Some(value)=incoming.get(&field).cloned() else { continue; };
            match field.as_str() {
                "title" => {
                    let title=value.as_str().ok_or(SyncRepositoryError::InvalidEvent)?;
                    tx.execute("UPDATE cards SET title = ?1 WHERE id = ?2",params![title,event.entity_id]).map_err(storage_failure)?;
                }
                "columnId" => {
                    let column=value.as_str().ok_or(SyncRepositoryError::InvalidEvent)?;
                    if !column_in_board(tx,column,&scope.board_id)? { return Err(SyncRepositoryError::InvalidEvent); }
                    tx.execute("UPDATE cards SET column_id = ?1 WHERE id = ?2",params![column,event.entity_id]).map_err(storage_failure)?;
                }
                "position" => {
                    let position=value.as_f64().filter(|value| value.is_finite()).ok_or(SyncRepositoryError::InvalidEvent)?;
                    tx.execute("UPDATE cards SET position = ?1 WHERE id = ?2",params![position,event.entity_id]).map_err(storage_failure)?;
                }
                "isArchived" => {
                    let archived=value.as_bool().ok_or(SyncRepositoryError::InvalidEvent)?;
                    tx.execute("UPDATE cards SET lifecycle = ?1 WHERE id = ?2",params![if archived {"archived"} else {"active"},event.entity_id]).map_err(storage_failure)?;
                }
                _ => {}
            }
            extension.insert(field.clone(), value);
            save_version(tx,&scope.board_id,&event.entity_id,&field,candidate)?;
            changed=true;
        }
    }
    store_extension(tx,"card",&event.entity_id,&extension)?;
    Ok((changed,false))
}

fn apply_card_delete(
    tx: &Transaction<'_>,
    scope: &RoamingScope,
    event: &RoamingBoardEvent,
    candidate: &VersionStamp,
) -> Result<bool, SyncRepositoryError> {
    if let Some(current)=card_tombstone(tx,&event.entity_id)? {
        if candidate <= &current { return Ok(false); }
    }
    tx.execute("DELETE FROM cards WHERE id = ?1",[event.entity_id.as_str()]).map_err(storage_failure)?;
    tx.execute(
        "INSERT INTO card_tombstones(card_id, workspace_id, board_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6) ON CONFLICT(card_id) DO UPDATE SET workspace_id=excluded.workspace_id, board_id=excluded.board_id, logical_clock=excluded.logical_clock, replica_id=excluded.replica_id, event_id=excluded.event_id",
        params![event.entity_id,scope.workspace_id,scope.board_id,candidate.logical_clock.to_string(),candidate.replica_id,candidate.event_id],
    ).map_err(storage_failure)?;
    save_version(tx,&scope.board_id,&event.entity_id,"__lifecycle",candidate)?;
    Ok(true)
}

fn mark_seen(
    tx: &Transaction<'_>,
    event: &RoamingBoardEvent,
    digest: &str,
) -> Result<(), SyncRepositoryError> {
    tx.execute(
        "INSERT INTO sync_seen_events(event_id, board_id, event_digest, logical_clock, replica_id, applied_at_unix_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![event.event_id,event.board_id,digest,event.logical_clock.to_string(),event.replica_id,now_millis()],
    ).map_err(storage_failure)?;
    Ok(())
}

impl SyncRepository for SqliteSyncRepository {
    fn materialize_pending(
        &mut self,
        scope: &RoamingScope,
    ) -> Result<SyncMaterializeReport, SyncRepositoryError> {
        let tx=self.connection.transaction_with_behavior(TransactionBehavior::Immediate).map_err(storage_failure)?;
        ensure_scope(&tx,scope)?;
        let replica_id=local_replica_id(&tx)?;
        let markers=pending_markers(&tx,&scope.board_id)?;
        let mut report=SyncMaterializeReport {
            pending_markers: markers.len() as u64,
            materialized_events:0,
            already_materialized_markers:0,
            blocked_markers:Vec::new(),
        };
        for marker in markers {
            let existing:i64=tx.query_row(
                "SELECT COUNT(*) FROM sync_outbox WHERE source_change_id = ?1",
                [marker.id.as_str()], |row| row.get(0)
            ).map_err(storage_failure)?;
            if existing>0 { report.already_materialized_markers+=1; continue; }
            let events=match events_for_marker(&tx,scope,&replica_id,&marker) {
                Ok(events)=>events,
                Err(SyncRepositoryError::UnsupportedPendingKind(kind))=>{
                    report.blocked_markers.push(format!("{}:{}",marker.id,kind));
                    continue;
                }
                Err(error)=>return Err(error),
            };
            if events.is_empty() {
                report.blocked_markers.push(format!("{}:{}",marker.id,marker.kind));
                continue;
            }
            for event in events {
                validate_roaming_event(&event,scope)?;
                insert_outbox(&tx,&marker.id,&event,marker.created_at_unix_ms)?;
                record_local_event_versions(&tx, scope, &event)?;
                report.materialized_events+=1;
            }
        }
        tx.commit().map_err(storage_failure)?;
        Ok(report)
    }

    fn list_outbox(&self, scope: &RoamingScope) -> Result<Vec<RoamingBoardEvent>, SyncRepositoryError> {
        ensure_scope(&self.connection,scope)?;
        let mut stmt=self.connection.prepare(
            "SELECT event_id, protocol_version, workspace_id, board_id, capability_epoch, replica_id, replica_seq, logical_clock, entity_type, entity_id, operation, occurred_at, field_mask_json, payload_json FROM sync_outbox WHERE board_id = ?1"
        ).map_err(storage_failure)?;
        let rows=stmt.query_map([scope.board_id.as_str()],|row| {
            Ok((
                row.get::<_,String>(0)?, row.get::<_,String>(1)?, row.get::<_,String>(2)?, row.get::<_,String>(3)?,
                row.get::<_,String>(4)?, row.get::<_,String>(5)?, row.get::<_,String>(6)?, row.get::<_,String>(7)?,
                row.get::<_,String>(8)?, row.get::<_,String>(9)?, row.get::<_,String>(10)?, row.get::<_,String>(11)?,
                row.get::<_,String>(12)?, row.get::<_,String>(13)?,
            ))
        }).map_err(storage_failure)?;
        let mut events=Vec::new();
        for row in rows {
            let (event_id,protocol_version,workspace_id,board_id,epoch,replica_id,replica_seq,logical_clock,entity_type,entity_id,operation,occurred_at,field_mask,payload)=row.map_err(storage_failure)?;
            let event=RoamingBoardEvent {
                protocol_version,event_id,workspace_id,board_id,
                capability_epoch:epoch.parse::<u64>().map_err(storage_failure)?,
                replica_id,
                replica_seq:replica_seq.parse::<u64>().map_err(storage_failure)?,
                logical_clock:logical_clock.parse::<u64>().map_err(storage_failure)?,
                entity_type,entity_id,operation,
                field_mask:serde_json::from_str(&field_mask).map_err(storage_failure)?,
                payload:serde_json::from_str(&payload).map_err(storage_failure)?,occurred_at,
            };
            validate_roaming_event(&event,scope)?;
            events.push(event);
        }
        events.sort_by(|left,right| stamp_of(left).unwrap().cmp(&stamp_of(right).unwrap()));
        Ok(events)
    }

    fn apply_remote_batch(
        &mut self,
        scope: &RoamingScope,
        events: &[RoamingBoardEvent],
    ) -> Result<SyncApplyReport, SyncRepositoryError> {
        ensure_scope(&self.connection,scope)?;
        let local = self.materialize_pending(scope)?;
        if let Some(blocked) = local.blocked_markers.first() {
            return Err(SyncRepositoryError::UnsupportedPendingKind(blocked.clone()));
        }
        for event in events { validate_roaming_event(event,scope)?; }
        let mut ordered=events.to_vec();
        ordered.sort_by(|left,right| match (stamp_of(left),stamp_of(right)) {
            (Ok(left),Ok(right))=>left.cmp(&right),
            _=>Ordering::Equal,
        });
        let tx=self.connection.transaction_with_behavior(TransactionBehavior::Immediate).map_err(storage_failure)?;
        ensure_scope(&tx,scope)?;
        if let Some(max_clock) = ordered.iter().map(|event| event.logical_clock).max() {
            observe_remote_clock(&tx, max_clock)?;
        }
        let mut report=SyncApplyReport { received:events.len() as u64, applied:0, duplicates:0, stale:0, tombstone_blocked:0 };
        for event in ordered {
            let digest=canonical_event_digest(&event)?;
            let seen:Option<String>=tx.query_row(
                "SELECT event_digest FROM sync_seen_events WHERE event_id = ?1",
                [event.event_id.as_str()],|row|row.get(0)
            ).optional().map_err(storage_failure)?;
            if let Some(seen)=seen {
                if seen!=digest { return Err(SyncRepositoryError::ReplayConflict); }
                report.duplicates+=1; continue;
            }
            let candidate=stamp_of(&event)?;
            let (changed,blocked)=match event.operation.as_str() {
                "card.delete"=>(apply_card_delete(&tx,scope,&event,&candidate)?,false),
                "card.put"=>apply_card_put(&tx,scope,&event,&candidate)?,
                "board.snapshot"=>(apply_board_snapshot(&tx,scope,&event,&candidate)?,false),
                "board.appearance.put"=>(apply_board_appearance(&tx,scope,&event,&candidate)?,false),
                _=>return Err(SyncRepositoryError::InvalidEvent),
            };
            if changed { report.applied+=1; }
            else if blocked { report.tombstone_blocked+=1; }
            else { report.stale+=1; }
            mark_seen(&tx,&event,&digest)?;
        }
        tx.commit().map_err(storage_failure)?;
        Ok(report)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        application::sync::SyncRepository,
        domain::sync::RoamingBoardEvent,
        infrastructure::profile::ProfileStoragePaths,
    };
    use std::{fs,path::PathBuf,sync::atomic::{AtomicU64,Ordering as AtomicOrdering}};

    static NEXT:AtomicU64=AtomicU64::new(1);
    fn temp_profile(name:&str)->ProfileStoragePaths {
        let n=NEXT.fetch_add(1,AtomicOrdering::Relaxed);
        ProfileStoragePaths::new(std::env::temp_dir().join(format!("p2pkanban-a10-{name}-{}-{n}/profiles/default",std::process::id())))
    }
    fn cleanup(layout:&ProfileStoragePaths) {
        let root=layout.root().ancestors().nth(2).map(PathBuf::from).unwrap_or_else(||layout.root().to_path_buf());
        let _=fs::remove_dir_all(root);
    }
    fn scope()->RoamingScope { RoamingScope { workspace_id:"018f0000-0000-7000-8000-000000000001".into(), board_id:"018f0000-0000-7000-8000-000000000002".into(), capability_epoch:3 } }
    fn seed(repo:&SqliteSyncRepository) {
        repo.connection.execute("INSERT INTO workspaces(id,title,access_epoch) VALUES (?1,'w','3')",[scope().workspace_id]).unwrap();
        repo.connection.execute("INSERT INTO boards(id,workspace_id,title) VALUES (?1,?2,'b')",params![scope().board_id,scope().workspace_id]).unwrap();
        repo.connection.execute("INSERT INTO columns(id,board_id,title,position) VALUES ('column-a',?1,'Todo',1000)",[scope().board_id]).unwrap();
        repo.connection.execute("UPDATE local_mutation_state SET origin_id='replica-linux-a10', logical_clock='10' WHERE singleton=1",[]).unwrap();
    }
    fn remote_put(event_id:&str,clock:u64,title:&str)->RoamingBoardEvent {
        RoamingBoardEvent {
            protocol_version:ROAMING_PROTOCOL_VERSION.into(),event_id:event_id.into(),workspace_id:scope().workspace_id,board_id:scope().board_id,capability_epoch:3,
            replica_id:"replica-android".into(),replica_seq:clock,logical_clock:clock,entity_type:"card".into(),entity_id:"card-a".into(),operation:"card.put".into(),
            field_mask:vec!["*".into()],payload:json!({"card":{"id":"card-a","boardId":scope().board_id,"columnId":"column-a","parentCardId":null,"title":title,"description":"preserved","priority":null,"position":1000.0,"startAt":null,"dueAt":null,"isArchived":false,"createdAt":"2026-09-13T00:00:00Z","updatedAt":"2026-09-13T00:00:00Z","archivedAt":null}}),occurred_at:"2026-09-13T00:00:00Z".into()
        }
    }

    #[test]
    fn a10_pending_marker_materializes_to_durable_roaming_outbox() {
        let layout=temp_profile("outbox"); cleanup(&layout);
        {
            let mut repo=SqliteSyncRepository::open(&layout).unwrap(); seed(&repo);
            repo.connection.execute("INSERT INTO cards(id,workspace_id,board_id,column_id,title,position,lifecycle) VALUES ('card-a',?1,?2,'column-a','Local',1000,'active')",params![scope().workspace_id,scope().board_id]).unwrap();
            repo.connection.execute("INSERT INTO pending_local_changes(id,workspace_id,board_id,sequence,kind,entity_id,created_at_unix_ms) VALUES ('018f0000-0000-7000-8000-000000000777',?1,?2,'11','card.create','card-a',1789257600000)",params![scope().workspace_id,scope().board_id]).unwrap();
            let report=repo.materialize_pending(&scope()).unwrap();
            assert_eq!(report.materialized_events,1);
            let outbox=repo.list_outbox(&scope()).unwrap();
            assert_eq!(outbox.len(),1);
            assert_eq!(outbox[0].event_id,"018f0000-0000-7000-8000-000000000777");
            assert_eq!(outbox[0].operation,"card.put");
            assert!(outbox[0].field_mask.contains(&"*".to_string()));
        }
        {
            let repo=SqliteSyncRepository::open(&layout).unwrap();
            assert_eq!(repo.list_outbox(&scope()).unwrap().len(),1);
        }
        cleanup(&layout);
    }

    #[test]
    fn a12_appearance_pending_materializes_and_remote_apply_persists() {
        let layout=temp_profile("appearance"); cleanup(&layout);
        let mut repo=SqliteSyncRepository::open(&layout).unwrap(); seed(&repo);
        repo.connection.execute(
            "INSERT INTO board_appearance_settings(board_id,settings_json,updated_at) VALUES (?1,?2,'2026-09-15T00:00:00Z')",
            params![scope().board_id, format!(r#"{{"boardId":"{}","accent":"violet"}}"#, scope().board_id)],
        ).unwrap();
        repo.connection.execute(
            "INSERT INTO pending_local_changes(id,workspace_id,board_id,sequence,kind,entity_id,created_at_unix_ms) VALUES ('appearance-local',?1,?2,'11','board.appearance.put',?2,1789257600000)",
            params![scope().workspace_id,scope().board_id],
        ).unwrap();
        let report=repo.materialize_pending(&scope()).unwrap();
        assert_eq!(report.materialized_events,1);
        let event=repo.list_outbox(&scope()).unwrap().into_iter().next().unwrap();
        assert_eq!(event.operation,"board.appearance.put");
        assert_eq!(event.payload["appearance"]["accent"],"violet");

        let target_layout=temp_profile("appearance-target"); cleanup(&target_layout);
        let mut target=SqliteSyncRepository::open(&target_layout).unwrap(); seed(&target);
        let applied=target.apply_remote_batch(&scope(),&[event]).unwrap();
        assert_eq!(applied.applied,1);
        let stored:String=target.connection.query_row("SELECT settings_json FROM board_appearance_settings WHERE board_id=?1",[scope().board_id],|row|row.get(0)).unwrap();
        assert!(stored.contains("violet"));
        cleanup(&layout); cleanup(&target_layout);
    }

    #[test]
    fn a10_remote_reorder_replay_delete_and_stale_resurrection_converge() {
        let layout=temp_profile("merge"); cleanup(&layout);
        let mut repo=SqliteSyncRepository::open(&layout).unwrap(); seed(&repo);
        let old=remote_put("event-old",7,"Old");
        let newer=remote_put("event-new",8,"New");
        let mut delete=remote_put("event-delete",9,"ignored");
        delete.operation="card.delete".into(); delete.field_mask=vec!["__lifecycle".into()]; delete.payload=json!({});
        let report=repo.apply_remote_batch(&scope(),&[newer.clone(),old.clone(),newer.clone()]).unwrap();
        assert_eq!(report.applied,2);
        assert_eq!(report.duplicates,1);
        let title:String=repo.connection.query_row("SELECT title FROM cards WHERE id='card-a'",[],|row|row.get(0)).unwrap();
        assert_eq!(title,"New");
        let ext:String=repo.connection.query_row("SELECT payload_json FROM sync_entity_extensions WHERE entity_type='card' AND entity_id='card-a'",[],|row|row.get(0)).unwrap();
        assert!(ext.contains("preserved"));
        repo.apply_remote_batch(&scope(),&[delete]).unwrap();
        assert_eq!(repo.connection.query_row("SELECT COUNT(*) FROM cards WHERE id='card-a'",[],|row|row.get::<_,i64>(0)).unwrap(),0);
        let mut resurrect=remote_put("event-resurrect",10,"Must not return");
        resurrect.field_mask=vec!["title".into()];
        let report=repo.apply_remote_batch(&scope(),&[resurrect]).unwrap();
        assert_eq!(report.tombstone_blocked,1);
        assert_eq!(repo.connection.query_row("SELECT COUNT(*) FROM cards WHERE id='card-a'",[],|row|row.get::<_,i64>(0)).unwrap(),0);
        cleanup(&layout);
    }

    #[test]
    fn a10_stale_capability_epoch_rejects_batch_before_mutation() {
        let layout=temp_profile("epoch"); cleanup(&layout);
        let mut repo=SqliteSyncRepository::open(&layout).unwrap(); seed(&repo);
        let stale=RoamingScope { capability_epoch:2,..scope() };
        assert_eq!(repo.apply_remote_batch(&stale,&[remote_put("event-a",1,"x")]),Err(SyncRepositoryError::StaleCapabilityEpoch));
        assert_eq!(repo.connection.query_row("SELECT COUNT(*) FROM sync_seen_events",[],|row|row.get::<_,i64>(0)).unwrap(),0);
        cleanup(&layout);
    }

    #[test]
    fn a10_replay_same_id_different_body_is_rejected_atomically() {
        let layout=temp_profile("replay-conflict"); cleanup(&layout);
        let mut repo=SqliteSyncRepository::open(&layout).unwrap(); seed(&repo);
        repo.apply_remote_batch(&scope(),&[remote_put("event-a",1,"first")]).unwrap();
        let before:String=repo.connection.query_row("SELECT title FROM cards WHERE id='card-a'",[],|row|row.get(0)).unwrap();
        assert_eq!(repo.apply_remote_batch(&scope(),&[remote_put("event-a",1,"tampered")]),Err(SyncRepositoryError::ReplayConflict));
        let after:String=repo.connection.query_row("SELECT title FROM cards WHERE id='card-a'",[],|row|row.get(0)).unwrap();
        assert_eq!(before,after);
        cleanup(&layout);
    }

    #[test]
    fn a10_materialized_local_version_beats_older_remote_event() {
        let layout=temp_profile("local-wins"); cleanup(&layout);
        let mut repo=SqliteSyncRepository::open(&layout).unwrap(); seed(&repo);
        repo.connection.execute("INSERT INTO cards(id,workspace_id,board_id,column_id,title,position,lifecycle) VALUES ('card-a',?1,?2,'column-a','Local',1000,'active')",params![scope().workspace_id,scope().board_id]).unwrap();
        repo.connection.execute("INSERT INTO pending_local_changes(id,workspace_id,board_id,sequence,kind,entity_id,created_at_unix_ms) VALUES ('018f0000-0000-7000-8000-000000000888',?1,?2,'11','card.create','card-a',1789257600000)",params![scope().workspace_id,scope().board_id]).unwrap();
        repo.materialize_pending(&scope()).unwrap();
        let older=remote_put("event-older",10,"Remote older");
        let report=repo.apply_remote_batch(&scope(),&[older]).unwrap();
        assert_eq!(report.stale,1);
        let title:String=repo.connection.query_row("SELECT title FROM cards WHERE id='card-a'",[],|row|row.get(0)).unwrap();
        assert_eq!(title,"Local");
        cleanup(&layout);
    }

    #[test]
    fn a10_remote_clock_advances_future_local_lamport_floor() {
        let layout=temp_profile("clock-floor"); cleanup(&layout);
        let mut repo=SqliteSyncRepository::open(&layout).unwrap(); seed(&repo);
        repo.apply_remote_batch(&scope(),&[remote_put("event-high",50,"Remote")]).unwrap();
        let clock:String=repo.connection.query_row("SELECT logical_clock FROM local_mutation_state WHERE singleton=1",[],|row|row.get(0)).unwrap();
        assert_eq!(clock,"50");
        cleanup(&layout);
    }

    #[test]
    fn a10_android_board_snapshot_fixture_seeds_empty_native_board_once() {
        let layout=temp_profile("snapshot"); cleanup(&layout);
        let mut repo=SqliteSyncRepository::open(&layout).unwrap();
        repo.connection.execute("INSERT INTO workspaces(id,title,access_epoch) VALUES (?1,'w','3')",[scope().workspace_id]).unwrap();
        repo.connection.execute("INSERT INTO boards(id,workspace_id,title) VALUES (?1,?2,'empty')",params![scope().board_id,scope().workspace_id]).unwrap();
        repo.connection.execute("UPDATE local_mutation_state SET origin_id='replica-linux-a10', logical_clock='10' WHERE singleton=1",[]).unwrap();
        let snapshot:RoamingBoardEvent=serde_json::from_str(include_str!("../../../../fixtures/protocol/roaming-board-snapshot-v1.json")).unwrap();
        let report=repo.apply_remote_batch(&scope(),&[snapshot.clone()]).unwrap();
        assert_eq!(report.applied,1);
        assert_eq!(repo.connection.query_row("SELECT COUNT(*) FROM columns WHERE board_id=?1",[scope().board_id],|row|row.get::<_,i64>(0)).unwrap(),1);
        assert_eq!(repo.connection.query_row("SELECT COUNT(*) FROM cards WHERE board_id=?1",[scope().board_id],|row|row.get::<_,i64>(0)).unwrap(),1);
        assert_eq!(repo.connection.query_row("SELECT COUNT(*) FROM checklists",[],|row|row.get::<_,i64>(0)).unwrap(),1);
        assert_eq!(repo.connection.query_row("SELECT COUNT(*) FROM checklist_items",[],|row|row.get::<_,i64>(0)).unwrap(),1);
        let replay=repo.apply_remote_batch(&scope(),&[snapshot]).unwrap();
        assert_eq!(replay.duplicates,1);
        cleanup(&layout);
    }

    #[test]
    fn a10_relay_drop_reorder_replay_harness_converges() {
        let source_layout = temp_profile("relay-source");
        let target_layout = temp_profile("relay-target");
        cleanup(&source_layout);
        cleanup(&target_layout);

        let mut source = SqliteSyncRepository::open(&source_layout).unwrap();
        let mut target = SqliteSyncRepository::open(&target_layout).unwrap();
        seed(&source);
        seed(&target);

        source.connection.execute(
            "INSERT INTO cards(id,workspace_id,board_id,column_id,title,position,lifecycle) VALUES ('card-a',?1,?2,'column-a','A',1000,'active'),('card-b',?1,?2,'column-a','B',2000,'active')",
            params![scope().workspace_id, scope().board_id],
        ).unwrap();
        source.connection.execute(
            "INSERT INTO pending_local_changes(id,workspace_id,board_id,sequence,kind,entity_id,created_at_unix_ms) VALUES ('018f0000-0000-7000-8000-000000000901',?1,?2,'11','card.create','card-a',1789257600000),('018f0000-0000-7000-8000-000000000902',?1,?2,'12','card.create','card-b',1789257601000)",
            params![scope().workspace_id, scope().board_id],
        ).unwrap();

        source.materialize_pending(&scope()).unwrap();
        let events = source.list_outbox(&scope()).unwrap();
        assert_eq!(events.len(), 2);

        // Simulated relay outage drops the older event. The target sees only the newer one.
        let first = target.apply_remote_batch(&scope(), &[events[1].clone()]).unwrap();
        assert_eq!(first.applied, 1);
        assert_eq!(target.connection.query_row(
            "SELECT COUNT(*) FROM cards WHERE board_id=?1",
            [scope().board_id],
            |row| row.get::<_, i64>(0),
        ).unwrap(), 1);

        // Reconnect delivers replayed newer event first, then the dropped older event, then replay again.
        let second = target.apply_remote_batch(
            &scope(),
            &[events[1].clone(), events[0].clone(), events[1].clone()],
        ).unwrap();
        assert_eq!(second.applied, 1);
        assert_eq!(second.duplicates, 2);
        let titles = {
            let mut stmt = target.connection.prepare(
                "SELECT title FROM cards WHERE board_id=?1 ORDER BY position, id",
            ).unwrap();
            stmt.query_map([scope().board_id], |row| row.get::<_, String>(0))
                .unwrap()
                .collect::<Result<Vec<_>, _>>()
                .unwrap()
        };
        assert_eq!(titles, vec!["A".to_owned(), "B".to_owned()]);

        cleanup(&source_layout);
        cleanup(&target_layout);
    }

}
