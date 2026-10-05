use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use uuid::Uuid;

use crate::{
    application::{
        planner::{PlannerFeatureMutation, PlannerFeatureRepository, PlannerFeatureTransaction},
        repository::{PlannerMutation, PlannerRepository, PlannerTransaction, RepositoryError},
    },
    domain::planner::{
        compare_card_order, compare_checklist_item_order, compare_checklist_order, compare_column_order,
        AccessEpoch, BoardId, CardId, CardLifecycle, CardRecord, CardTombstone, ChecklistId,
        ChecklistItemId, ChecklistItemRecord, ChecklistItemTombstone, ChecklistRecord,
        ChecklistTombstone, ColumnId, ColumnRecord, OrderKey, VersionStamp, WorkspaceId,
    },
};

use crate::infrastructure::profile::ProfileStoragePaths;

use super::migration::{open_profile, ProfileOpenError, ProfileSchemaInfo};

pub struct SqlitePlannerRepository {
    connection: Connection,
    schema: ProfileSchemaInfo,
}

impl SqlitePlannerRepository {
    pub fn open(layout: &ProfileStoragePaths) -> Result<Self, ProfileOpenError> {
        let (connection, schema) = open_profile(layout)?;
        Ok(Self { connection, schema })
    }

    pub fn schema_info(&self) -> ProfileSchemaInfo {
        self.schema
    }

    #[cfg(test)]
    fn seed_contract_scope(&mut self) {
        self.connection
            .execute(
                "INSERT INTO workspaces(id, access_epoch) VALUES (?1, '3')",
                ["018f0000-0000-7000-8000-000000000001"],
            )
            .unwrap();
        self.connection
            .execute(
                "INSERT INTO boards(id, workspace_id) VALUES (?1, ?2)",
                params![
                    "018f0000-0000-7000-8000-000000000002",
                    "018f0000-0000-7000-8000-000000000001"
                ],
            )
            .unwrap();
        for column in [
            "018f0000-0000-7000-8000-000000000005",
            "018f0000-0000-7000-8000-000000000006",
        ] {
            self.connection
                .execute(
                    "INSERT INTO columns(id, board_id) VALUES (?1, ?2)",
                    params![column, "018f0000-0000-7000-8000-000000000002"],
                )
                .unwrap();
        }
    }
}

fn storage_failure<T>(_: T) -> RepositoryError {
    RepositoryError::StorageFailure
}

fn epoch_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(i64::MAX as u128) as i64)
        .unwrap_or(0)
}

fn next_local_clock(tx: &Transaction<'_>) -> Result<(u64, String), RepositoryError> {
    let (clock, origin): (String, String) = tx
        .query_row(
            "SELECT logical_clock, origin_id FROM local_mutation_state WHERE singleton = 1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .map_err(storage_failure)?;
    let next = clock
        .parse::<u64>()
        .map_err(storage_failure)?
        .checked_add(1)
        .ok_or(RepositoryError::StorageFailure)?;
    let origin = if origin.trim().is_empty() {
        Uuid::new_v4().to_string()
    } else {
        origin
    };
    tx.execute(
        "UPDATE local_mutation_state SET logical_clock = ?1, origin_id = ?2 WHERE singleton = 1",
        params![next.to_string(), &origin],
    )
    .map_err(storage_failure)?;
    Ok((next, origin))
}

#[derive(Debug, Clone)]
struct PendingDescriptor {
    board_id: BoardId,
    kind: &'static str,
    entity_id: String,
    version: Option<VersionStamp>,
}

fn enqueue_pending(
    tx: &Transaction<'_>,
    workspace_id: &WorkspaceId,
    descriptor: &PendingDescriptor,
) -> Result<(), RepositoryError> {
    let (id, sequence) = if let Some(version) = &descriptor.version {
        (version.event_id.clone(), version.logical_clock)
    } else {
        let (sequence, _) = next_local_clock(tx)?;
        (Uuid::new_v4().to_string(), sequence)
    };
    tx.execute(
        "INSERT INTO pending_local_changes(id, workspace_id, board_id, sequence, kind, entity_id, created_at_unix_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![
            id,
            workspace_id.as_str(),
            descriptor.board_id.as_str(),
            sequence.to_string(),
            descriptor.kind,
            descriptor.entity_id,
            epoch_millis(),
        ],
    )
    .map_err(storage_failure)?;
    Ok(())
}

fn current_access_epoch_on(
    conn: &Connection,
    workspace_id: &WorkspaceId,
) -> Result<AccessEpoch, RepositoryError> {
    let value: Option<String> = conn
        .query_row(
            "SELECT access_epoch FROM workspaces WHERE id = ?1",
            [workspace_id.as_str()],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage_failure)?;
    let value = value.ok_or(RepositoryError::WorkspaceNotFound)?;
    AccessEpoch::new(value.parse::<u64>().map_err(storage_failure)?).map_err(storage_failure)
}

fn parse_card(
    id: String,
    workspace_id: String,
    board_id: String,
    column_id: String,
    title: String,
    position: f64,
    lifecycle: String,
) -> Result<CardRecord, RepositoryError> {
    let lifecycle = match lifecycle.as_str() {
        "active" => CardLifecycle::Active,
        "archived" => CardLifecycle::Archived,
        _ => return Err(RepositoryError::StorageFailure),
    };
    Ok(CardRecord {
        id: CardId::new(id).map_err(storage_failure)?,
        workspace_id: WorkspaceId::new(workspace_id).map_err(storage_failure)?,
        board_id: BoardId::new(board_id).map_err(storage_failure)?,
        column_id: ColumnId::new(column_id).map_err(storage_failure)?,
        title,
        position: OrderKey::new(position).map_err(storage_failure)?,
        lifecycle,
    })
}

fn card_by_id(conn: &Connection, card_id: &CardId) -> Result<Option<CardRecord>, RepositoryError> {
    let raw = conn
        .query_row(
            "SELECT id, workspace_id, board_id, column_id, title, position, lifecycle FROM cards WHERE id = ?1",
            [card_id.as_str()],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, f64>(5)?,
                    row.get::<_, String>(6)?,
                ))
            },
        )
        .optional()
        .map_err(storage_failure)?;
    raw.map(|(id, ws, board, column, title, position, lifecycle)| {
        parse_card(id, ws, board, column, title, position, lifecycle)
    })
    .transpose()
}

