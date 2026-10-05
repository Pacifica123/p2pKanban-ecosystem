use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    state::AppState,
};

use super::dto::{
    CommentListResponse, CommentResponse, CreateCommentRequest, ListCommentsQuery,
    UpdateCommentRequest,
};

fn validate_body(body: &str) -> AppResult<()> {
    if body.trim().is_empty() {
        return Err(AppError::bad_request("Comment body is required"));
    }
    Ok(())
}

pub async fn list_comments(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
    query: ListCommentsQuery,
) -> AppResult<CommentListResponse> {
    super::repo::list_comments(&state.db, actor_user_id, card_id, query).await
}

pub async fn create_comment(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: CreateCommentRequest,
) -> AppResult<CommentResponse> {
    validate_body(&payload.body)?;
    super::repo::create_comment(&state.db, actor_user_id, card_id, payload).await
}

pub async fn update_comment(
    state: &AppState,
    actor_user_id: Uuid,
    comment_id: Uuid,
    payload: UpdateCommentRequest,
) -> AppResult<CommentResponse> {
    if let Some(body) = &payload.body {
        validate_body(body)?;
    }
    super::repo::update_comment(&state.db, actor_user_id, comment_id, payload).await
}

pub async fn delete_comment(
    state: &AppState,
    actor_user_id: Uuid,
    comment_id: Uuid,
) -> AppResult<CommentResponse> {
    super::repo::delete_comment(&state.db, actor_user_id, comment_id).await
}
