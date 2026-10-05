use std::collections::{BTreeMap, BTreeSet};

use crate::{
    application::repository::{
        PlannerMutation, PlannerRepository, PlannerTransaction, RepositoryError,
    },
    domain::planner::{
        compare_card_order, AccessEpoch, BoardId, CardId, CardLifecycle, CardRecord, CardTombstone,
        ColumnId, OrderKey, VersionStamp, WorkspaceId,
    },
};

#[derive(Debug, Clone)]
struct MemoryState {
    epochs: BTreeMap<WorkspaceId, AccessEpoch>,
    boards: BTreeMap<BoardId, WorkspaceId>,
    columns: BTreeMap<ColumnId, BoardId>,
    cards: BTreeMap<CardId, CardRecord>,
    tombstones: BTreeMap<CardId, CardTombstone>,
}

#[derive(Debug, Clone)]
struct InMemoryPlannerRepository {
    state: MemoryState,
}

impl InMemoryPlannerRepository {
    fn fixture() -> Self {
        let workspace = workspace_id();
        let board = board_id();
        let column_a = column_a_id();
        let column_b = column_b_id();
        Self {
            state: MemoryState {
                epochs: BTreeMap::from([(workspace.clone(), epoch(3))]),
                boards: BTreeMap::from([(board.clone(), workspace)]),
                columns: BTreeMap::from([(column_a, board.clone()), (column_b, board)]),
                cards: BTreeMap::new(),
                tombstones: BTreeMap::new(),
            },
        }
    }

    fn apply_mutation(
        state: &mut MemoryState,
        workspace_id: &WorkspaceId,
        mutation: PlannerMutation,
    ) -> Result<(), RepositoryError> {
        match mutation {
            PlannerMutation::CreateCard(card) => {
                let board_workspace = state
                    .boards
                    .get(&card.board_id)
                    .ok_or(RepositoryError::BoardNotFound)?;
                let column_board = state
                    .columns
                    .get(&card.column_id)
                    .ok_or(RepositoryError::ColumnNotFound)?;
                if board_workspace != workspace_id
                    || &card.workspace_id != workspace_id
                    || column_board != &card.board_id
                {
                    return Err(RepositoryError::ScopeMismatch);
                }
                if state.tombstones.contains_key(&card.id) {
                    return Err(RepositoryError::Tombstoned);
                }
                if state.cards.contains_key(&card.id) {
                    return Err(RepositoryError::DuplicateCard);
                }
                state.cards.insert(card.id.clone(), card);
            }
            PlannerMutation::MoveCard {
                card_id,
                target_column_id,
                position,
            } => {
                let card = state
                    .cards
                    .get(&card_id)
                    .ok_or(RepositoryError::CardNotFound)?;
                if &card.workspace_id != workspace_id {
                    return Err(RepositoryError::ScopeMismatch);
                }
                let target_board = state
                    .columns
                    .get(&target_column_id)
                    .ok_or(RepositoryError::ColumnNotFound)?;
                if target_board != &card.board_id {
                    return Err(RepositoryError::ScopeMismatch);
                }
                let card = state.cards.get_mut(&card_id).expect("card existence checked");
                card.column_id = target_column_id;
                card.position = position;
            }
            PlannerMutation::SetCardArchived { card_id, archived } => {
                let card = state
                    .cards
                    .get_mut(&card_id)
                    .ok_or(RepositoryError::CardNotFound)?;
                if &card.workspace_id != workspace_id {
                    return Err(RepositoryError::ScopeMismatch);
                }
                card.lifecycle = if archived {
                    CardLifecycle::Archived
                } else {
                    CardLifecycle::Active
                };
            }
            PlannerMutation::DeleteCard { card_id, version } => {
                if let Some(existing) = state.tombstones.get_mut(&card_id) {
                    if &existing.workspace_id != workspace_id {
                        return Err(RepositoryError::ScopeMismatch);
                    }
                    if version > existing.version {
                        existing.version = version;
                    }
                    return Ok(());
                }
                let card = state
                    .cards
                    .remove(&card_id)
                    .ok_or(RepositoryError::CardNotFound)?;
                if &card.workspace_id != workspace_id {
                    state.cards.insert(card.id.clone(), card);
                    return Err(RepositoryError::ScopeMismatch);
                }
                state.tombstones.insert(
                    card_id.clone(),
                    CardTombstone {
                        workspace_id: card.workspace_id,
                        board_id: card.board_id,
                        card_id,
                        version,
                    },
                );
            }
            PlannerMutation::ReorderColumn { column_id, positions } => {
                let target_board = state
                    .columns
                    .get(&column_id)
                    .ok_or(RepositoryError::ColumnNotFound)?
                    .clone();
                let board_workspace = state
                    .boards
                    .get(&target_board)
                    .ok_or(RepositoryError::BoardNotFound)?;
                if board_workspace != workspace_id {
                    return Err(RepositoryError::ScopeMismatch);
                }

                let mut seen = BTreeSet::new();
                for (card_id, _) in &positions {
                    if !seen.insert(card_id.clone()) {
                        return Err(RepositoryError::DuplicateReorderItem);
                    }
                    let card = state
                        .cards
                        .get(card_id)
                        .ok_or(RepositoryError::CardNotFound)?;
                    if card.board_id != target_board || card.column_id != column_id {
                        return Err(RepositoryError::ScopeMismatch);
                    }
                }
                for (card_id, position) in positions {
                    state
                        .cards
                        .get_mut(&card_id)
                        .expect("reorder membership checked")
                        .position = position;
                }
            }
        }
        Ok(())
    }
}

