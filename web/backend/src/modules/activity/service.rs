use uuid::Uuid;

use crate::{error::AppResult, state::AppState};

use super::dto::{
    ActivityListResponse, BoardProductivityQuery, BoardProductivityResponse, ListActivityQuery,
};

pub async fn get_board_productivity(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
    query: BoardProductivityQuery,
) -> AppResult<BoardProductivityResponse> {
    super::repo::get_board_productivity(
        &state.db,
        actor_user_id,
        board_id,
        query.days.unwrap_or(84),
    )
    .await
}

pub async fn list_board_activity(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
    query: ListActivityQuery,
) -> AppResult<ActivityListResponse> {
    super::repo::list_board_activity(&state.db, actor_user_id, board_id, query).await
}

pub async fn list_card_activity(
    state: &AppState,
    actor_user_id: Uuid,
    card_id: Uuid,
    query: ListActivityQuery,
) -> AppResult<ActivityListResponse> {
    super::repo::list_card_activity(&state.db, actor_user_id, card_id, query).await
}
