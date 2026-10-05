use std::sync::Mutex;

use serde_json::Value;
use time::{format_description::well_known::Rfc3339, OffsetDateTime};
use uuid::Uuid;

use crate::domain::{
    parity::{ActivityEntryId, ActivityEntryRecord, BoardAppearanceRecord, CardLabelRecord, CommentId, CommentRecord, LabelId, LabelRecord},
    planner::{BoardId, CardId, OrderKey, WorkspaceId},
};

const MAX_LABEL_CHARS: usize = 120;
const MAX_COMMENT_CHARS: usize = 65_536;
const MAX_COLOR_CHARS: usize = 128;
const MAX_APPEARANCE_BYTES: usize = 65_536;
const LOCAL_APPEND_STEP: f64 = 1000.0;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParityRepositoryError {
    WorkspaceNotFound,
    BoardNotFound,
    CardNotFound,
    LabelNotFound,
    CommentNotFound,
    ScopeMismatch,
    DuplicateLabel,
    DuplicateComment,
    StorageFailure,
}

pub trait ParityRepository {
    fn board_workspace(&self, board_id: &BoardId) -> Result<WorkspaceId, ParityRepositoryError>;
    fn card_scope(&self, card_id: &CardId) -> Result<(WorkspaceId, BoardId), ParityRepositoryError>;
    fn list_labels(&self, board_id: &BoardId) -> Result<Vec<LabelRecord>, ParityRepositoryError>;
    fn create_label(&mut self, workspace_id: &WorkspaceId, label: LabelRecord, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError>;
    fn delete_label(&mut self, workspace_id: &WorkspaceId, board_id: &BoardId, label_id: &LabelId, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError>;
    fn list_card_labels(&self, card_id: &CardId) -> Result<Vec<CardLabelRecord>, ParityRepositoryError>;
    fn set_card_label(&mut self, workspace_id: &WorkspaceId, board_id: &BoardId, edge: CardLabelRecord, assigned: bool, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError>;
    fn list_comments(&self, card_id: &CardId) -> Result<Vec<CommentRecord>, ParityRepositoryError>;
    fn comment_board(&self, comment_id: &CommentId, workspace_id: &WorkspaceId) -> Result<BoardId, ParityRepositoryError>;
    fn create_comment(&mut self, comment: CommentRecord, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError>;
    fn delete_comment(&mut self, workspace_id: &WorkspaceId, board_id: &BoardId, comment_id: &CommentId, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError>;
    fn get_appearance(&self, board_id: &BoardId) -> Result<Option<BoardAppearanceRecord>, ParityRepositoryError>;
    fn set_appearance(&mut self, workspace_id: &WorkspaceId, appearance: BoardAppearanceRecord, activity: ActivityEntryRecord) -> Result<(), ParityRepositoryError>;
    fn list_activity(&self, board_id: &BoardId, limit: usize) -> Result<Vec<ActivityEntryRecord>, ParityRepositoryError>;
    fn unsynced_parity_count(&self, board_id: &BoardId) -> Result<u64, ParityRepositoryError>;
}

pub trait ParityIdGenerator: Send + Sync {
    fn label_id(&self) -> LabelId;
    fn comment_id(&self) -> CommentId;
    fn activity_id(&self) -> ActivityEntryId;
}

#[derive(Default)]
pub struct RandomParityIds;

impl ParityIdGenerator for RandomParityIds {
    fn label_id(&self) -> LabelId {
        LabelId::new(Uuid::new_v4().to_string()).expect("UUID must be non-empty")
    }

    fn comment_id(&self) -> CommentId {
        CommentId::new(Uuid::new_v4().to_string()).expect("UUID must be non-empty")
    }

    fn activity_id(&self) -> ActivityEntryId {
        ActivityEntryId::new(Uuid::new_v4().to_string()).expect("UUID must be non-empty")
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct LabelView {
    pub id: String,
    pub board_id: String,
    pub name: String,
    pub color: Option<String>,
    pub position: f64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommentView {
    pub id: String,
    pub card_id: String,
    pub author_user_id: Option<String>,
    pub body: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppearanceView {
    pub board_id: String,
    pub settings_json: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivityView {
    pub id: String,
    pub board_id: String,
    pub card_id: Option<String>,
    pub actor_user_id: Option<String>,
    pub kind: String,
    pub entity_type: String,
    pub entity_id: Option<String>,
    pub payload_json: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParityServiceError {
    InvalidId,
    EmptyValue,
    ValueTooLong,
    InvalidJson,
    Repository(ParityRepositoryError),
    RepositoryPoisoned,
}

impl From<ParityRepositoryError> for ParityServiceError {
    fn from(value: ParityRepositoryError) -> Self {
        Self::Repository(value)
    }
}

fn now_rfc3339() -> Result<String, ParityServiceError> {
    OffsetDateTime::now_utc()
        .format(&Rfc3339)
        .map_err(|_| ParityServiceError::Repository(ParityRepositoryError::StorageFailure))
}

fn normalized(value: &str, max: usize) -> Result<String, ParityServiceError> {
    let value = value.trim();
    if value.is_empty() {
        return Err(ParityServiceError::EmptyValue);
    }
    if value.chars().count() > max {
        return Err(ParityServiceError::ValueTooLong);
    }
    Ok(value.to_owned())
}

fn label_view(value: LabelRecord) -> LabelView {
    LabelView {
        id: value.id.as_str().to_owned(),
        board_id: value.board_id.as_str().to_owned(),
        name: value.name,
        color: value.color,
        position: value.position.get(),
    }
}

fn comment_view(value: CommentRecord) -> CommentView {
    CommentView {
        id: value.id.as_str().to_owned(),
        card_id: value.card_id.as_str().to_owned(),
        author_user_id: value.author_user_id,
        body: value.body,
        created_at: value.created_at,
        updated_at: value.updated_at,
    }
}

fn appearance_view(value: BoardAppearanceRecord) -> AppearanceView {
    AppearanceView {
        board_id: value.board_id.as_str().to_owned(),
        settings_json: value.settings_json,
        updated_at: value.updated_at,
    }
}

fn activity_view(value: ActivityEntryRecord) -> ActivityView {
    ActivityView {
        id: value.id.as_str().to_owned(),
        board_id: value.board_id.as_str().to_owned(),
        card_id: value.card_id.map(|id| id.as_str().to_owned()),
        actor_user_id: value.actor_user_id,
        kind: value.kind,
        entity_type: value.entity_type,
        entity_id: value.entity_id,
        payload_json: value.payload_json,
        occurred_at: value.occurred_at,
    }
}

pub struct ParityService {
    repository: Mutex<Box<dyn ParityRepository + Send>>,
    ids: Box<dyn ParityIdGenerator>,
}

impl ParityService {
    pub fn new(repository: Box<dyn ParityRepository + Send>, ids: Box<dyn ParityIdGenerator>) -> Self {
        Self { repository: Mutex::new(repository), ids }
    }

    fn ids(workspace_id: &str, board_id: &str) -> Result<(WorkspaceId, BoardId), ParityServiceError> {
        Ok((
            WorkspaceId::new(workspace_id).map_err(|_| ParityServiceError::InvalidId)?,
            BoardId::new(board_id).map_err(|_| ParityServiceError::InvalidId)?,
        ))
    }

    fn ensure_board_scope(repo: &dyn ParityRepository, workspace_id: &WorkspaceId, board_id: &BoardId) -> Result<(), ParityServiceError> {
        if repo.board_workspace(board_id)? != *workspace_id {
            return Err(ParityRepositoryError::ScopeMismatch.into());
        }
        Ok(())
    }

    fn activity(&self, workspace_id: WorkspaceId, board_id: BoardId, card_id: Option<CardId>, kind: &str, entity_type: &str, entity_id: Option<String>, payload: Value, occurred_at: String) -> Result<ActivityEntryRecord, ParityServiceError> {
        Ok(ActivityEntryRecord {
            id: self.ids.activity_id(), workspace_id, board_id, card_id,
            actor_user_id: None,
            kind: kind.to_owned(), entity_type: entity_type.to_owned(), entity_id,
            payload_json: serde_json::to_string(&payload).map_err(|_| ParityServiceError::InvalidJson)?,
            occurred_at,
        })
    }

    pub fn list_labels(&self, workspace_id: &str, board_id: &str) -> Result<Vec<LabelView>, ParityServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        Ok(repo.list_labels(&board_id)?.into_iter().map(label_view).collect())
    }

    pub fn create_label(&self, workspace_id: &str, board_id: &str, name: &str, color: Option<&str>) -> Result<LabelView, ParityServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let mut repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        let labels = repo.list_labels(&board_id)?;
        let position = labels.iter().map(|value| value.position.get()).fold(0.0_f64, f64::max) + LOCAL_APPEND_STEP;
        let name = normalized(name, MAX_LABEL_CHARS)?;
        let color = match color.map(str::trim).filter(|value| !value.is_empty()) {
            Some(value) if value.chars().count() > MAX_COLOR_CHARS => return Err(ParityServiceError::ValueTooLong),
            Some(value) => Some(value.to_owned()),
            None => None,
        };
        let label = LabelRecord {
            id: self.ids.label_id(), board_id: board_id.clone(), name: name.clone(), color: color.clone(),
            position: OrderKey::new(position).map_err(|_| ParityServiceError::Repository(ParityRepositoryError::StorageFailure))?,
            raw_json: "{}".into(),
        };
        let at = now_rfc3339()?;
        let activity = self.activity(workspace_id.clone(), board_id.clone(), None, "label.create", "label", Some(label.id.as_str().to_owned()), serde_json::json!({"name": name, "color": color}), at)?;
        repo.create_label(&workspace_id, label.clone(), activity)?;
        Ok(label_view(label))
    }

    pub fn delete_label(&self, workspace_id: &str, board_id: &str, label_id: &str) -> Result<(), ParityServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let label_id = LabelId::new(label_id).map_err(|_| ParityServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        let at = now_rfc3339()?;
        let activity = self.activity(workspace_id.clone(), board_id.clone(), None, "label.delete", "label", Some(label_id.as_str().to_owned()), serde_json::json!({}), at)?;
        repo.delete_label(&workspace_id, &board_id, &label_id, activity)?;
        Ok(())
    }

    pub fn list_card_label_ids(&self, workspace_id: &str, card_id: &str) -> Result<Vec<String>, ParityServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| ParityServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| ParityServiceError::InvalidId)?;
        let repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        let (actual_workspace, _) = repo.card_scope(&card_id)?;
        if actual_workspace != workspace_id { return Err(ParityRepositoryError::ScopeMismatch.into()); }
        Ok(repo.list_card_labels(&card_id)?.into_iter().map(|edge| edge.label_id.as_str().to_owned()).collect())
    }

    pub fn set_card_label(&self, workspace_id: &str, card_id: &str, label_id: &str, assigned: bool) -> Result<(), ParityServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| ParityServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| ParityServiceError::InvalidId)?;
        let label_id = LabelId::new(label_id).map_err(|_| ParityServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        let (actual_workspace, board_id) = repo.card_scope(&card_id)?;
        if actual_workspace != workspace_id { return Err(ParityRepositoryError::ScopeMismatch.into()); }
        let edge = CardLabelRecord { card_id: card_id.clone(), label_id: label_id.clone() };
        let at = now_rfc3339()?;
        let kind = if assigned { "card.label.assign" } else { "card.label.unassign" };
        let activity = self.activity(workspace_id.clone(), board_id.clone(), Some(card_id), kind, "label", Some(label_id.as_str().to_owned()), serde_json::json!({"assigned": assigned}), at)?;
        repo.set_card_label(&workspace_id, &board_id, edge, assigned, activity)?;
        Ok(())
    }

    pub fn list_comments(&self, workspace_id: &str, card_id: &str) -> Result<Vec<CommentView>, ParityServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| ParityServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| ParityServiceError::InvalidId)?;
        let repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        let (actual_workspace, _) = repo.card_scope(&card_id)?;
        if actual_workspace != workspace_id { return Err(ParityRepositoryError::ScopeMismatch.into()); }
        Ok(repo.list_comments(&card_id)?.into_iter().map(comment_view).collect())
    }

    pub fn create_comment(&self, workspace_id: &str, card_id: &str, body: &str) -> Result<CommentView, ParityServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| ParityServiceError::InvalidId)?;
        let card_id = CardId::new(card_id).map_err(|_| ParityServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        let (actual_workspace, board_id) = repo.card_scope(&card_id)?;
        if actual_workspace != workspace_id { return Err(ParityRepositoryError::ScopeMismatch.into()); }
        let body = normalized(body, MAX_COMMENT_CHARS)?;
        let at = now_rfc3339()?;
        let comment = CommentRecord {
            id: self.ids.comment_id(), workspace_id: workspace_id.clone(), board_id: board_id.clone(), card_id: card_id.clone(),
            author_user_id: None, body: body.clone(), created_at: at.clone(), updated_at: at.clone(), raw_json: "{}".into(),
        };
        let activity = self.activity(workspace_id, board_id, Some(card_id), "comment.create", "comment", Some(comment.id.as_str().to_owned()), serde_json::json!({"bodyLength": body.chars().count()}), at)?;
        repo.create_comment(comment.clone(), activity)?;
        Ok(comment_view(comment))
    }

    pub fn delete_comment(&self, workspace_id: &str, comment_id: &str) -> Result<(), ParityServiceError> {
        let workspace_id = WorkspaceId::new(workspace_id).map_err(|_| ParityServiceError::InvalidId)?;
        let comment_id = CommentId::new(comment_id).map_err(|_| ParityServiceError::InvalidId)?;
        let mut repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        // Scope is established atomically by the repository from the comment row; the service
        // supplies the caller workspace and receives no comment body back across the boundary.
        let board_id = repo.comment_board(&comment_id, &workspace_id)?;
        let at = now_rfc3339()?;
        let activity = self.activity(workspace_id.clone(), board_id.clone(), None, "comment.delete", "comment", Some(comment_id.as_str().to_owned()), serde_json::json!({}), at)?;
        repo.delete_comment(&workspace_id, &board_id, &comment_id, activity)?;
        Ok(())
    }

    pub fn get_appearance(&self, workspace_id: &str, board_id: &str) -> Result<AppearanceView, ParityServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        if let Some(value) = repo.get_appearance(&board_id)? { return Ok(appearance_view(value)); }
        Ok(AppearanceView { board_id: board_id.as_str().to_owned(), settings_json: format!("{{\"boardId\":\"{}\"}}", board_id.as_str()), updated_at: String::new() })
    }

    pub fn set_appearance(&self, workspace_id: &str, board_id: &str, settings_json: &str) -> Result<AppearanceView, ParityServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let mut repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        if settings_json.as_bytes().len() > MAX_APPEARANCE_BYTES { return Err(ParityServiceError::ValueTooLong); }
        let mut object = serde_json::from_str::<Value>(settings_json).map_err(|_| ParityServiceError::InvalidJson)?
            .as_object().cloned().ok_or(ParityServiceError::InvalidJson)?;
        object.insert("boardId".into(), Value::String(board_id.as_str().to_owned()));
        let normalized = serde_json::to_string(&Value::Object(object)).map_err(|_| ParityServiceError::InvalidJson)?;
        let at = now_rfc3339()?;
        let appearance = BoardAppearanceRecord { board_id: board_id.clone(), settings_json: normalized.clone(), updated_at: at.clone() };
        let activity = self.activity(workspace_id.clone(), board_id.clone(), None, "board.appearance.put", "board", Some(appearance.board_id.as_str().to_owned()), serde_json::json!({"appearance": serde_json::from_str::<Value>(&normalized).map_err(|_| ParityServiceError::InvalidJson)?}), at)?;
        repo.set_appearance(&workspace_id, appearance.clone(), activity)?;
        Ok(appearance_view(appearance))
    }

    pub fn list_activity(&self, workspace_id: &str, board_id: &str, limit: usize) -> Result<Vec<ActivityView>, ParityServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        let limit = limit.clamp(1, 200);
        Ok(repo.list_activity(&board_id, limit)?.into_iter().map(activity_view).collect())
    }

    pub fn unsynced_parity_count(&self, workspace_id: &str, board_id: &str) -> Result<u64, ParityServiceError> {
        let (workspace_id, board_id) = Self::ids(workspace_id, board_id)?;
        let repo = self.repository.lock().map_err(|_| ParityServiceError::RepositoryPoisoned)?;
        Self::ensure_board_scope(repo.as_ref(), &workspace_id, &board_id)?;
        Ok(repo.unsynced_parity_count(&board_id)?)
    }
}