impl PlannerRepository for InMemoryPlannerRepository {
    fn current_access_epoch(
        &self,
        workspace_id: &WorkspaceId,
    ) -> Result<AccessEpoch, RepositoryError> {
        self.state
            .epochs
            .get(workspace_id)
            .copied()
            .ok_or(RepositoryError::WorkspaceNotFound)
    }

    fn get_card(&self, card_id: &CardId) -> Result<Option<CardRecord>, RepositoryError> {
        Ok(self.state.cards.get(card_id).cloned())
    }

    fn get_card_tombstone(
        &self,
        card_id: &CardId,
    ) -> Result<Option<CardTombstone>, RepositoryError> {
        Ok(self.state.tombstones.get(card_id).cloned())
    }

    fn list_column_cards(
        &self,
        board_id: &BoardId,
        column_id: &ColumnId,
        include_archived: bool,
    ) -> Result<Vec<CardRecord>, RepositoryError> {
        let column_board = self
            .state
            .columns
            .get(column_id)
            .ok_or(RepositoryError::ColumnNotFound)?;
        if column_board != board_id {
            return Err(RepositoryError::ScopeMismatch);
        }
        let mut cards = self
            .state
            .cards
            .values()
            .filter(|card| {
                &card.board_id == board_id
                    && &card.column_id == column_id
                    && (include_archived || card.lifecycle == CardLifecycle::Active)
            })
            .cloned()
            .collect::<Vec<_>>();
        cards.sort_by(compare_card_order);
        Ok(cards)
    }

    fn commit(&mut self, transaction: PlannerTransaction) -> Result<(), RepositoryError> {
        let current = self.current_access_epoch(&transaction.workspace_id)?;
        if current != transaction.access_epoch {
            return Err(RepositoryError::StaleAccessEpoch {
                provided: transaction.access_epoch,
                current,
            });
        }
        let mut candidate = self.state.clone();
        for mutation in transaction.mutations {
            Self::apply_mutation(&mut candidate, &transaction.workspace_id, mutation)?;
        }
        self.state = candidate;
        Ok(())
    }
}

fn workspace_id() -> WorkspaceId {
    WorkspaceId::new("018f0000-0000-7000-8000-000000000001").unwrap()
}

fn board_id() -> BoardId {
    BoardId::new("018f0000-0000-7000-8000-000000000002").unwrap()
}