fn tombstone_by_id(
    conn: &Connection,
    card_id: &CardId,
) -> Result<Option<CardTombstone>, RepositoryError> {
    let raw = conn
        .query_row(
            "SELECT workspace_id, board_id, card_id, logical_clock, replica_id, event_id FROM card_tombstones WHERE card_id = ?1",
            [card_id.as_str()],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                ))
            },
        )
        .optional()
        .map_err(storage_failure)?;
    raw.map(|(workspace, board, card, clock, replica, event)| {
        Ok(CardTombstone {
            workspace_id: WorkspaceId::new(workspace).map_err(storage_failure)?,
            board_id: BoardId::new(board).map_err(storage_failure)?,
            card_id: CardId::new(card).map_err(storage_failure)?,
            version: VersionStamp::new(
                clock.parse::<u64>().map_err(storage_failure)?,
                replica,
                event,
            )
            .map_err(storage_failure)?,
        })
    })
    .transpose()
}

fn board_workspace(conn: &Connection, board_id: &BoardId) -> Result<WorkspaceId, RepositoryError> {
    let value: Option<String> = conn
        .query_row(
            "SELECT workspace_id FROM boards WHERE id = ?1",
            [board_id.as_str()],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage_failure)?;
    value
        .ok_or(RepositoryError::BoardNotFound)
        .and_then(|value| WorkspaceId::new(value).map_err(storage_failure))
}

fn column_board(conn: &Connection, column_id: &ColumnId) -> Result<BoardId, RepositoryError> {
    let value: Option<String> = conn
        .query_row(
            "SELECT board_id FROM columns WHERE id = ?1",
            [column_id.as_str()],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage_failure)?;
    value
        .ok_or(RepositoryError::ColumnNotFound)
        .and_then(|value| BoardId::new(value).map_err(storage_failure))
}

fn parse_column(
    id: String,
    board_id: String,
    title: String,
    position: f64,
) -> Result<ColumnRecord, RepositoryError> {
    Ok(ColumnRecord {
        id: ColumnId::new(id).map_err(storage_failure)?,
        board_id: BoardId::new(board_id).map_err(storage_failure)?,
        title,
        position: OrderKey::new(position).map_err(storage_failure)?,
    })
}

fn parse_checklist(
    id: String,
    workspace_id: String,
    board_id: String,
    card_id: String,
    title: String,
    position: f64,
) -> Result<ChecklistRecord, RepositoryError> {
    Ok(ChecklistRecord {
        id: ChecklistId::new(id).map_err(storage_failure)?,
        workspace_id: WorkspaceId::new(workspace_id).map_err(storage_failure)?,
        board_id: BoardId::new(board_id).map_err(storage_failure)?,
        card_id: CardId::new(card_id).map_err(storage_failure)?,
        title,
        position: OrderKey::new(position).map_err(storage_failure)?,
    })
}

fn checklist_by_id(
    conn: &Connection,
    checklist_id: &ChecklistId,
) -> Result<Option<ChecklistRecord>, RepositoryError> {
    let raw = conn
        .query_row(
            "SELECT id, workspace_id, board_id, card_id, title, position FROM checklists WHERE id = ?1",
            [checklist_id.as_str()],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, f64>(5)?,
                ))
            },
        )
        .optional()
        .map_err(storage_failure)?;
    raw.map(|(id, workspace, board, card, title, position)| {
        parse_checklist(id, workspace, board, card, title, position)
    })
    .transpose()
}

fn parse_checklist_item(
    id: String,
    checklist_id: String,
    title: String,
    position: f64,
    is_done: i64,
) -> Result<ChecklistItemRecord, RepositoryError> {
    Ok(ChecklistItemRecord {
        id: ChecklistItemId::new(id).map_err(storage_failure)?,
        checklist_id: ChecklistId::new(checklist_id).map_err(storage_failure)?,
        title,
        position: OrderKey::new(position).map_err(storage_failure)?,
        is_done: match is_done {
            0 => false,
            1 => true,
            _ => return Err(RepositoryError::StorageFailure),
        },
    })
}

fn checklist_item_by_id(
    conn: &Connection,
    item_id: &ChecklistItemId,
) -> Result<Option<ChecklistItemRecord>, RepositoryError> {
    let raw = conn
        .query_row(
            "SELECT id, checklist_id, title, position, is_done FROM checklist_items WHERE id = ?1",
            [item_id.as_str()],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, f64>(3)?,
                    row.get::<_, i64>(4)?,
                ))
            },
        )
        .optional()
        .map_err(storage_failure)?;
    raw.map(|(id, checklist, title, position, done)| {
        parse_checklist_item(id, checklist, title, position, done)
    })
    .transpose()
}

fn checklist_tombstone_by_id(
    conn: &Connection,
    checklist_id: &ChecklistId,
) -> Result<Option<ChecklistTombstone>, RepositoryError> {
    let raw = conn
        .query_row(
            "SELECT workspace_id, board_id, card_id, checklist_id, logical_clock, replica_id, event_id FROM checklist_tombstones WHERE checklist_id = ?1",
            [checklist_id.as_str()],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                ))
            },
        )
        .optional()
        .map_err(storage_failure)?;
    raw.map(|(workspace, board, card, checklist, clock, replica, event)| {
        Ok(ChecklistTombstone {
            workspace_id: WorkspaceId::new(workspace).map_err(storage_failure)?,
            board_id: BoardId::new(board).map_err(storage_failure)?,
            card_id: CardId::new(card).map_err(storage_failure)?,
            checklist_id: ChecklistId::new(checklist).map_err(storage_failure)?,
            version: VersionStamp::new(
                clock.parse::<u64>().map_err(storage_failure)?,
                replica,
                event,
            )
            .map_err(storage_failure)?,
        })
    })
    .transpose()
}

