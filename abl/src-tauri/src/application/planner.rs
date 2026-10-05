use std::sync::Mutex;

use uuid::Uuid;

use crate::{
    application::repository::{PlannerMutation, PlannerRepository, PlannerTransaction, RepositoryError},
    domain::planner::{
        AccessEpoch, BoardId, CardId, CardLifecycle, CardRecord, ChecklistId, ChecklistItemId,
        ChecklistItemRecord, ChecklistItemTombstone, ChecklistRecord, ChecklistTombstone, ColumnId,
        ColumnRecord, OrderKey, VersionStamp, WorkspaceId,
    },
};

const MAX_TITLE_CHARS: usize = 120;
const LOCAL_APPEND_STEP: f64 = 1000.0;

#[derive(Debug, Clone, PartialEq)]
pub enum PlannerFeatureMutation {
    CreateColumn(ColumnRecord),
    CreateChecklist(ChecklistRecord),
    CreateChecklistItem(ChecklistItemRecord),
    SetChecklistItemDone {
        item_id: ChecklistItemId,
        done: bool,
    },
    DeleteChecklist {
        checklist_id: ChecklistId,
        version: VersionStamp,
    },
    DeleteChecklistItem {
        item_id: ChecklistItemId,
        version: VersionStamp,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlannerFeatureTransaction {
    pub workspace_id: WorkspaceId,
    pub access_epoch: AccessEpoch,
    pub mutations: Vec<PlannerFeatureMutation>,
}

pub trait PlannerFeatureRepository: PlannerRepository {
    fn board_workspace(&self, board_id: &BoardId) -> Result<WorkspaceId, RepositoryError>;
    fn list_board_columns(&self, board_id: &BoardId) -> Result<Vec<ColumnRecord>, RepositoryError>;
    fn get_checklist(&self, checklist_id: &ChecklistId) -> Result<Option<ChecklistRecord>, RepositoryError>;
    fn list_card_checklists(&self, card_id: &CardId) -> Result<Vec<ChecklistRecord>, RepositoryError>;
    fn get_checklist_item(
        &self,
        item_id: &ChecklistItemId,
    ) -> Result<Option<ChecklistItemRecord>, RepositoryError>;
    fn list_checklist_items(
        &self,
        checklist_id: &ChecklistId,
    ) -> Result<Vec<ChecklistItemRecord>, RepositoryError>;
    fn get_checklist_tombstone(
        &self,
        checklist_id: &ChecklistId,
    ) -> Result<Option<ChecklistTombstone>, RepositoryError>;
    fn get_checklist_item_tombstone(
        &self,
        item_id: &ChecklistItemId,
    ) -> Result<Option<ChecklistItemTombstone>, RepositoryError>;
    fn pending_change_count(&self, board_id: &BoardId) -> Result<u64, RepositoryError>;
    fn allocate_local_version(&mut self) -> Result<VersionStamp, RepositoryError>;
    fn commit_features(
        &mut self,
        transaction: PlannerFeatureTransaction,
    ) -> Result<(), RepositoryError>;
}

pub trait PlannerIdGenerator: Send + Sync {
    fn column_id(&self) -> ColumnId;
    fn card_id(&self) -> CardId;
    fn checklist_id(&self) -> ChecklistId;
    fn checklist_item_id(&self) -> ChecklistItemId;
}

#[derive(Default)]
pub struct RandomPlannerIds;

impl PlannerIdGenerator for RandomPlannerIds {
    fn column_id(&self) -> ColumnId {
        ColumnId::new(Uuid::new_v4().to_string()).expect("UUID must be non-empty")
    }

    fn card_id(&self) -> CardId {
        CardId::new(Uuid::new_v4().to_string()).expect("UUID must be non-empty")
    }

    fn checklist_id(&self) -> ChecklistId {
        ChecklistId::new(Uuid::new_v4().to_string()).expect("UUID must be non-empty")
    }

    fn checklist_item_id(&self) -> ChecklistItemId {
        ChecklistItemId::new(Uuid::new_v4().to_string()).expect("UUID must be non-empty")
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ColumnView {
    pub id: String,
    pub board_id: String,
    pub title: String,
    pub position: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CardView {
    pub id: String,
    pub workspace_id: String,
    pub board_id: String,
    pub column_id: String,
    pub title: String,
    pub position: f64,
    pub archived: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChecklistView {
    pub id: String,
    pub card_id: String,
    pub title: String,
    pub position: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChecklistItemView {
    pub id: String,
    pub checklist_id: String,
    pub title: String,
    pub position: f64,
    pub is_done: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlannerServiceError {
    EmptyTitle,
    TitleTooLong,
    InvalidId,
    OrderExhausted,
    Repository(RepositoryError),
    RepositoryPoisoned,
}

impl From<RepositoryError> for PlannerServiceError {
    fn from(value: RepositoryError) -> Self {
        Self::Repository(value)
    }
}

fn normalized_title(value: &str) -> Result<String, PlannerServiceError> {
    let value = value.trim();
    if value.is_empty() {
        return Err(PlannerServiceError::EmptyTitle);
    }
    if value.chars().count() > MAX_TITLE_CHARS {
        return Err(PlannerServiceError::TitleTooLong);
    }
    Ok(value.to_owned())
}

fn next_position(values: impl Iterator<Item = f64>) -> Result<OrderKey, PlannerServiceError> {
    let highest = values.fold(0.0_f64, f64::max);
    OrderKey::new(highest + LOCAL_APPEND_STEP).map_err(|_| PlannerServiceError::OrderExhausted)
}

fn column_view(value: ColumnRecord) -> ColumnView {
    ColumnView {
        id: value.id.as_str().to_owned(),
        board_id: value.board_id.as_str().to_owned(),
        title: value.title,
        position: value.position.get(),
    }
}

fn card_view(value: CardRecord) -> CardView {
    CardView {
        id: value.id.as_str().to_owned(),
        workspace_id: value.workspace_id.as_str().to_owned(),
        board_id: value.board_id.as_str().to_owned(),
        column_id: value.column_id.as_str().to_owned(),
        title: value.title,
        position: value.position.get(),
        archived: value.lifecycle == CardLifecycle::Archived,
    }
}

fn checklist_view(value: ChecklistRecord) -> ChecklistView {
    ChecklistView {
        id: value.id.as_str().to_owned(),
        card_id: value.card_id.as_str().to_owned(),
        title: value.title,
        position: value.position.get(),
    }
}

fn checklist_item_view(value: ChecklistItemRecord) -> ChecklistItemView {
    ChecklistItemView {
        id: value.id.as_str().to_owned(),
        checklist_id: value.checklist_id.as_str().to_owned(),
        title: value.title,
        position: value.position.get(),
        is_done: value.is_done,
    }
}

pub struct PlannerService {
    repository: Mutex<Box<dyn PlannerFeatureRepository + Send>>,
    ids: Box<dyn PlannerIdGenerator>,
}

impl PlannerService {
    pub fn new(
        repository: Box<dyn PlannerFeatureRepository + Send>,
        ids: Box<dyn PlannerIdGenerator>,
    ) -> Self {
        Self {
            repository: Mutex::new(repository),
            ids,
        }
    }

    fn ids(workspace_id: &str, board_id: &str) -> Result<(WorkspaceId, BoardId), PlannerServiceError> {
        Ok((
            WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?,
            BoardId::new(board_id).map_err(|_| PlannerServiceError::InvalidId)?,
        ))
    }

    fn ensure_board_scope(
        repo: &dyn PlannerFeatureRepository,
        workspace_id: &WorkspaceId,
        board_id: &BoardId,
    ) -> Result<(), PlannerServiceError> {
        if repo.board_workspace(board_id)? != *workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        Ok(())
    }

    pub fn list_columns(
        &self,
        workspace_id: &str,
        board_id: &str,
    ) -> Result<Vec<ColumnView>, PlannerServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        Ok(repo.list_board_columns(&board_id)?.into_iter().map(column_view).collect())
    }

    pub fn create_column(
        &self,
        workspace_id: &str,
        board_id: &str,
        title: &str,
    ) -> Result<ColumnView, PlannerServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        let position = next_position(repo.list_board_columns(&board_id)?.into_iter().map(|column| column.position.get()))?;
        let column = ColumnRecord {
            id: self.ids.column_id(),
            board_id: board_id.clone(),
            title: normalized_title(title)?,
            position,
        };
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerFeatureMutation::CreateColumn(column.clone())],
        })?;
        Ok(column_view(column))
    }

    pub fn list_cards(
        &self,
        workspace_id: &str,
        board_id: &str,
        include_archived: bool,
    ) -> Result<Vec<CardView>, PlannerServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        let mut cards = Vec::new();
        for column in repo.list_board_columns(&board_id)? {
            cards.extend(repo.list_column_cards(&board_id, &column.id, include_archived)?);
        }
        Ok(cards.into_iter().map(card_view).collect())
    }

    pub fn create_card(
        &self,
        workspace_id: &str,
        board_id: &str,
        column_id: &str,
        title: &str,
    ) -> Result<CardView, PlannerServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let column_id = ColumnId::new(column_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        let position = next_position(
            repo.list_column_cards(&board_id, &column_id, true)?
                .into_iter()
                .map(|card| card.position.get()),
        )?;
        let card = CardRecord {
            id: self.ids.card_id(),
            workspace_id: workspace_id.clone(),
            board_id: board_id.clone(),
            column_id,
            title: normalized_title(title)?,
            position,
            lifecycle: CardLifecycle::Active,
        };
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit(PlannerTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerMutation::CreateCard(card.clone())],
        })?;
        Ok(card_view(card))
    }