fn column_a_id() -> ColumnId {
    ColumnId::new("018f0000-0000-7000-8000-000000000005").unwrap()
}

fn column_b_id() -> ColumnId {
    ColumnId::new("018f0000-0000-7000-8000-000000000006").unwrap()
}

fn card_id(value: &str) -> CardId {
    CardId::new(value).unwrap()
}

fn epoch(value: u64) -> AccessEpoch {
    AccessEpoch::new(value).unwrap()
}

fn order(value: f64) -> OrderKey {
    OrderKey::new(value).unwrap()
}

fn version(clock: u64, event: &str) -> VersionStamp {
    VersionStamp::new(clock, "fixture-replica-a04", event).unwrap()
}

fn active_card(id: &str, column_id: ColumnId, position: f64) -> CardRecord {
    CardRecord {
        id: card_id(id),
        workspace_id: workspace_id(),
        board_id: board_id(),
        column_id,
        title: id.to_string(),
        position: order(position),
        lifecycle: CardLifecycle::Active,
    }
}

fn transaction(mutations: Vec<PlannerMutation>) -> PlannerTransaction {
    PlannerTransaction {
        workspace_id: workspace_id(),
        access_epoch: epoch(3),
        mutations,
    }
}

fn create<R: PlannerRepository>(repo: &mut R, card: CardRecord) {
    repo.commit(transaction(vec![PlannerMutation::CreateCard(card)]))
        .unwrap();
}

/// Generic semantic scenario entry point. The next durable adapter must call
/// the same logical assertions rather than inventing an adapter-specific suite.
pub(crate) fn assert_repository_contract<R: PlannerRepository>(mut repo: R) {
    let first = active_card(
        "018f0000-0000-7000-8000-000000000101",
        column_a_id(),
        1000.0,
    );
    let second = active_card(
        "018f0000-0000-7000-8000-000000000100",
        column_a_id(),
        1000.0,
    );
    create(&mut repo, first.clone());
    create(&mut repo, second.clone());

    let ordered = repo
        .list_column_cards(&board_id(), &column_a_id(), false)
        .unwrap();
    assert_eq!(
        ordered.iter().map(|card| card.id.as_str()).collect::<Vec<_>>(),
        vec![second.id.as_str(), first.id.as_str()],
        "equal position values must use stable card-id tie-break ordering"
    );

    repo.commit(transaction(vec![PlannerMutation::MoveCard {
        card_id: first.id.clone(),
        target_column_id: column_b_id(),
        position: order(250.0),
    }]))
    .unwrap();
    let moved = repo.get_card(&first.id).unwrap().unwrap();
    assert_eq!(moved.column_id, column_b_id());
    assert_eq!(moved.position, order(250.0));

    repo.commit(transaction(vec![PlannerMutation::SetCardArchived {
        card_id: first.id.clone(),
        archived: true,
    }]))
    .unwrap();
    assert!(repo
        .list_column_cards(&board_id(), &column_b_id(), false)
        .unwrap()
        .is_empty());
    assert_eq!(
        repo.list_column_cards(&board_id(), &column_b_id(), true)
            .unwrap()
            .len(),
        1,
        "archive is reversible visibility state, not deletion"
    );
    repo.commit(transaction(vec![PlannerMutation::SetCardArchived {
        card_id: first.id.clone(),
        archived: false,
    }]))
    .unwrap();

    repo.commit(transaction(vec![PlannerMutation::DeleteCard {
        card_id: first.id.clone(),
        version: version(42, "delete-42"),
    }]))
    .unwrap();
    assert!(repo.get_card(&first.id).unwrap().is_none());
    let tombstone = repo.get_card_tombstone(&first.id).unwrap().unwrap();
    assert_eq!(tombstone.version, version(42, "delete-42"));

    let resurrection = repo.commit(transaction(vec![PlannerMutation::CreateCard(first)]));
    assert_eq!(resurrection, Err(RepositoryError::Tombstoned));

    repo.commit(transaction(vec![PlannerMutation::DeleteCard {
        card_id: tombstone.card_id.clone(),
        version: version(41, "delete-41"),
    }]))
    .unwrap();
    assert_eq!(
        repo.get_card_tombstone(&tombstone.card_id)
            .unwrap()
            .unwrap()
            .version,
        version(42, "delete-42"),
        "older duplicate delete must not lower the tombstone version"
    );
}