fn checklist_item_tombstone_by_id(
    conn: &Connection,
    item_id: &ChecklistItemId,
) -> Result<Option<ChecklistItemTombstone>, RepositoryError> {
    let raw = conn
        .query_row(
            "SELECT workspace_id, board_id, card_id, checklist_id, item_id, logical_clock, replica_id, event_id FROM checklist_item_tombstones WHERE item_id = ?1",
            [item_id.as_str()],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, String>(7)?,
                ))
            },
        )
        .optional()
        .map_err(storage_failure)?;
    raw.map(|(workspace, board, card, checklist, item, clock, replica, event)| {
        Ok(ChecklistItemTombstone {
            workspace_id: WorkspaceId::new(workspace).map_err(storage_failure)?,
            board_id: BoardId::new(board).map_err(storage_failure)?,
            card_id: CardId::new(card).map_err(storage_failure)?,
            checklist_id: ChecklistId::new(checklist).map_err(storage_failure)?,
            item_id: ChecklistItemId::new(item).map_err(storage_failure)?,
            version: VersionStamp::new(
                clock.parse::<u64>().map_err(storage_failure)?,
                replica,
                event,
            )
            .map_err(storage_failure)?,
        })
    })
    .transpose()
}

fn apply_mutation(
    tx: &Transaction<'_>,
    workspace_id: &WorkspaceId,
    mutation: PlannerMutation,
) -> Result<(), RepositoryError> {
    match mutation {
        PlannerMutation::CreateCard(card) => {
            if board_workspace(tx, &card.board_id)? != *workspace_id
                || card.workspace_id != *workspace_id
                || column_board(tx, &card.column_id)? != card.board_id
            {
                return Err(RepositoryError::ScopeMismatch);
            }
            if tombstone_by_id(tx, &card.id)?.is_some() {
                return Err(RepositoryError::Tombstoned);
            }
            if card_by_id(tx, &card.id)?.is_some() {
                return Err(RepositoryError::DuplicateCard);
            }
            let lifecycle = match card.lifecycle {
                CardLifecycle::Active => "active",
                CardLifecycle::Archived => "archived",
            };
            tx.execute(
                "INSERT INTO cards(id, workspace_id, board_id, column_id, title, position, lifecycle) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    card.id.as_str(),
                    card.workspace_id.as_str(),
                    card.board_id.as_str(),
                    card.column_id.as_str(),
                    card.title,
                    card.position.get(),
                    lifecycle,
                ],
            )
            .map_err(storage_failure)?;
        }
        PlannerMutation::MoveCard {
            card_id,
            target_column_id,
            position,
        } => {
            let card = card_by_id(tx, &card_id)?.ok_or(RepositoryError::CardNotFound)?;
            if card.workspace_id != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            if column_board(tx, &target_column_id)? != card.board_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            tx.execute(
                "UPDATE cards SET column_id = ?1, position = ?2 WHERE id = ?3",
                params![target_column_id.as_str(), position.get(), card_id.as_str()],
            )
            .map_err(storage_failure)?;
        }
        PlannerMutation::SetCardArchived { card_id, archived } => {
            let card = card_by_id(tx, &card_id)?.ok_or(RepositoryError::CardNotFound)?;
            if card.workspace_id != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            tx.execute(
                "UPDATE cards SET lifecycle = ?1 WHERE id = ?2",
                params![if archived { "archived" } else { "active" }, card_id.as_str()],
            )
            .map_err(storage_failure)?;
        }
        PlannerMutation::DeleteCard { card_id, version } => {
            if let Some(existing) = tombstone_by_id(tx, &card_id)? {
                if existing.workspace_id != *workspace_id {
                    return Err(RepositoryError::ScopeMismatch);
                }
                if version > existing.version {
                    tx.execute(
                        "UPDATE card_tombstones SET logical_clock = ?1, replica_id = ?2, event_id = ?3 WHERE card_id = ?4",
                        params![
                            version.logical_clock.to_string(),
                            version.replica_id,
                            version.event_id,
                            card_id.as_str(),
                        ],
                    )
                    .map_err(storage_failure)?;
                }
                return Ok(());
            }
            let card = card_by_id(tx, &card_id)?.ok_or(RepositoryError::CardNotFound)?;
            if card.workspace_id != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            tx.execute("DELETE FROM cards WHERE id = ?1", [card_id.as_str()])
                .map_err(storage_failure)?;
            tx.execute(
                "INSERT INTO card_tombstones(card_id, workspace_id, board_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    card_id.as_str(),
                    card.workspace_id.as_str(),
                    card.board_id.as_str(),
                    version.logical_clock.to_string(),
                    version.replica_id,
                    version.event_id,
                ],
            )
            .map_err(storage_failure)?;
        }
        PlannerMutation::ReorderColumn { column_id, positions } => {
            let target_board = column_board(tx, &column_id)?;
            if board_workspace(tx, &target_board)? != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            let mut seen = std::collections::BTreeSet::new();
            for (card_id, _) in &positions {
                if !seen.insert(card_id.clone()) {
                    return Err(RepositoryError::DuplicateReorderItem);
                }
                let card = card_by_id(tx, card_id)?.ok_or(RepositoryError::CardNotFound)?;
                if card.board_id != target_board || card.column_id != column_id {
                    return Err(RepositoryError::ScopeMismatch);
                }
            }
            for (card_id, position) in positions {
                tx.execute(
                    "UPDATE cards SET position = ?1 WHERE id = ?2",
                    params![position.get(), card_id.as_str()],
                )
                .map_err(storage_failure)?;
            }
        }
    }
    Ok(())
}