    pub fn move_card(
        &self,
        workspace_id: &str,
        card_id: &str,
        target_column_id: &str,
    ) -> Result<CardView, PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let target_column_id = ColumnId::new(target_column_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let mut card = repo.get_card(&card_id)?.ok_or(RepositoryError::CardNotFound)?;
        if card.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let position = next_position(
            repo.list_column_cards(&card.board_id, &target_column_id, true)?
                .into_iter()
                .filter(|candidate| candidate.id != card_id)
                .map(|candidate| candidate.position.get()),
        )?;
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit(PlannerTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerMutation::MoveCard {
                card_id: card_id.clone(),
                target_column_id: target_column_id.clone(),
                position,
            }],
        })?;
        card.column_id = target_column_id;
        card.position = position;
        Ok(card_view(card))
    }

    pub fn swap_card_order(
        &self,
        workspace_id: &str,
        card_id: &str,
        other_card_id: &str,
    ) -> Result<(), PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let other_card_id = CardId::new(other_card_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let card = repo.get_card(&card_id)?.ok_or(RepositoryError::CardNotFound)?;
        let other = repo.get_card(&other_card_id)?.ok_or(RepositoryError::CardNotFound)?;
        if card.workspace_id != workspace_id
            || other.workspace_id != workspace_id
            || card.board_id != other.board_id
            || card.column_id != other.column_id
        {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit(PlannerTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerMutation::ReorderColumn {
                column_id: card.column_id,
                positions: vec![
                    (card_id, other.position),
                    (other_card_id, card.position),
                ],
            }],
        })?;
        Ok(())
    }

    pub fn set_card_archived(
        &self,
        workspace_id: &str,
        card_id: &str,
        archived: bool,
    ) -> Result<CardView, PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let mut card = repo.get_card(&card_id)?.ok_or(RepositoryError::CardNotFound)?;
        if card.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit(PlannerTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerMutation::SetCardArchived {
                card_id,
                archived,
            }],
        })?;
        card.lifecycle = if archived { CardLifecycle::Archived } else { CardLifecycle::Active };
        Ok(card_view(card))
    }

    pub fn delete_card(&self, workspace_id: &str, card_id: &str) -> Result<(), PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let card = repo.get_card(&card_id)?.ok_or(RepositoryError::CardNotFound)?;
        if card.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let version = repo.allocate_local_version()?;
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit(PlannerTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerMutation::DeleteCard { card_id, version }],
        })?;
        Ok(())
    }

    pub fn list_checklists(
        &self,
        workspace_id: &str,
        card_id: &str,
    ) -> Result<Vec<ChecklistView>, PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let card = repo.get_card(&card_id)?.ok_or(RepositoryError::CardNotFound)?;
        if card.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        Ok(repo.list_card_checklists(&card_id)?.into_iter().map(checklist_view).collect())
    }

    pub fn create_checklist(
        &self,
        workspace_id: &str,
        card_id: &str,
        title: &str,
    ) -> Result<ChecklistView, PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let card = repo.get_card(&card_id)?.ok_or(RepositoryError::CardNotFound)?;
        if card.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let position = next_position(
            repo.list_card_checklists(&card_id)?
                .into_iter()
                .map(|item| item.position.get()),
        )?;
        let checklist = ChecklistRecord {
            id: self.ids.checklist_id(),
            workspace_id: workspace_id.clone(),
            board_id: card.board_id,
            card_id,
            title: normalized_title(title)?,
            position,
        };
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerFeatureMutation::CreateChecklist(checklist.clone())],
        })?;
        Ok(checklist_view(checklist))
    }

    pub fn delete_checklist(
        &self,
        workspace_id: &str,
        checklist_id: &str,
    ) -> Result<(), PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let checklist_id = ChecklistId::new(checklist_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let checklist = repo.get_checklist(&checklist_id)?.ok_or(RepositoryError::ChecklistNotFound)?;
        if checklist.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let version = repo.allocate_local_version()?;
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerFeatureMutation::DeleteChecklist { checklist_id, version }],
        })?;
        Ok(())
    }

    pub fn list_checklist_items(
        &self,
        workspace_id: &str,
        checklist_id: &str,
    ) -> Result<Vec<ChecklistItemView>, PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let checklist_id = ChecklistId::new(checklist_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let checklist = repo.get_checklist(&checklist_id)?.ok_or(RepositoryError::ChecklistNotFound)?;
        if checklist.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        Ok(repo.list_checklist_items(&checklist_id)?.into_iter().map(checklist_item_view).collect())
    }

    pub fn create_checklist_item(
        &self,
        workspace_id: &str,
        checklist_id: &str,
        title: &str,
    ) -> Result<ChecklistItemView, PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let checklist_id = ChecklistId::new(checklist_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let checklist = repo.get_checklist(&checklist_id)?.ok_or(RepositoryError::ChecklistNotFound)?;
        if checklist.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let position = next_position(
            repo.list_checklist_items(&checklist_id)?
                .into_iter()
                .map(|item| item.position.get()),
        )?;
        let item = ChecklistItemRecord {
            id: self.ids.checklist_item_id(),
            checklist_id,
            title: normalized_title(title)?,
            position,
            is_done: false,
        };
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerFeatureMutation::CreateChecklistItem(item.clone())],
        })?;
        Ok(checklist_item_view(item))
    }

    pub fn set_checklist_item_done(
        &self,
        workspace_id: &str,
        item_id: &str,
        done: bool,
    ) -> Result<ChecklistItemView, PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let item_id = ChecklistItemId::new(item_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let mut item = repo.get_checklist_item(&item_id)?.ok_or(RepositoryError::ChecklistItemNotFound)?;
        let checklist = repo.get_checklist(&item.checklist_id)?.ok_or(RepositoryError::ChecklistNotFound)?;
        if checklist.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerFeatureMutation::SetChecklistItemDone {
                item_id,
                done,
            }],
        })?;
        item.is_done = done;
        Ok(checklist_item_view(item))
    }

    pub fn delete_checklist_item(
        &self,
        workspace_id: &str,
        item_id: &str,
    ) -> Result<(), PlannerServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let item_id = ChecklistItemId::new(item_id).map_err(|_| PlannerServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        let item = repo.get_checklist_item(&item_id)?.ok_or(RepositoryError::ChecklistItemNotFound)?;
        let checklist = repo.get_checklist(&item.checklist_id)?.ok_or(RepositoryError::ChecklistNotFound)?;
        if checklist.workspace_id != workspace_id {
            return Err(RepositoryError::ScopeMismatch.into());
        }
        let version = repo.allocate_local_version()?;
        let epoch = repo.current_access_epoch(&workspace_id)?;
        repo.commit_features(PlannerFeatureTransaction {
            workspace_id,
            access_epoch: epoch,
            mutations: vec![PlannerFeatureMutation::DeleteChecklistItem { item_id, version }],
        })?;
        Ok(())
    }

    pub fn pending_change_count(
        &self,
        workspace_id: &str,
        board_id: &str,
    ) -> Result<u64, PlannerServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let repo = self.repository.lock().map_err(|_| PlannerServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        repo.pending_change_count(&board_id).map_err(Into::into)
    }
}
