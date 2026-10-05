use thiserror::Error;
use uuid::Uuid;

use crate::{ClientChangeEvent, SyncEnvelope, SYNC_PROTOCOL_VERSION};

const ENTITY_TYPES: &[&str] = &[
    "workspace",
    "workspace_member",
    "board",
    "column",
    "card",
    "board_label",
    "card_label",
    "checklist",
    "checklist_item",
    "comment",
];

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ValidationError {
    #[error("{field} must be a valid UUID")]
    InvalidUuid { field: &'static str },
    #[error("replicaSeq must be positive")]
    InvalidReplicaSequence,
    #[error("logicalClock must be positive")]
    InvalidLogicalClock,
    #[error("baseServerOrder must not be negative")]
    InvalidBaseServerOrder,
    #[error("unsupported entityType: {0}")]
    UnsupportedEntityType(String),
    #[error("unsupported operation: {0}")]
    UnsupportedOperation(String),
    #[error("fieldMask must not contain empty or duplicate paths")]
    InvalidFieldMask,
    #[error("unsupported protocolVersion: {0}")]
    UnsupportedProtocolVersion(String),
    #[error("envelopeId must match eventId")]
    EnvelopeIdMismatch,
    #[error("workspaceId must be a valid UUID")]
    InvalidWorkspaceId,
}

pub fn normalize_operation(operation: &str) -> Option<&'static str> {
    match operation {
        "create" => Some("create"),
        "update" | "move" | "complete" => Some("update"),
        "delete" => Some("delete"),
        "restore" => Some("restore"),
        "reorder" => Some("reorder"),
        "add" => Some("add"),
        "remove" => Some("remove"),
        "archive" => Some("archive"),
        "unarchive" => Some("unarchive"),
        _ => None,
    }
}

fn parse_uuid(value: &str, field: &'static str) -> Result<(), ValidationError> {
    Uuid::parse_str(value)
        .map(|_| ())
        .map_err(|_| ValidationError::InvalidUuid { field })
}

pub fn validate_client_event(event: &ClientChangeEvent) -> Result<(), ValidationError> {
    parse_uuid(&event.event_id, "eventId")?;
    parse_uuid(&event.replica_id, "event.replicaId")?;
    parse_uuid(&event.entity_id, "entityId")?;

    if event.replica_seq < 1 {
        return Err(ValidationError::InvalidReplicaSequence);
    }
    if event.logical_clock < 1 {
        return Err(ValidationError::InvalidLogicalClock);
    }
    if event.base_server_order.is_some_and(|value| value < 0) {
        return Err(ValidationError::InvalidBaseServerOrder);
    }
    if !ENTITY_TYPES.contains(&event.entity_type.as_str()) {
        return Err(ValidationError::UnsupportedEntityType(
            event.entity_type.clone(),
        ));
    }
    if normalize_operation(&event.operation).is_none() {
        return Err(ValidationError::UnsupportedOperation(
            event.operation.clone(),
        ));
    }

    if let Some(field_mask) = &event.field_mask {
        let mut normalized = field_mask
            .iter()
            .map(|item| item.trim())
            .collect::<Vec<_>>();
        if normalized.iter().any(|item| item.is_empty()) {
            return Err(ValidationError::InvalidFieldMask);
        }
        normalized.sort_unstable();
        if normalized.windows(2).any(|items| items[0] == items[1]) {
            return Err(ValidationError::InvalidFieldMask);
        }
    }

    Ok(())
}

pub fn validate_envelope(envelope: &SyncEnvelope) -> Result<(), ValidationError> {
    if envelope.protocol_version != SYNC_PROTOCOL_VERSION {
        return Err(ValidationError::UnsupportedProtocolVersion(
            envelope.protocol_version.clone(),
        ));
    }
    if envelope.envelope_id != envelope.event.event_id {
        return Err(ValidationError::EnvelopeIdMismatch);
    }
    Uuid::parse_str(&envelope.workspace_id).map_err(|_| ValidationError::InvalidWorkspaceId)?;

    let event = ClientChangeEvent {
        event_id: envelope.event.event_id.clone(),
        replica_id: envelope.event.replica_id.clone(),
        replica_seq: envelope.event.replica_seq,
        entity_type: envelope.event.entity_type.clone(),
        entity_id: envelope.event.entity_id.clone(),
        operation: envelope.event.operation.clone(),
        field_mask: Some(envelope.event.field_mask.clone()),
        logical_clock: envelope.event.logical_clock,
        base_server_order: envelope.event.base_server_order,
        occurred_at: Some(envelope.event.accepted_at.clone()),
        payload: envelope.event.payload.clone(),
        metadata: envelope.event.metadata.clone(),
    };
    validate_client_event(&event)
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn event() -> ClientChangeEvent {
        ClientChangeEvent {
            event_id: "018f22e2-1d58-7f08-9a36-1f96bd9854b1".to_string(),
            replica_id: "018f22e2-29cc-7ad6-aa57-b61d74a14e52".to_string(),
            replica_seq: 1,
            entity_type: "card".to_string(),
            entity_id: "018f22e2-355a-7ba2-8ef0-d7bc788ceec8".to_string(),
            operation: "update".to_string(),
            field_mask: Some(vec!["title".to_string()]),
            logical_clock: 3,
            base_server_order: Some(2),
            occurred_at: None,
            payload: json!({"title": "new"}),
            metadata: json!({}),
        }
    }

    #[test]
    fn accepts_valid_event() {
        assert_eq!(validate_client_event(&event()), Ok(()));
    }

    #[test]
    fn rejects_duplicate_field_paths() {
        let mut event = event();
        event.field_mask = Some(vec!["title".to_string(), "title".to_string()]);
        assert_eq!(
            validate_client_event(&event),
            Err(ValidationError::InvalidFieldMask)
        );
    }
}