fn card_pending_descriptors(
    tx: &Transaction<'_>,
    mutation: &PlannerMutation,
) -> Result<Vec<PendingDescriptor>, RepositoryError> {
    let one = |board_id: BoardId, kind: &'static str, entity_id: String, version: Option<VersionStamp>| {
        vec![PendingDescriptor { board_id, kind, entity_id, version }]
    };
    match mutation {
        PlannerMutation::CreateCard(card) => Ok(one(
            card.board_id.clone(),
            "card.create",
            card.id.as_str().to_owned(),
            None,
        )),
        PlannerMutation::MoveCard { card_id, .. } => {
            let card = card_by_id(tx, card_id)?.ok_or(RepositoryError::CardNotFound)?;
            Ok(one(card.board_id, "card.move", card_id.as_str().to_owned(), None))
        }
        PlannerMutation::SetCardArchived { card_id, archived } => {
            let card = card_by_id(tx, card_id)?.ok_or(RepositoryError::CardNotFound)?;
            Ok(one(
                card.board_id,
                if *archived { "card.archive" } else { "card.unarchive" },
                card_id.as_str().to_owned(),
                None,
            ))
        }
        PlannerMutation::DeleteCard { card_id, version } => {
            let board_id = if let Some(card) = card_by_id(tx, card_id)? {
                card.board_id
            } else {
                tombstone_by_id(tx, card_id)?
                    .ok_or(RepositoryError::CardNotFound)?
                    .board_id
            };
            Ok(one(
                board_id,
                "card.delete",
                card_id.as_str().to_owned(),
                Some(version.clone()),
            ))
        }
        PlannerMutation::ReorderColumn { column_id, positions } => {
            let board_id = column_board(tx, column_id)?;
            // A10 stops generating the legacy aggregate card.reorder marker. Each affected card
            // receives its own card.move marker/version so roaming events have unique identities.
            Ok(positions
                .iter()
                .map(|(card_id, _)| PendingDescriptor {
                    board_id: board_id.clone(),
                    kind: "card.move",
                    entity_id: card_id.as_str().to_owned(),
                    version: None,
                })
                .collect())
        }
    }
}

impl PlannerRepository for SqlitePlannerRepository {
    fn current_access_epoch(
        &self,
        workspace_id: &WorkspaceId,
    ) -> Result<AccessEpoch, RepositoryError> {
        current_access_epoch_on(&self.connection, workspace_id)
    }

    fn get_card(&self, card_id: &CardId) -> Result<Option<CardRecord>, RepositoryError> {
        card_by_id(&self.connection, card_id)
    }

    fn get_card_tombstone(
        &self,
        card_id: &CardId,
    ) -> Result<Option<CardTombstone>, RepositoryError> {
        tombstone_by_id(&self.connection, card_id)
    }

    fn list_column_cards(
        &self,
        board_id: &BoardId,
        column_id: &ColumnId,
        include_archived: bool,
    ) -> Result<Vec<CardRecord>, RepositoryError> {
        let mut stmt = self
            .connection
            .prepare(
                "SELECT id, workspace_id, board_id, column_id, title, position, lifecycle FROM cards WHERE board_id = ?1 AND column_id = ?2 AND (?3 = 1 OR lifecycle = 'active')",
            )
            .map_err(storage_failure)?;
        let rows = stmt
            .query_map(
                params![board_id.as_str(), column_id.as_str(), if include_archived { 1 } else { 0 }],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, f64>(5)?,
                        row.get::<_, String>(6)?,
                    ))
                },
            )
            .map_err(storage_failure)?;
        let mut cards = Vec::new();
        for row in rows {
            let (id, ws, board, column, title, position, lifecycle) = row.map_err(storage_failure)?;
            cards.push(parse_card(id, ws, board, column, title, position, lifecycle)?);
        }
        cards.sort_by(compare_card_order);
        Ok(cards)
    }

    fn commit(&mut self, transaction: PlannerTransaction) -> Result<(), RepositoryError> {
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage_failure)?;
        let current = current_access_epoch_on(&tx, &transaction.workspace_id)?;
        if current != transaction.access_epoch {
            return Err(RepositoryError::StaleAccessEpoch {
                provided: transaction.access_epoch,
                current,
            });
        }
        for mutation in transaction.mutations {
            let pending = card_pending_descriptors(&tx, &mutation)?;
            apply_mutation(&tx, &transaction.workspace_id, mutation)?;
            for descriptor in pending {
                enqueue_pending(&tx, &transaction.workspace_id, &descriptor)?;
            }
        }
        tx.commit().map_err(storage_failure)
    }
}


