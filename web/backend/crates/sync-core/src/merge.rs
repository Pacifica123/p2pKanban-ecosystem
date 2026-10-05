use std::cmp::Ordering;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct VersionStamp {
    pub logical_clock: i64,
    pub replica_id: String,
    pub event_id: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MergeDecision {
    Left,
    Right,
    Equal,
}

pub fn choose_winner(left: &VersionStamp, right: &VersionStamp) -> MergeDecision {
    match left
        .logical_clock
        .cmp(&right.logical_clock)
        .then_with(|| left.replica_id.cmp(&right.replica_id))
        .then_with(|| left.event_id.cmp(&right.event_id))
    {
        Ordering::Greater => MergeDecision::Left,
        Ordering::Less => MergeDecision::Right,
        Ordering::Equal => MergeDecision::Equal,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn logical_clock_wins_before_tie_breakers() {
        let left = VersionStamp {
            logical_clock: 9,
            replica_id: "a".to_string(),
            event_id: "a".to_string(),
        };
        let right = VersionStamp {
            logical_clock: 8,
            replica_id: "z".to_string(),
            event_id: "z".to_string(),
        };
        assert_eq!(choose_winner(&left, &right), MergeDecision::Left);
    }

    #[test]
    fn replica_and_event_make_parallel_replay_deterministic() {
        let left = VersionStamp {
            logical_clock: 9,
            replica_id: "replica-a".to_string(),
            event_id: "event-z".to_string(),
        };
        let right = VersionStamp {
            logical_clock: 9,
            replica_id: "replica-b".to_string(),
            event_id: "event-a".to_string(),
        };
        assert_eq!(choose_winner(&left, &right), MergeDecision::Right);
    }
}
