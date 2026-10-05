use serde_json::Value;

use crate::domain::planner::{BoardId, CardId, OrderKey, WorkspaceId};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LabelId(String);

impl LabelId {
    pub fn new(value: impl Into<String>) -> Result<Self, ParityValueError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ParityValueError::EmptyId("label"));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommentId(String);

impl CommentId {
    pub fn new(value: impl Into<String>) -> Result<Self, ParityValueError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ParityValueError::EmptyId("comment"));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivityEntryId(String);

impl ActivityEntryId {
    pub fn new(value: impl Into<String>) -> Result<Self, ParityValueError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ParityValueError::EmptyId("activity"));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParityValueError {
    EmptyId(&'static str),
    InvalidJson,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LabelRecord {
    pub id: LabelId,
    pub board_id: BoardId,
    pub name: String,
    pub color: Option<String>,
    pub position: OrderKey,
    pub raw_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CardLabelRecord {
    pub card_id: CardId,
    pub label_id: LabelId,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommentRecord {
    pub id: CommentId,
    pub workspace_id: WorkspaceId,
    pub board_id: BoardId,
    pub card_id: CardId,
    pub author_user_id: Option<String>,
    pub body: String,
    pub created_at: String,
    pub updated_at: String,
    pub raw_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoardAppearanceRecord {
    pub board_id: BoardId,
    pub settings_json: String,
    pub updated_at: String,
}

impl BoardAppearanceRecord {
    pub fn settings(&self) -> Result<Value, ParityValueError> {
        serde_json::from_str(&self.settings_json).map_err(|_| ParityValueError::InvalidJson)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivityEntryRecord {
    pub id: ActivityEntryId,
    pub workspace_id: WorkspaceId,
    pub board_id: BoardId,
    pub card_id: Option<CardId>,
    pub actor_user_id: Option<String>,
    pub kind: String,
    pub entity_type: String,
    pub entity_id: Option<String>,
    pub payload_json: String,
    pub occurred_at: String,
}
