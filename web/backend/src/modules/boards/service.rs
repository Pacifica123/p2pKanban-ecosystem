use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    state::AppState,
};

use super::dto::{
    BoardListResponse, BoardResponse, ColumnListResponse, ColumnResponse, CreateBoardRequest,
    CreateColumnRequest, ListBoardsQuery, UpdateBoardRequest, UpdateColumnRequest,
};

pub async fn list_boards(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    query: ListBoardsQuery,
) -> AppResult<BoardListResponse> {
    super::repo::list_boards(&state.db, actor_user_id, workspace_id, query).await
}

pub async fn create_board(
    state: &AppState,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    payload: CreateBoardRequest,
) -> AppResult<BoardResponse> {
    if payload.name.trim().is_empty() {
        return Err(AppError::bad_request("Board name is required"));
    }
    if let Some(board_type) = &payload.board_type {
        if board_type != "kanban" {
            return Err(AppError::bad_request(
                "Only kanban boards are supported in v1",
            ));
        }
    }

    super::repo::create_board(&state.db, actor_user_id, workspace_id, payload).await
}

pub async fn get_board(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<BoardResponse> {
    super::repo::get_board(&state.db, actor_user_id, board_id).await
}

pub async fn update_board(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: UpdateBoardRequest,
) -> AppResult<BoardResponse> {
    if let Some(name) = &payload.name {
        if name.trim().is_empty() {
            return Err(AppError::bad_request("Board name cannot be empty"));
        }
    }

    super::repo::update_board(&state.db, actor_user_id, board_id, payload).await
}

pub async fn delete_board(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<BoardResponse> {
    super::repo::delete_board(&state.db, actor_user_id, board_id).await
}

pub async fn archive_board(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<BoardResponse> {
    super::repo::archive_board(&state.db, actor_user_id, board_id).await
}

pub async fn list_columns(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<ColumnListResponse> {
    super::repo::list_columns(&state.db, actor_user_id, board_id).await
}

pub async fn create_column(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: CreateColumnRequest,
) -> AppResult<ColumnResponse> {
    if payload.name.trim().is_empty() {
        return Err(AppError::bad_request("Column name is required"));
    }
    if matches!(payload.wip_limit, Some(limit) if limit < 0) {
        return Err(AppError::bad_request("wipLimit must be zero or positive"));
    }

    super::repo::create_column(&state.db, actor_user_id, board_id, payload).await
}

pub async fn update_column(
    state: &AppState,
    actor_user_id: Uuid,
    column_id: Uuid,
    payload: UpdateColumnRequest,
) -> AppResult<ColumnResponse> {
    if let Some(name) = &payload.name {
        if name.trim().is_empty() {
            return Err(AppError::bad_request("Column name cannot be empty"));
        }
    }
    if let Some(Some(limit)) = payload.wip_limit {
        if limit < 0 {
            return Err(AppError::bad_request("wipLimit must be zero or positive"));
        }
    }

    super::repo::update_column(&state.db, actor_user_id, column_id, payload).await
}

pub async fn delete_column(
    state: &AppState,
    actor_user_id: Uuid,
    column_id: Uuid,
) -> AppResult<ColumnResponse> {
    super::repo::delete_column(&state.db, actor_user_id, column_id).await
}
