use std::sync::Mutex;

use uuid::Uuid;

use crate::domain::planner::{AccessEpoch, BoardId, BoardRecord, WorkspaceId, WorkspaceRecord};

const MAX_TITLE_CHARS: usize = 120;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceRepositoryError {
    WorkspaceNotFound,
    BoardNotFound,
    DuplicateWorkspace,
    DuplicateBoard,
    StorageFailure,
}

pub trait WorkspaceCatalogRepository {
    fn list_workspaces(&self) -> Result<Vec<WorkspaceRecord>, WorkspaceRepositoryError>;
    fn create_workspace(&mut self, workspace: WorkspaceRecord) -> Result<(), WorkspaceRepositoryError>;
    fn list_boards(&self, workspace_id: &WorkspaceId) -> Result<Vec<BoardRecord>, WorkspaceRepositoryError>;
    fn create_board(&mut self, board: BoardRecord) -> Result<(), WorkspaceRepositoryError>;
    fn get_board(
        &self,
        workspace_id: &WorkspaceId,
        board_id: &BoardId,
    ) -> Result<Option<BoardRecord>, WorkspaceRepositoryError>;
}

pub trait EntityIdGenerator: Send + Sync {
    fn workspace_id(&self) -> WorkspaceId;
    fn board_id(&self) -> BoardId;
}

#[derive(Default)]
pub struct RandomUuidGenerator;

impl EntityIdGenerator for RandomUuidGenerator {
    fn workspace_id(&self) -> WorkspaceId {
        WorkspaceId::new(Uuid::new_v4().to_string()).expect("UUID must be a valid non-empty id")
    }

