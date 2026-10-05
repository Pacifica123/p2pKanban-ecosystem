use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    state::AppState,
};

use super::dto::{
    ChecklistItemResponse, ChecklistListResponse, ChecklistResponse, CreateChecklistItemRequest,
    CreateChecklistRequest, UpdateChecklistItemRequest, UpdateChecklistRequest,
};

fn validate_title(value: &str, label: &str) -> AppResult<()> {
    if value.trim().is_empty() {
        return Err(AppError::bad_request(format!("{label} is required")));
    }
    Ok(())
}

fn validate_position(value: Option<f64>, label: &str) -> AppResult<()> {
    if matches!(value, Some(position) if !position.is_finite()) {
        return Err(AppError::bad_request(format!(
            "{label} must be a finite number"
        )));
    }
    Ok(())
}

pub async fn list_checklists(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<ChecklistListResponse> {
    super::repo::list_checklists(&state.db, actor_user_id, card_id).await
}

pub async fn create_checklist(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: CreateChecklistRequest,
) -> AppResult<ChecklistResponse> {
    validate_title(&payload.title, "Checklist title")?;
    validate_position(payload.position, "Checklist position")?;
    super::repo::create_checklist(&state.db, actor_user_id, card_id, payload).await
}

pub async fn update_checklist(
    state: &AppState,
    actor_user_id: Uuid,
    checklist_id: Uuid,
    payload: UpdateChecklistRequest,
) -> AppResult<ChecklistResponse> {
    if let Some(title) = &payload.title {
        validate_title(title, "Checklist title")?;
    }
    validate_position(payload.position, "Checklist position")?;
    super::repo::update_checklist(&state.db, actor_user_id, checklist_id, payload).await
}

pub async fn delete_checklist(
    state: &AppState,
    actor_user_id: Uuid,
    checklist_id: Uuid,
) -> AppResult<ChecklistResponse> {
    super::repo::delete_checklist(&state.db, actor_user_id, checklist_id).await
}

pub async fn create_item(
    state: &AppState,
    actor_user_id: Uuid,
    checklist_id: Uuid,
    payload: CreateChecklistItemRequest,
) -> AppResult<ChecklistItemResponse> {
    validate_title(&payload.title, "Checklist item title")?;
    validate_position(payload.position, "Checklist item position")?;
    super::repo::create_item(&state.db, actor_user_id, checklist_id, payload).await
}

pub async fn update_item(
    state: &AppState,
    actor_user_id: Uuid,
    item_id: Uuid,
    payload: UpdateChecklistItemRequest,
) -> AppResult<ChecklistItemResponse> {
    if let Some(title) = &payload.title {
        validate_title(title, "Checklist item title")?;
    }
    validate_position(payload.position, "Checklist item position")?;
    super::repo::update_item(&state.db, actor_user_id, item_id, payload).await
}

pub async fn delete_item(
    state: &AppState,
    actor_user_id: Uuid,
    item_id: Uuid,
) -> AppResult<ChecklistItemResponse> {
    super::repo::delete_item(&state.db, actor_user_id, item_id).await
}
