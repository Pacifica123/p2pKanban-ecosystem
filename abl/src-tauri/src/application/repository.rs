use crate::domain::planner::{
    AccessEpoch, BoardId, CardId, CardRecord, CardTombstone, ColumnId, OrderKey,
    VersionStamp, WorkspaceId,
};

#[derive(Debug, Clone, PartialEq)]
pub enum PlannerMutation {
    CreateCard(CardRecord),
    MoveCard {
        card_id: CardId,
        target_column_id: ColumnId,
        position: OrderKey,
    },
    SetCardArchived {
        card_id: CardId,
        archived: bool,
    },
    DeleteCard {
        card_id: CardId,
        version: VersionStamp,
    },
    ReorderColumn {
        column_id: ColumnId,
        positions: Vec<(CardId, OrderKey)>,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlannerTransaction {
    pub workspace_id: WorkspaceId,
    pub access_epoch: AccessEpoch,
    pub mutations: Vec<PlannerMutation>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RepositoryError {
    WorkspaceNotFound,
    StaleAccessEpoch {
        provided: AccessEpoch,
        current: AccessEpoch,
    },
    BoardNotFound,
    ColumnNotFound,
    CardNotFound,
    ScopeMismatch,
    DuplicateCard,
    DuplicateColumn,
    DuplicateChecklist,
    DuplicateChecklistItem,
    ChecklistNotFound,
    ChecklistItemNotFound,
    DuplicateReorderItem,
    Tombstoned,
    StorageFailure,
}

pub trait PlannerRepository {
    fn current_access_epoch(
        &self,
        workspace_id: &WorkspaceId,
    ) -> Result<AccessEpoch, RepositoryError>;

    fn get_card(&self, card_id: &CardId) -> Result<Option<CardRecord>, RepositoryError>;

    fn get_card_tombstone(
        &self,
        card_id: &CardId,
    ) -> Result<Option<CardTombstone>, RepositoryError>;

    fn list_column_cards(
        &self,
        board_id: &BoardId,
        column_id: &ColumnId,
        include_archived: bool,
    ) -> Result<Vec<CardRecord>, RepositoryError>;

    /// Apply all mutations atomically. On any error the repository-visible
    /// state must be exactly the state observed before the call.
    fn commit(&mut self, transaction: PlannerTransaction) -> Result<(), RepositoryError>;
}

#[cfg(test)]
pub(crate) mod contract;
