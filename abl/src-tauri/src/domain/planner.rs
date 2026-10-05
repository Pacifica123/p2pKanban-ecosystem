use std::cmp::Ordering;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlannerValueError {
    EmptyId(&'static str),
    InvalidAccessEpoch,
    InvalidOrderKey,
    EmptyVersionComponent(&'static str),
}

macro_rules! id_type {
    ($name:ident, $label:literal) => {
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, PlannerValueError> {
                let value = value.into();
                if value.trim().is_empty() {
                    return Err(PlannerValueError::EmptyId($label));
                }
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }
    };
}

id_type!(WorkspaceId, "workspace");
id_type!(BoardId, "board");
id_type!(ColumnId, "column");
id_type!(CardId, "card");
id_type!(ChecklistId, "checklist");
id_type!(ChecklistItemId, "checklist_item");

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceRecord {
    pub id: WorkspaceId,
    pub title: String,
    pub access_epoch: AccessEpoch,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoardRecord {
    pub id: BoardId,
    pub workspace_id: WorkspaceId,
    pub title: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ColumnRecord {
    pub id: ColumnId,
    pub board_id: BoardId,
    pub title: String,
    pub position: OrderKey,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct AccessEpoch(u64);

impl AccessEpoch {
    pub fn new(value: u64) -> Result<Self, PlannerValueError> {
        if value == 0 {
            return Err(PlannerValueError::InvalidAccessEpoch);
        }
        Ok(Self(value))
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct OrderKey(f64);

impl OrderKey {
    pub fn new(value: f64) -> Result<Self, PlannerValueError> {
        if !value.is_finite() {
            return Err(PlannerValueError::InvalidOrderKey);
        }
        Ok(Self(value))
    }

    pub const fn get(self) -> f64 {
        self.0
    }

    pub fn compare(self, other: Self) -> Ordering {
        self.0.total_cmp(&other.0)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VersionStamp {
    pub logical_clock: u64,
    pub replica_id: String,
    pub event_id: String,
}

impl VersionStamp {
    pub fn new(
        logical_clock: u64,
        replica_id: impl Into<String>,
        event_id: impl Into<String>,
    ) -> Result<Self, PlannerValueError> {
        let replica_id = replica_id.into();
        let event_id = event_id.into();
        if replica_id.trim().is_empty() {
            return Err(PlannerValueError::EmptyVersionComponent("replica_id"));
        }
        if event_id.trim().is_empty() {
            return Err(PlannerValueError::EmptyVersionComponent("event_id"));
        }
        Ok(Self {
            logical_clock,
            replica_id,
            event_id,
        })
    }
}

impl Ord for VersionStamp {
    fn cmp(&self, other: &Self) -> Ordering {
        self.logical_clock
            .cmp(&other.logical_clock)
            .then_with(|| self.replica_id.cmp(&other.replica_id))
            .then_with(|| self.event_id.cmp(&other.event_id))
    }
}

impl PartialOrd for VersionStamp {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CardLifecycle {
    Active,
    Archived,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CardRecord {
    pub id: CardId,
    pub workspace_id: WorkspaceId,
    pub board_id: BoardId,
    pub column_id: ColumnId,
    pub title: String,
    pub position: OrderKey,
    pub lifecycle: CardLifecycle,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CardTombstone {
    pub workspace_id: WorkspaceId,
    pub board_id: BoardId,
    pub card_id: CardId,
    pub version: VersionStamp,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChecklistRecord {
    pub id: ChecklistId,
    pub workspace_id: WorkspaceId,
    pub board_id: BoardId,
    pub card_id: CardId,
    pub title: String,
    pub position: OrderKey,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChecklistItemRecord {
    pub id: ChecklistItemId,
    pub checklist_id: ChecklistId,
    pub title: String,
    pub position: OrderKey,
    pub is_done: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChecklistTombstone {
    pub workspace_id: WorkspaceId,
    pub board_id: BoardId,
    pub card_id: CardId,
    pub checklist_id: ChecklistId,
    pub version: VersionStamp,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChecklistItemTombstone {
    pub workspace_id: WorkspaceId,
    pub board_id: BoardId,
    pub card_id: CardId,
    pub checklist_id: ChecklistId,
    pub item_id: ChecklistItemId,
    pub version: VersionStamp,
}

pub fn compare_card_order(left: &CardRecord, right: &CardRecord) -> Ordering {
    left.position
        .compare(right.position)
        .then_with(|| left.id.cmp(&right.id))
}

pub fn compare_column_order(left: &ColumnRecord, right: &ColumnRecord) -> Ordering {
    left.position
        .compare(right.position)
        .then_with(|| left.id.cmp(&right.id))
}

pub fn compare_checklist_order(left: &ChecklistRecord, right: &ChecklistRecord) -> Ordering {
    left.position
        .compare(right.position)
        .then_with(|| left.id.cmp(&right.id))
}

pub fn compare_checklist_item_order(
    left: &ChecklistItemRecord,
    right: &ChecklistItemRecord,
) -> Ordering {
    left.position
        .compare(right.position)
        .then_with(|| left.id.cmp(&right.id))
}

#[cfg(test)]
mod tests {
    use super::{
        compare_card_order, AccessEpoch, BoardId, CardId, CardLifecycle, CardRecord, ColumnId,
        OrderKey, VersionStamp, WorkspaceId,
    };

    fn card(id: &str, position: f64) -> CardRecord {
        CardRecord {
            id: CardId::new(id).unwrap(),
            workspace_id: WorkspaceId::new("workspace-a").unwrap(),
            board_id: BoardId::new("board-a").unwrap(),
            column_id: ColumnId::new("column-a").unwrap(),
            title: id.to_string(),
            position: OrderKey::new(position).unwrap(),
            lifecycle: CardLifecycle::Active,
        }
    }

    #[test]
    fn version_order_matches_roaming_comparator() {
        let low_clock = VersionStamp::new(4, "z-replica", "z-event").unwrap();
        let high_clock = VersionStamp::new(5, "a-replica", "a-event").unwrap();
        let replica_tie_break = VersionStamp::new(5, "b-replica", "a-event").unwrap();
        let event_tie_break = VersionStamp::new(5, "b-replica", "b-event").unwrap();

        assert!(low_clock < high_clock);
        assert!(high_clock < replica_tie_break);
        assert!(replica_tie_break < event_tie_break);
    }

    #[test]
    fn card_order_is_numeric_position_then_stable_id() {
        let mut cards = vec![card("card-b", 1000.0), card("card-a", 1000.0), card("card-c", 500.0)];
        cards.sort_by(compare_card_order);
        let ids = cards.iter().map(|card| card.id.as_str()).collect::<Vec<_>>();
        assert_eq!(ids, vec!["card-c", "card-a", "card-b"]);
    }

    #[test]
    fn epoch_zero_and_non_finite_order_keys_are_invalid() {
        assert!(AccessEpoch::new(0).is_err());
        assert!(OrderKey::new(f64::NAN).is_err());
        assert!(OrderKey::new(f64::INFINITY).is_err());
    }
}
