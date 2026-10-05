use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use uuid::Uuid;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::{
    dto::{
        CreateBoardRequest, CreateColumnRequest, ListBoardsQuery, UpdateBoardRequest,
        UpdateColumnRequest,
    },
    service,
};

pub async fn list_boards(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
    Query(query): Query<ListBoardsQuery>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let boards = service::list_boards(&state, actor, workspace_id, query).await?;
    Ok(ok(boards))
}

pub async fn create_board(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(workspace_id): Path<Uuid>,
    Json(payload): Json<CreateBoardRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let board = service::create_board(&state, actor, workspace_id, payload).await?;
    Ok((StatusCode::CREATED, ok(board)))
}

pub async fn get_board(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let board = service::get_board(&state, actor, board_id).await?;
    Ok(ok(board))
}

pub async fn update_board(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
    Json(payload): Json<UpdateBoardRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let board = service::update_board(&state, actor, board_id, payload).await?;
    Ok(ok(board))
}

pub async fn delete_board(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let board = service::delete_board(&state, actor, board_id).await?;
    Ok(ok(board))
}

pub async fn archive_board(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let board = service::archive_board(&state, actor, board_id).await?;
    Ok(ok(board))
}

pub async fn list_columns(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let columns = service::list_columns(&state, actor, board_id).await?;
    Ok(ok(columns))
}

pub async fn create_column(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
    Json(payload): Json<CreateColumnRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let column = service::create_column(&state, actor, board_id, payload).await?;
    Ok((StatusCode::CREATED, ok(column)))
}

pub async fn update_column(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(column_id): Path<Uuid>,
    Json(payload): Json<UpdateColumnRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let column = service::update_column(&state, actor, column_id, payload).await?;
    Ok(ok(column))
}

pub async fn delete_column(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(column_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let column = service::delete_column(&state, actor, column_id).await?;
    Ok(ok(column))
}

pub async fn update_column_scoped(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path((_board_id, column_id)): Path<(Uuid, Uuid)>,
    Json(payload): Json<UpdateColumnRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let column = service::update_column(&state, actor, column_id, payload).await?;
    Ok(ok(column))
}

pub async fn delete_column_scoped(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path((_board_id, column_id)): Path<(Uuid, Uuid)>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let column = service::delete_column(&state, actor, column_id).await?;
    Ok(ok(column))
}