fn apply_feature_mutation(
    tx: &Transaction<'_>,
    workspace_id: &WorkspaceId,
    mutation: PlannerFeatureMutation,
) -> Result<(), RepositoryError> {
    match mutation {
        PlannerFeatureMutation::CreateColumn(column) => {
            if board_workspace(tx, &column.board_id)? != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            let exists = tx
                .query_row(
                    "SELECT 1 FROM columns WHERE id = ?1",
                    [column.id.as_str()],
                    |_| Ok(()),
                )
                .optional()
                .map_err(storage_failure)?
                .is_some();
            if exists {
                return Err(RepositoryError::DuplicateColumn);
            }
            tx.execute(
                "INSERT INTO columns(id, board_id, title, position) VALUES (?1, ?2, ?3, ?4)",
                params![column.id.as_str(), column.board_id.as_str(), column.title, column.position.get()],
            )
            .map_err(storage_failure)?;
        }
        PlannerFeatureMutation::CreateChecklist(checklist) => {
            let card = card_by_id(tx, &checklist.card_id)?.ok_or(RepositoryError::CardNotFound)?;
            if card.workspace_id != *workspace_id
                || checklist.workspace_id != *workspace_id
                || checklist.board_id != card.board_id
            {
                return Err(RepositoryError::ScopeMismatch);
            }
            if checklist_tombstone_by_id(tx, &checklist.id)?.is_some() {
                return Err(RepositoryError::Tombstoned);
            }
            if checklist_by_id(tx, &checklist.id)?.is_some() {
                return Err(RepositoryError::DuplicateChecklist);
            }
            tx.execute(
                "INSERT INTO checklists(id, workspace_id, board_id, card_id, title, position) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    checklist.id.as_str(),
                    checklist.workspace_id.as_str(),
                    checklist.board_id.as_str(),
                    checklist.card_id.as_str(),
                    checklist.title,
                    checklist.position.get(),
                ],
            )
            .map_err(storage_failure)?;
        }
        PlannerFeatureMutation::CreateChecklistItem(item) => {
            let checklist = checklist_by_id(tx, &item.checklist_id)?
                .ok_or(RepositoryError::ChecklistNotFound)?;
            if checklist.workspace_id != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            if checklist_item_tombstone_by_id(tx, &item.id)?.is_some() {
                return Err(RepositoryError::Tombstoned);
            }
            if checklist_item_by_id(tx, &item.id)?.is_some() {
                return Err(RepositoryError::DuplicateChecklistItem);
            }
            tx.execute(
                "INSERT INTO checklist_items(id, checklist_id, title, position, is_done) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    item.id.as_str(),
                    item.checklist_id.as_str(),
                    item.title,
                    item.position.get(),
                    if item.is_done { 1 } else { 0 },
                ],
            )
            .map_err(storage_failure)?;
        }
        PlannerFeatureMutation::SetChecklistItemDone { item_id, done } => {
            let item = checklist_item_by_id(tx, &item_id)?
                .ok_or(RepositoryError::ChecklistItemNotFound)?;
            let checklist = checklist_by_id(tx, &item.checklist_id)?
                .ok_or(RepositoryError::ChecklistNotFound)?;
            if checklist.workspace_id != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            tx.execute(
                "UPDATE checklist_items SET is_done = ?1 WHERE id = ?2",
                params![if done { 1 } else { 0 }, item_id.as_str()],
            )
            .map_err(storage_failure)?;
        }
        PlannerFeatureMutation::DeleteChecklist { checklist_id, version } => {
            if let Some(existing) = checklist_tombstone_by_id(tx, &checklist_id)? {
                if existing.workspace_id != *workspace_id {
                    return Err(RepositoryError::ScopeMismatch);
                }
                if version > existing.version {
                    tx.execute(
                        "UPDATE checklist_tombstones SET logical_clock = ?1, replica_id = ?2, event_id = ?3 WHERE checklist_id = ?4",
                        params![version.logical_clock.to_string(), version.replica_id, version.event_id, checklist_id.as_str()],
                    )
                    .map_err(storage_failure)?;
                }
                return Ok(());
            }
            let checklist = checklist_by_id(tx, &checklist_id)?
                .ok_or(RepositoryError::ChecklistNotFound)?;
            if checklist.workspace_id != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            tx.execute("DELETE FROM checklists WHERE id = ?1", [checklist_id.as_str()])
                .map_err(storage_failure)?;
            tx.execute(
                "INSERT INTO checklist_tombstones(checklist_id, workspace_id, board_id, card_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    checklist_id.as_str(),
                    checklist.workspace_id.as_str(),
                    checklist.board_id.as_str(),
                    checklist.card_id.as_str(),
                    version.logical_clock.to_string(),
                    version.replica_id,
                    version.event_id,
                ],
            )
            .map_err(storage_failure)?;
        }
        PlannerFeatureMutation::DeleteChecklistItem { item_id, version } => {
            if let Some(existing) = checklist_item_tombstone_by_id(tx, &item_id)? {
                if existing.workspace_id != *workspace_id {
                    return Err(RepositoryError::ScopeMismatch);
                }
                if version > existing.version {
                    tx.execute(
                        "UPDATE checklist_item_tombstones SET logical_clock = ?1, replica_id = ?2, event_id = ?3 WHERE item_id = ?4",
                        params![version.logical_clock.to_string(), version.replica_id, version.event_id, item_id.as_str()],
                    )
                    .map_err(storage_failure)?;
                }
                return Ok(());
            }
            let item = checklist_item_by_id(tx, &item_id)?
                .ok_or(RepositoryError::ChecklistItemNotFound)?;
            let checklist = checklist_by_id(tx, &item.checklist_id)?
                .ok_or(RepositoryError::ChecklistNotFound)?;
            if checklist.workspace_id != *workspace_id {
                return Err(RepositoryError::ScopeMismatch);
            }
            tx.execute("DELETE FROM checklist_items WHERE id = ?1", [item_id.as_str()])
                .map_err(storage_failure)?;
            tx.execute(
                "INSERT INTO checklist_item_tombstones(item_id, workspace_id, board_id, card_id, checklist_id, logical_clock, replica_id, event_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    item_id.as_str(),
                    checklist.workspace_id.as_str(),
                    checklist.board_id.as_str(),
                    checklist.card_id.as_str(),
                    checklist.id.as_str(),
                    version.logical_clock.to_string(),
                    version.replica_id,
                    version.event_id,
                ],
            )
            .map_err(storage_failure)?;
        }
    }
    Ok(())
}

fn feature_pending_descriptors(
    tx: &Transaction<'_>,
    mutation: &PlannerFeatureMutation,
) -> Result<Vec<PendingDescriptor>, RepositoryError> {
    let one = |board_id: BoardId, kind: &'static str, entity_id: String, version: Option<VersionStamp>| {
        vec![PendingDescriptor { board_id, kind, entity_id, version }]
    };
    match mutation {
        PlannerFeatureMutation::CreateColumn(column) => Ok(one(
            column.board_id.clone(),
            "column.create",
            column.id.as_str().to_owned(),
            None,
        )),
        PlannerFeatureMutation::CreateChecklist(checklist) => Ok(one(
            checklist.board_id.clone(),
            "checklist.create",
            checklist.id.as_str().to_owned(),
            None,
        )),
        PlannerFeatureMutation::CreateChecklistItem(item) => {
            let checklist = checklist_by_id(tx, &item.checklist_id)?
                .ok_or(RepositoryError::ChecklistNotFound)?;
            Ok(one(checklist.board_id, "checklist.item.create", item.id.as_str().to_owned(), None))
        }
        PlannerFeatureMutation::SetChecklistItemDone { item_id, .. } => {
            let item = checklist_item_by_id(tx, item_id)?
                .ok_or(RepositoryError::ChecklistItemNotFound)?;
            let checklist = checklist_by_id(tx, &item.checklist_id)?
                .ok_or(RepositoryError::ChecklistNotFound)?;
            Ok(one(checklist.board_id, "checklist.item.update", item_id.as_str().to_owned(), None))
        }
        PlannerFeatureMutation::DeleteChecklist { checklist_id, version } => {
            let board_id = if let Some(checklist) = checklist_by_id(tx, checklist_id)? {
                checklist.board_id
            } else {
                checklist_tombstone_by_id(tx, checklist_id)?
                    .ok_or(RepositoryError::ChecklistNotFound)?
                    .board_id
            };
            Ok(one(
                board_id,
                "checklist.delete",
                checklist_id.as_str().to_owned(),
                Some(version.clone()),
            ))
        }
        PlannerFeatureMutation::DeleteChecklistItem { item_id, version } => {
            let board_id = if let Some(item) = checklist_item_by_id(tx, item_id)? {
                checklist_by_id(tx, &item.checklist_id)?
                    .ok_or(RepositoryError::ChecklistNotFound)?
                    .board_id
            } else {
                checklist_item_tombstone_by_id(tx, item_id)?
                    .ok_or(RepositoryError::ChecklistItemNotFound)?
                    .board_id
            };
            Ok(one(
                board_id,
                "checklist.item.delete",
                item_id.as_str().to_owned(),
                Some(version.clone()),
            ))
        }
    }
}

