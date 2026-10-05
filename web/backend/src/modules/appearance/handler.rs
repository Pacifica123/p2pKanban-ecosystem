use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use uuid::Uuid;

use crate::{
    error::AppResult, http::response::ok, modules::common::actor_user_id, state::AppState,
};

use super::{
    dto::{UpdateBoardAppearanceRequest, UpdateUserAppearancePreferencesRequest},
    service,
};

pub async fn get_my_preferences(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let preferences = service::get_my_preferences(&state, actor).await?;
    Ok(ok(preferences))
}

pub async fn upsert_my_preferences(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<UpdateUserAppearancePreferencesRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let preferences = service::upsert_my_preferences(&state, actor, payload).await?;
    Ok((StatusCode::OK, ok(preferences)))
}

pub async fn get_board_appearance(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let appearance = service::get_board_appearance(&state, actor, board_id).await?;
    Ok(ok(appearance))
}

pub async fn upsert_board_appearance(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(board_id): Path<Uuid>,
    Json(payload): Json<UpdateBoardAppearanceRequest>,
) -> AppResult<impl IntoResponse> {
    let actor = actor_user_id(&state, &headers).await?;
    let appearance = service::upsert_board_appearance(&state, actor, board_id, payload).await?;
    Ok((StatusCode::OK, ok(appearance)))
}
