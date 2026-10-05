use rusqlite::{params, Connection, ErrorCode, OptionalExtension, TransactionBehavior};

use crate::{
    application::workspace::{WorkspaceCatalogRepository, WorkspaceRepositoryError},
    domain::planner::{AccessEpoch, BoardId, BoardRecord, WorkspaceId, WorkspaceRecord},
    infrastructure::profile::ProfileStoragePaths,
};

use super::migration::{open_profile, ProfileOpenError};

pub struct SqliteWorkspaceCatalog {
    connection: Connection,
}

impl SqliteWorkspaceCatalog {
    pub fn open(layout: &ProfileStoragePaths) -> Result<Self, ProfileOpenError> {
        let (connection, _) = open_profile(layout)?;
        Ok(Self { connection })
    }
}

fn storage_failure<T>(_: T) -> WorkspaceRepositoryError {
    WorkspaceRepositoryError::StorageFailure
}

fn constraint_error(error: rusqlite::Error, duplicate: WorkspaceRepositoryError) -> WorkspaceRepositoryError {
    match &error {
        rusqlite::Error::SqliteFailure(inner, _)
            if matches!(
                inner.code,
                ErrorCode::ConstraintViolation
            ) =>
        {
            duplicate
        }
        _ => WorkspaceRepositoryError::StorageFailure,
    }
}

fn parse_workspace(
    id: String,
    title: String,
    access_epoch: String,
) -> Result<WorkspaceRecord, WorkspaceRepositoryError> {
    Ok(WorkspaceRecord {
        id: WorkspaceId::new(id).map_err(storage_failure)?,
        title,
        access_epoch: AccessEpoch::new(access_epoch.parse::<u64>().map_err(storage_failure)?)
            .map_err(storage_failure)?,
    })
}

fn parse_board(
    id: String,
    workspace_id: String,
    title: String,
) -> Result<BoardRecord, WorkspaceRepositoryError> {
    Ok(BoardRecord {
        id: BoardId::new(id).map_err(storage_failure)?,
        workspace_id: WorkspaceId::new(workspace_id).map_err(storage_failure)?,
        title,
    })
}

fn workspace_exists(conn: &Connection, workspace_id: &WorkspaceId) -> Result<bool, WorkspaceRepositoryError> {
    conn.query_row(
        "SELECT 1 FROM workspaces WHERE id = ?1",
        [workspace_id.as_str()],
        |_| Ok(()),
    )
    .optional()
    .map(|value| value.is_some())
    .map_err(storage_failure)
}

impl WorkspaceCatalogRepository for SqliteWorkspaceCatalog {
    fn list_workspaces(&self) -> Result<Vec<WorkspaceRecord>, WorkspaceRepositoryError> {
        let mut statement = self
            .connection
            .prepare("SELECT id, title, access_epoch FROM workspaces ORDER BY title COLLATE NOCASE, id")
            .map_err(storage_failure)?;
        let rows = statement
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(storage_failure)?;
        let mut workspaces = Vec::new();
        for row in rows {
            let (id, title, epoch) = row.map_err(storage_failure)?;
            workspaces.push(parse_workspace(id, title, epoch)?);
        }
        Ok(workspaces)
    }

    fn create_workspace(&mut self, workspace: WorkspaceRecord) -> Result<(), WorkspaceRepositoryError> {
        self.connection
            .execute(
                "INSERT INTO workspaces(id, access_epoch, title) VALUES (?1, ?2, ?3)",
                params![
                    workspace.id.as_str(),
                    workspace.access_epoch.get().to_string(),
                    workspace.title,
                ],
            )
            .map(|_| ())
            .map_err(|error| constraint_error(error, WorkspaceRepositoryError::DuplicateWorkspace))
    }