impl PlannerFeatureRepository for SqlitePlannerRepository {
    fn board_workspace(&self, board_id: &BoardId) -> Result<WorkspaceId, RepositoryError> {
        board_workspace(&self.connection, board_id)
    }

    fn list_board_columns(&self, board_id: &BoardId) -> Result<Vec<ColumnRecord>, RepositoryError> {
        board_workspace(&self.connection, board_id)?;
        let mut stmt = self.connection.prepare(
            "SELECT id, board_id, title, position FROM columns WHERE board_id = ?1",
        ).map_err(storage_failure)?;
        let rows = stmt.query_map([board_id.as_str()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, f64>(3)?,
            ))
        }).map_err(storage_failure)?;
        let mut columns = Vec::new();
        for row in rows {
            let (id, board, title, position) = row.map_err(storage_failure)?;
            columns.push(parse_column(id, board, title, position)?);
        }
        columns.sort_by(compare_column_order);
        Ok(columns)
    }

    fn get_checklist(&self, checklist_id: &ChecklistId) -> Result<Option<ChecklistRecord>, RepositoryError> {
        checklist_by_id(&self.connection, checklist_id)
    }

    fn list_card_checklists(&self, card_id: &CardId) -> Result<Vec<ChecklistRecord>, RepositoryError> {
        if card_by_id(&self.connection, card_id)?.is_none() {
            return Err(RepositoryError::CardNotFound);
        }
        let mut stmt = self.connection.prepare(
            "SELECT id, workspace_id, board_id, card_id, title, position FROM checklists WHERE card_id = ?1",
        ).map_err(storage_failure)?;
        let rows = stmt.query_map([card_id.as_str()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, f64>(5)?,
            ))
        }).map_err(storage_failure)?;
        let mut values = Vec::new();
        for row in rows {
            let (id, workspace, board, card, title, position) = row.map_err(storage_failure)?;
            values.push(parse_checklist(id, workspace, board, card, title, position)?);
        }
        values.sort_by(compare_checklist_order);
        Ok(values)
    }

    fn get_checklist_item(&self, item_id: &ChecklistItemId) -> Result<Option<ChecklistItemRecord>, RepositoryError> {
        checklist_item_by_id(&self.connection, item_id)
    }

    fn list_checklist_items(&self, checklist_id: &ChecklistId) -> Result<Vec<ChecklistItemRecord>, RepositoryError> {
        if checklist_by_id(&self.connection, checklist_id)?.is_none() {
            return Err(RepositoryError::ChecklistNotFound);
        }
        let mut stmt = self.connection.prepare(
            "SELECT id, checklist_id, title, position, is_done FROM checklist_items WHERE checklist_id = ?1",
        ).map_err(storage_failure)?;
        let rows = stmt.query_map([checklist_id.as_str()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, f64>(3)?,
                row.get::<_, i64>(4)?,
            ))
        }).map_err(storage_failure)?;
        let mut values = Vec::new();
        for row in rows {
            let (id, checklist, title, position, done) = row.map_err(storage_failure)?;
            values.push(parse_checklist_item(id, checklist, title, position, done)?);
        }
        values.sort_by(compare_checklist_item_order);
        Ok(values)
    }

    fn get_checklist_tombstone(
        &self,
        checklist_id: &ChecklistId,
    ) -> Result<Option<ChecklistTombstone>, RepositoryError> {
        checklist_tombstone_by_id(&self.connection, checklist_id)
    }

    fn get_checklist_item_tombstone(
        &self,
        item_id: &ChecklistItemId,
    ) -> Result<Option<ChecklistItemTombstone>, RepositoryError> {
        checklist_item_tombstone_by_id(&self.connection, item_id)
    }

    fn pending_change_count(&self, board_id: &BoardId) -> Result<u64, RepositoryError> {
        let count: i64 = self.connection.query_row(
            "SELECT COUNT(*) FROM pending_local_changes WHERE board_id = ?1",
            [board_id.as_str()],
            |row| row.get(0),
        ).map_err(storage_failure)?;
        u64::try_from(count).map_err(storage_failure)
    }

    fn allocate_local_version(&mut self) -> Result<VersionStamp, RepositoryError> {
        let tx = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage_failure)?;
        let (clock, origin) = next_local_clock(&tx)?;
        let version = VersionStamp::new(clock, origin, Uuid::new_v4().to_string())
            .map_err(storage_failure)?;
        tx.commit().map_err(storage_failure)?;
        Ok(version)
    }

    fn commit_features(
        &mut self,
        transaction: PlannerFeatureTransaction,
    ) -> Result<(), RepositoryError> {
        let tx = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage_failure)?;
        let current = current_access_epoch_on(&tx, &transaction.workspace_id)?;
        if current != transaction.access_epoch {
            return Err(RepositoryError::StaleAccessEpoch {
                provided: transaction.access_epoch,
                current,
            });
        }
        for mutation in transaction.mutations {
            let pending = feature_pending_descriptors(&tx, &mutation)?;
            apply_feature_mutation(&tx, &transaction.workspace_id, mutation)?;
            for descriptor in pending {
                enqueue_pending(&tx, &transaction.workspace_id, &descriptor)?;
            }
        }
        tx.commit().map_err(storage_failure)
    }
}