pub(crate) fn assert_stale_epoch_contract<R: PlannerRepository>(mut repo: R) {
    let card = active_card("card-stale-epoch", column_a_id(), 100.0);
    let result = repo.commit(PlannerTransaction {
        workspace_id: workspace_id(),
        access_epoch: epoch(2),
        mutations: vec![PlannerMutation::CreateCard(card.clone())],
    });
    assert_eq!(
        result,
        Err(RepositoryError::StaleAccessEpoch {
            provided: epoch(2),
            current: epoch(3),
        })
    );
    assert!(repo.get_card(&card.id).unwrap().is_none());
}

pub(crate) fn assert_atomic_rollback_contract<R: PlannerRepository>(mut repo: R) {
    let card = active_card("card-atomic", column_a_id(), 100.0);
    create(&mut repo, card.clone());

    let result = repo.commit(transaction(vec![
        PlannerMutation::MoveCard {
            card_id: card.id.clone(),
            target_column_id: column_b_id(),
            position: order(200.0),
        },
        PlannerMutation::MoveCard {
            card_id: card_id("missing-card"),
            target_column_id: column_b_id(),
            position: order(300.0),
        },
    ]));
    assert_eq!(result, Err(RepositoryError::CardNotFound));

    let after = repo.get_card(&card.id).unwrap().unwrap();
    assert_eq!(after.column_id, column_a_id());
    assert_eq!(after.position, order(100.0));
}

pub(crate) fn assert_reorder_contract<R: PlannerRepository>(mut repo: R) {
    let card_a = active_card("card-a", column_a_id(), 100.0);
    let card_b = active_card("card-b", column_a_id(), 200.0);
    let card_other = active_card("card-other", column_b_id(), 300.0);
    create(&mut repo, card_a.clone());
    create(&mut repo, card_b.clone());
    create(&mut repo, card_other.clone());

    repo.commit(transaction(vec![PlannerMutation::ReorderColumn {
        column_id: column_a_id(),
        positions: vec![
            (card_a.id.clone(), order(900.0)),
            (card_b.id.clone(), order(100.0)),
        ],
    }]))
    .unwrap();
    let ordered = repo
        .list_column_cards(&board_id(), &column_a_id(), false)
        .unwrap();
    assert_eq!(ordered[0].id, card_b.id);
    assert_eq!(ordered[1].id, card_a.id);

    let before_a = repo.get_card(&card_a.id).unwrap().unwrap().position;
    let invalid = repo.commit(transaction(vec![PlannerMutation::ReorderColumn {
        column_id: column_a_id(),
        positions: vec![
            (card_a.id.clone(), order(10.0)),
            (card_other.id.clone(), order(20.0)),
        ],
    }]));
    assert_eq!(invalid, Err(RepositoryError::ScopeMismatch));
    assert_eq!(repo.get_card(&card_a.id).unwrap().unwrap().position, before_a);
}

#[test]
fn in_memory_reference_adapter_passes_repository_semantics() {
    assert_repository_contract(InMemoryPlannerRepository::fixture());
}

#[test]
fn stale_capability_epoch_rejects_the_entire_transaction() {
    assert_stale_epoch_contract(InMemoryPlannerRepository::fixture());
}

#[test]
fn failing_batch_rolls_back_earlier_mutations() {
    assert_atomic_rollback_contract(InMemoryPlannerRepository::fixture());
}

#[test]
fn reorder_is_atomic_column_scoped_and_deterministic() {
    assert_reorder_contract(InMemoryPlannerRepository::fixture());
}