    fn board_id(&self) -> BoardId {
        BoardId::new(Uuid::new_v4().to_string()).expect("UUID must be a valid non-empty id")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceView {
    pub id: String,
    pub title: String,
    pub access_epoch: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoardView {
    pub id: String,
    pub workspace_id: String,
    pub title: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceServiceError {
    EmptyTitle,
    TitleTooLong,
    InvalidId,
    Repository(WorkspaceRepositoryError),
    RepositoryPoisoned,
}

impl From<WorkspaceRepositoryError> for WorkspaceServiceError {
    fn from(value: WorkspaceRepositoryError) -> Self {
        Self::Repository(value)
    }
}

fn normalized_title(value: &str) -> Result<String, WorkspaceServiceError> {
    let value = value.trim();
    if value.is_empty() {
        return Err(WorkspaceServiceError::EmptyTitle);
    }
    if value.chars().count() > MAX_TITLE_CHARS {
        return Err(WorkspaceServiceError::TitleTooLong);
    }
    Ok(value.to_owned())
}

fn workspace_view(value: WorkspaceRecord) -> WorkspaceView {
    WorkspaceView {
        id: value.id.as_str().to_owned(),
        title: value.title,
        access_epoch: value.access_epoch.get(),
    }
}

fn board_view(value: BoardRecord) -> BoardView {
    BoardView {
        id: value.id.as_str().to_owned(),
        workspace_id: value.workspace_id.as_str().to_owned(),
        title: value.title,
    }
}

pub struct WorkspaceService {
    repository: Mutex<Box<dyn WorkspaceCatalogRepository + Send>>,
    ids: Box<dyn EntityIdGenerator>,
}

impl WorkspaceService {
    pub fn new(
        repository: Box<dyn WorkspaceCatalogRepository + Send>,
        ids: Box<dyn EntityIdGenerator>,
    ) -> Self {
        Self {
            repository: Mutex::new(repository),
            ids,
        }
    }

    pub fn list_workspaces(&self) -> Result<Vec<WorkspaceView>, WorkspaceServiceError> {
        let repository = self.repository.lock().map_err(|_| WorkspaceServiceError::RepositoryPoisoned)?;
        Ok(repository
            .list_workspaces()?
            .into_iter()
            .map(workspace_view)
            .collect())
    }

    pub fn create_workspace(&self, title: &str) -> Result<WorkspaceView, WorkspaceServiceError> {
        let workspace = WorkspaceRecord {
            id: self.ids.workspace_id(),
            title: normalized_title(title)?,
            access_epoch: AccessEpoch::new(1).expect("initial access epoch is valid"),
        };
        let mut repository = self.repository.lock().map_err(|_| WorkspaceServiceError::RepositoryPoisoned)?;
        repository.create_workspace(workspace.clone())?;
        Ok(workspace_view(workspace))
    }

    pub fn list_boards(&self, workspace_id: &str) -> Result<Vec<BoardView>, WorkspaceServiceError> {
        let workspace_id =
            WorkspaceId::new(workspace_id).map_err(|_| WorkspaceServiceError::InvalidId)?;
        let repository = self.repository.lock().map_err(|_| WorkspaceServiceError::RepositoryPoisoned)?;
        Ok(repository
            .list_boards(&workspace_id)?
            .into_iter()
            .map(board_view)
            .collect())
    }

    pub fn create_board(
        &self,
        workspace_id: &str,
        title: &str,
    ) -> Result<BoardView, WorkspaceServiceError> {
        let workspace_id =
            WorkspaceId::new(workspace_id).map_err(|_| WorkspaceServiceError::InvalidId)?;
        let board = BoardRecord {
            id: self.ids.board_id(),
            workspace_id,
            title: normalized_title(title)?,
        };
        let mut repository = self.repository.lock().map_err(|_| WorkspaceServiceError::RepositoryPoisoned)?;
        repository.create_board(board.clone())?;
        Ok(board_view(board))
    }

    pub fn open_board(
        &self,
        workspace_id: &str,
        board_id: &str,
    ) -> Result<BoardView, WorkspaceServiceError> {
        let workspace_id =
            WorkspaceId::new(workspace_id).map_err(|_| WorkspaceServiceError::InvalidId)?;
        let board_id = BoardId::new(board_id).map_err(|_| WorkspaceServiceError::InvalidId)?;
        let repository = self.repository.lock().map_err(|_| WorkspaceServiceError::RepositoryPoisoned)?;
        repository
            .get_board(&workspace_id, &board_id)?
            .map(board_view)
            .ok_or(WorkspaceRepositoryError::BoardNotFound.into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[derive(Default)]
    struct MemoryRepo {
        workspaces: BTreeMap<String, WorkspaceRecord>,
        boards: BTreeMap<String, BoardRecord>,
    }

    impl WorkspaceCatalogRepository for MemoryRepo {
        fn list_workspaces(&self) -> Result<Vec<WorkspaceRecord>, WorkspaceRepositoryError> {
            Ok(self.workspaces.values().cloned().collect())
        }

        fn create_workspace(&mut self, workspace: WorkspaceRecord) -> Result<(), WorkspaceRepositoryError> {
            if self.workspaces.contains_key(workspace.id.as_str()) {
                return Err(WorkspaceRepositoryError::DuplicateWorkspace);
            }
            self.workspaces.insert(workspace.id.as_str().to_owned(), workspace);
            Ok(())
        }

        fn list_boards(&self, workspace_id: &WorkspaceId) -> Result<Vec<BoardRecord>, WorkspaceRepositoryError> {
            if !self.workspaces.contains_key(workspace_id.as_str()) {
                return Err(WorkspaceRepositoryError::WorkspaceNotFound);
            }
            Ok(self.boards.values().filter(|board| board.workspace_id == *workspace_id).cloned().collect())
        }

        fn create_board(&mut self, board: BoardRecord) -> Result<(), WorkspaceRepositoryError> {
            if !self.workspaces.contains_key(board.workspace_id.as_str()) {
                return Err(WorkspaceRepositoryError::WorkspaceNotFound);
            }
            if self.boards.contains_key(board.id.as_str()) {
                return Err(WorkspaceRepositoryError::DuplicateBoard);
            }
            self.boards.insert(board.id.as_str().to_owned(), board);
            Ok(())
        }

        fn get_board(
            &self,
            workspace_id: &WorkspaceId,
            board_id: &BoardId,
        ) -> Result<Option<BoardRecord>, WorkspaceRepositoryError> {
            Ok(self.boards.get(board_id.as_str()).filter(|board| board.workspace_id == *workspace_id).cloned())
        }
    }

    struct FixedIds;

    impl EntityIdGenerator for FixedIds {
        fn workspace_id(&self) -> WorkspaceId {
            WorkspaceId::new("workspace-fixed").unwrap()
        }
        fn board_id(&self) -> BoardId {
            BoardId::new("board-fixed").unwrap()
        }
    }

    #[test]
    fn application_service_creates_and_opens_board_without_platform_dependencies() {
        let service = WorkspaceService::new(Box::new(MemoryRepo::default()), Box::new(FixedIds));
        let workspace = service.create_workspace("  Offline work  ").unwrap();
        assert_eq!(workspace.title, "Offline work");
        let board = service.create_board(&workspace.id, "Planner").unwrap();
        assert_eq!(service.open_board(&workspace.id, &board.id).unwrap(), board);
    }

    #[test]
    fn empty_or_oversized_titles_fail_before_repository_write() {
        let service = WorkspaceService::new(Box::new(MemoryRepo::default()), Box::new(FixedIds));
        assert_eq!(service.create_workspace("   "), Err(WorkspaceServiceError::EmptyTitle));
        assert_eq!(
            service.create_workspace(&"x".repeat(MAX_TITLE_CHARS + 1)),
            Err(WorkspaceServiceError::TitleTooLong)
        );
    }
}