    fn list_boards(&self, workspace_id: &WorkspaceId) -> Result<Vec<BoardRecord>, WorkspaceRepositoryError> {
        if !workspace_exists(&self.connection, workspace_id)? {
            return Err(WorkspaceRepositoryError::WorkspaceNotFound);
        }
        let mut statement = self
            .connection
            .prepare(
                "SELECT id, workspace_id, title FROM boards WHERE workspace_id = ?1 ORDER BY title COLLATE NOCASE, id",
            )
            .map_err(storage_failure)?;
        let rows = statement
            .query_map([workspace_id.as_str()], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(storage_failure)?;
        let mut boards = Vec::new();
        for row in rows {
            let (id, workspace, title) = row.map_err(storage_failure)?;
            boards.push(parse_board(id, workspace, title)?);
        }
        Ok(boards)
    }

    fn create_board(&mut self, board: BoardRecord) -> Result<(), WorkspaceRepositoryError> {
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage_failure)?;
        if !workspace_exists(&tx, &board.workspace_id)? {
            return Err(WorkspaceRepositoryError::WorkspaceNotFound);
        }
        tx.execute(
            "INSERT INTO boards(id, workspace_id, title) VALUES (?1, ?2, ?3)",
            params![board.id.as_str(), board.workspace_id.as_str(), board.title],
        )
        .map_err(|error| constraint_error(error, WorkspaceRepositoryError::DuplicateBoard))?;
        tx.commit().map_err(storage_failure)
    }

    fn get_board(
        &self,
        workspace_id: &WorkspaceId,
        board_id: &BoardId,
    ) -> Result<Option<BoardRecord>, WorkspaceRepositoryError> {
        let row = self
            .connection
            .query_row(
                "SELECT id, workspace_id, title FROM boards WHERE id = ?1 AND workspace_id = ?2",
                params![board_id.as_str(), workspace_id.as_str()],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                },
            )
            .optional()
            .map_err(storage_failure)?;
        row.map(|(id, workspace, title)| parse_board(id, workspace, title))
            .transpose()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::workspace::WorkspaceCatalogRepository;
    use std::{fs, path::PathBuf, sync::atomic::{AtomicU64, Ordering}};

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn temp_profile(name: &str) -> ProfileStoragePaths {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        ProfileStoragePaths::new(std::env::temp_dir().join(format!(
            "p2pkanban-a07-workspace-{name}-{}-{n}/profiles/default",
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

    fn workspace() -> WorkspaceRecord {
        WorkspaceRecord {
            id: WorkspaceId::new("018f0000-0000-7000-8000-000000000101").unwrap(),
            title: "Offline workspace".into(),
            access_epoch: AccessEpoch::new(1).unwrap(),
        }
    }

    fn board() -> BoardRecord {
        BoardRecord {
            id: BoardId::new("018f0000-0000-7000-8000-000000000102").unwrap(),
            workspace_id: WorkspaceId::new("018f0000-0000-7000-8000-000000000101").unwrap(),
            title: "Durable board".into(),
        }
    }

    #[test]
    fn workspace_and_board_survive_close_and_reopen() {
        let layout = temp_profile("reopen");
        cleanup(&layout);
        {
            let mut repository = SqliteWorkspaceCatalog::open(&layout).unwrap();
            repository.create_workspace(workspace()).unwrap();
            repository.create_board(board()).unwrap();
            assert_eq!(repository.list_workspaces().unwrap(), vec![workspace()]);
            assert_eq!(repository.list_boards(&workspace().id).unwrap(), vec![board()]);
        }
        {
            let repository = SqliteWorkspaceCatalog::open(&layout).unwrap();
            assert_eq!(
                repository.get_board(&workspace().id, &board().id).unwrap(),
                Some(board())
            );
        }
        cleanup(&layout);
    }

    #[test]
    fn board_creation_requires_existing_workspace() {
        let layout = temp_profile("scope");
        cleanup(&layout);
        let mut repository = SqliteWorkspaceCatalog::open(&layout).unwrap();
        assert_eq!(
            repository.create_board(board()),
            Err(WorkspaceRepositoryError::WorkspaceNotFound)
        );
        cleanup(&layout);
    }

    #[test]
    fn sqlite_catalog_schema_has_no_secret_bearing_columns() {
        let layout = temp_profile("no-secrets");
        cleanup(&layout);
        let repository = SqliteWorkspaceCatalog::open(&layout).unwrap();
        let mut statement = repository.connection.prepare(
            "SELECT lower(name || ' ' || sql) FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name",
        ).unwrap();
        let text = statement
            .query_map([], |row| row.get::<_, String>(0))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
            .join("\n");
        for forbidden in ["refresh_token", "access_token", "board_key", "private_key", "vault_root", "secret_key"] {
            assert!(!text.contains(forbidden), "secret-bearing schema token leaked: {forbidden}");
        }
        drop(statement);
        drop(repository);
        cleanup(&layout);
    }
}
