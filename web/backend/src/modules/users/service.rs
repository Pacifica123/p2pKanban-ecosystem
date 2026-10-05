use uuid::Uuid;

use crate::{error::AppResult, state::AppState};

use super::dto::{DeviceResponse, MeResponse};

pub async fn get_current_user(state: &AppState, actor_user_id: Uuid) -> AppResult<MeResponse> {
    super::repo::get_current_user(&state.db, actor_user_id).await
}

pub async fn list_devices(state: &AppState, actor_user_id: Uuid) -> AppResult<Vec<DeviceResponse>> {
    super::repo::list_devices(&state.db, actor_user_id).await
}

pub async fn revoke_device(
    state: &AppState,
    actor_user_id: Uuid,
    device_id: Uuid,
) -> AppResult<()> {
    super::repo::revoke_device(&state.db, actor_user_id, device_id).await
}
