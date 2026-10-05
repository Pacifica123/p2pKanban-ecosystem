use std::collections::HashSet;

use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    state::AppState,
};

use super::dto::{
    CreateLabelRequest, LabelListResponse, LabelResponse, ReplaceCardLabelsRequest,
    UpdateLabelRequest,
};
use crate::modules::cards::dto::CardResponse;

fn validate_label_name(name: &str) -> AppResult<()> {
    if name.trim().is_empty() {
        return Err(AppError::bad_request("Label name is required"));
    }
    Ok(())
}

fn validate_label_color(color: &str) -> AppResult<()> {
    if color.trim().is_empty() {
        return Err(AppError::bad_request("Label color is required"));
    }
    Ok(())
}

pub async fn list_labels(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<LabelListResponse> {
    super::repo::list_labels(&state.db, actor_user_id, board_id).await
}

pub async fn create_label(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: CreateLabelRequest,
) -> AppResult<LabelResponse> {
    validate_label_name(&payload.name)?;
    validate_label_color(&payload.color)?;
    super::repo::create_label(&state.db, actor_user_id, board_id, payload).await
}

pub async fn update_label(
    state: &AppState,
    actor_user_id: Uuid,
    label_id: Uuid,
    payload: UpdateLabelRequest,
) -> AppResult<LabelResponse> {
    if let Some(name) = &payload.name {
        validate_label_name(name)?;
    }
    if let Some(color) = &payload.color {
        validate_label_color(color)?;
    }
    super::repo::update_label(&state.db, actor_user_id, label_id, payload).await
}

pub async fn delete_label(
    state: &AppState,
    actor_user_id: Uuid,
    label_id: Uuid,
) -> AppResult<LabelResponse> {
    super::repo::delete_label(&state.db, actor_user_id, label_id).await
}

pub async fn replace_card_labels(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: ReplaceCardLabelsRequest,
) -> AppResult<CardResponse> {
    let mut seen = HashSet::with_capacity(payload.label_ids.len());
    for label_id in &payload.label_ids {
        if !seen.insert(*label_id) {
            return Err(AppError::bad_request("Duplicate labelId in labelIds"));
        }
    }
    super::repo::replace_card_labels(&state.db, actor_user_id, card_id, payload).await
}