impl SqlitePlannerRepository {
    #[cfg(test)]
    fn commit_card_with_forced_abort(
        &mut self,
        transaction: PlannerTransaction,
    ) -> Result<(), RepositoryError> {
        let tx = self.connection.transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage_failure)?;
        let current = current_access_epoch_on(&tx, &transaction.workspace_id)?;
        if current != transaction.access_epoch {
            return Err(RepositoryError::StaleAccessEpoch {
                provided: transaction.access_epoch,
                current,
            });
        }
        for mutation in transaction.mutations {
            let pending = card_pending_descriptors(&tx, &mutation)?;
            apply_mutation(&tx, &transaction.workspace_id, mutation)?;
            for descriptor in pending {
                enqueue_pending(&tx, &transaction.workspace_id, &descriptor)?;
            }
        }
        Err(RepositoryError::StorageFailure)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        application::{
            planner::{PlannerFeatureMutation, PlannerFeatureRepository, PlannerFeatureTransaction},
            repository::{
            contract::{
                assert_atomic_rollback_contract, assert_reorder_contract,
                assert_repository_contract, assert_stale_epoch_contract,
            },
            PlannerMutation, PlannerTransaction,
            },
        },
        domain::planner::{
            AccessEpoch, BoardId, CardId, CardLifecycle, CardRecord, ChecklistId, ChecklistItemId,
            ChecklistItemRecord, ChecklistRecord, ColumnId, OrderKey, WorkspaceId,
        },
    };
    use std::{fs, sync::atomic::{AtomicU64, Ordering}};

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn temp_profile(name: &str) -> ProfileStoragePaths {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        ProfileStoragePaths::new(std::env::temp_dir().join(format!(
            "p2pkanban-a06-repo-{name}-{}-{n}/profiles/default",
            std::process::id()
        )))
    }

    fn cleanup(layout: &ProfileStoragePaths) {
        let root = layout
            .root()
            .ancestors()
            .nth(2)
            .map(ToOwned::to_owned)
            .unwrap_or_else(|| layout.root().to_path_buf());
        let _ = fs::remove_dir_all(root);
    }

    fn fixture_repo(layout: &ProfileStoragePaths) -> SqlitePlannerRepository {
        cleanup(layout);
        let mut repo = SqlitePlannerRepository::open(layout).unwrap();
        repo.seed_contract_scope();
        repo
    }

    #[test]
    fn sqlite_adapter_passes_the_same_a04_repository_contract() {
        let layout = temp_profile("contract");
        let repo = fixture_repo(&layout);
        assert_repository_contract(repo);
        cleanup(&layout);
    }

    #[test]
    fn sqlite_adapter_preserves_stale_epoch_rejection() {
        let layout = temp_profile("stale-epoch");
        let repo = fixture_repo(&layout);
        assert_stale_epoch_contract(repo);
        cleanup(&layout);
    }

    #[test]
    fn sqlite_adapter_preserves_atomic_batch_rollback() {
        let layout = temp_profile("atomic-rollback");
        let repo = fixture_repo(&layout);
        assert_atomic_rollback_contract(repo);
        cleanup(&layout);
    }

    #[test]
    fn sqlite_adapter_preserves_reorder_semantics() {
        let layout = temp_profile("reorder");
        let repo = fixture_repo(&layout);
        assert_reorder_contract(repo);
        cleanup(&layout);
    }

    #[test]
    fn card_survives_close_and_reopen() {
        let layout = temp_profile("reopen");
        let mut repo = fixture_repo(&layout);
        let card_id = CardId::new("018f0000-0000-7000-8000-000000000777").unwrap();
        let card = CardRecord {
            id: card_id.clone(),
            workspace_id: WorkspaceId::new("018f0000-0000-7000-8000-000000000001").unwrap(),
            board_id: BoardId::new("018f0000-0000-7000-8000-000000000002").unwrap(),
            column_id: ColumnId::new("018f0000-0000-7000-8000-000000000005").unwrap(),
            title: "durable card".into(),
            position: OrderKey::new(1000.0).unwrap(),
            lifecycle: CardLifecycle::Active,
        };
        repo.commit(PlannerTransaction {
            workspace_id: card.workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![PlannerMutation::CreateCard(card.clone())],
        })
        .unwrap();
        drop(repo);

        let reopened = SqlitePlannerRepository::open(&layout).unwrap();
        assert_eq!(reopened.get_card(&card_id).unwrap(), Some(card));
        drop(reopened);
        cleanup(&layout);
    }

    fn contract_workspace_id() -> WorkspaceId {
        WorkspaceId::new("018f0000-0000-7000-8000-000000000001").unwrap()
    }

    fn contract_board_id() -> BoardId {
        BoardId::new("018f0000-0000-7000-8000-000000000002").unwrap()
    }

    fn contract_column_id() -> ColumnId {
        ColumnId::new("018f0000-0000-7000-8000-000000000005").unwrap()
    }

    #[test]
    fn a08_planner_slice_survives_close_reopen_and_keeps_pending_explicit() {
        let layout = temp_profile("a08-reopen");
        let mut repo = fixture_repo(&layout);
        let workspace_id = contract_workspace_id();
        let board_id = contract_board_id();
        let card_id = CardId::new("018f0000-0000-7000-8000-000000000881").unwrap();
        let checklist_id = ChecklistId::new("018f0000-0000-7000-8000-000000000882").unwrap();
        let item_id = ChecklistItemId::new("018f0000-0000-7000-8000-000000000883").unwrap();

        repo.commit(PlannerTransaction {
            workspace_id: workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![PlannerMutation::CreateCard(CardRecord {
                id: card_id.clone(),
                workspace_id: workspace_id.clone(),
                board_id: board_id.clone(),
                column_id: contract_column_id(),
                title: "A08 durable card".into(),
                position: OrderKey::new(1000.0).unwrap(),
                lifecycle: CardLifecycle::Active,
            })],
        }).unwrap();

        repo.commit_features(PlannerFeatureTransaction {
            workspace_id: workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![
                PlannerFeatureMutation::CreateChecklist(ChecklistRecord {
                    id: checklist_id.clone(),
                    workspace_id: workspace_id.clone(),
                    board_id: board_id.clone(),
                    card_id: card_id.clone(),
                    title: "Release".into(),
                    position: OrderKey::new(1000.0).unwrap(),
                }),
                PlannerFeatureMutation::CreateChecklistItem(ChecklistItemRecord {
                    id: item_id.clone(),
                    checklist_id: checklist_id.clone(),
                    title: "Run offline verifier".into(),
                    position: OrderKey::new(1000.0).unwrap(),
                    is_done: false,
                }),
                PlannerFeatureMutation::SetChecklistItemDone {
                    item_id: item_id.clone(),
                    done: true,
                },
            ],
        }).unwrap();

        assert!(repo.pending_change_count(&board_id).unwrap() >= 4);
        drop(repo);

        let reopened = SqlitePlannerRepository::open(&layout).unwrap();
        assert_eq!(reopened.get_card(&card_id).unwrap().unwrap().title, "A08 durable card");
        assert_eq!(reopened.list_card_checklists(&card_id).unwrap().len(), 1);
        assert!(reopened.list_checklist_items(&checklist_id).unwrap()[0].is_done);
        assert!(reopened.pending_change_count(&board_id).unwrap() >= 4);
        drop(reopened);
        cleanup(&layout);
    }

    #[test]
    fn a08_tombstones_block_stale_checklist_and_item_resurrection() {
        let layout = temp_profile("a08-tombstone");
        let mut repo = fixture_repo(&layout);
        let workspace_id = contract_workspace_id();
        let board_id = contract_board_id();
        let card_id = CardId::new("018f0000-0000-7000-8000-000000000891").unwrap();
        let checklist_id = ChecklistId::new("018f0000-0000-7000-8000-000000000892").unwrap();
        let item_id = ChecklistItemId::new("018f0000-0000-7000-8000-000000000893").unwrap();

        repo.commit(PlannerTransaction {
            workspace_id: workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![PlannerMutation::CreateCard(CardRecord {
                id: card_id.clone(),
                workspace_id: workspace_id.clone(),
                board_id: board_id.clone(),
                column_id: contract_column_id(),
                title: "card".into(),
                position: OrderKey::new(1000.0).unwrap(),
                lifecycle: CardLifecycle::Active,
            })],
        }).unwrap();
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id: workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![
                PlannerFeatureMutation::CreateChecklist(ChecklistRecord {
                    id: checklist_id.clone(),
                    workspace_id: workspace_id.clone(),
                    board_id: board_id.clone(),
                    card_id: card_id.clone(),
                    title: "checklist".into(),
                    position: OrderKey::new(1000.0).unwrap(),
                }),
                PlannerFeatureMutation::CreateChecklistItem(ChecklistItemRecord {
                    id: item_id.clone(),
                    checklist_id: checklist_id.clone(),
                    title: "item".into(),
                    position: OrderKey::new(1000.0).unwrap(),
                    is_done: false,
                }),
            ],
        }).unwrap();

        let item_version = repo.allocate_local_version().unwrap();
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id: workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![PlannerFeatureMutation::DeleteChecklistItem {
                item_id: item_id.clone(),
                version: item_version,
            }],
        }).unwrap();
        assert!(repo.get_checklist_item_tombstone(&item_id).unwrap().is_some());
        let item_resurrection = repo.commit_features(PlannerFeatureTransaction {
            workspace_id: workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![PlannerFeatureMutation::CreateChecklistItem(ChecklistItemRecord {
                id: item_id.clone(),
                checklist_id: checklist_id.clone(),
                title: "stale".into(),
                position: OrderKey::new(2000.0).unwrap(),
                is_done: false,
            })],
        });
        assert_eq!(item_resurrection, Err(RepositoryError::Tombstoned));

        let checklist_version = repo.allocate_local_version().unwrap();
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id: workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![PlannerFeatureMutation::DeleteChecklist {
                checklist_id: checklist_id.clone(),
                version: checklist_version,
            }],
        }).unwrap();
        assert!(repo.get_checklist_tombstone(&checklist_id).unwrap().is_some());
        let checklist_resurrection = repo.commit_features(PlannerFeatureTransaction {
            workspace_id,
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![PlannerFeatureMutation::CreateChecklist(ChecklistRecord {
                id: checklist_id,
                workspace_id: contract_workspace_id(),
                board_id,
                card_id,
                title: "stale".into(),
                position: OrderKey::new(2000.0).unwrap(),
            })],
        });
        assert_eq!(checklist_resurrection, Err(RepositoryError::Tombstoned));
        cleanup(&layout);
    }

    #[test]
    fn a08_forced_abort_rolls_back_card_and_pending_marker_together() {
        let layout = temp_profile("a08-crash");
        let mut repo = fixture_repo(&layout);
        let workspace_id = contract_workspace_id();
        let board_id = contract_board_id();
        let card_id = CardId::new("018f0000-0000-7000-8000-000000000899").unwrap();
        let before = repo.pending_change_count(&board_id).unwrap();
        let result = repo.commit_card_with_forced_abort(PlannerTransaction {
            workspace_id: workspace_id.clone(),
            access_epoch: AccessEpoch::new(3).unwrap(),
            mutations: vec![PlannerMutation::CreateCard(CardRecord {
                id: card_id.clone(),
                workspace_id,
                board_id: board_id.clone(),
                column_id: contract_column_id(),
                title: "must roll back".into(),
                position: OrderKey::new(1000.0).unwrap(),
                lifecycle: CardLifecycle::Active,
            })],
        });
        assert_eq!(result, Err(RepositoryError::StorageFailure));
        assert_eq!(repo.get_card(&card_id).unwrap(), None);
        assert_eq!(repo.pending_change_count(&board_id).unwrap(), before);
        drop(repo);

        let reopened = SqlitePlannerRepository::open(&layout).unwrap();
        assert_eq!(reopened.get_card(&card_id).unwrap(), None);
        assert_eq!(reopened.pending_change_count(&board_id).unwrap(), before);
        drop(reopened);
        cleanup(&layout);
    }

}
