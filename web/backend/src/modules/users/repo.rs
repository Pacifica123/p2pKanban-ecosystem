use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    auth::repo as auth_repo,
    error::{AppError, AppResult},
};

use super::dto::{DeviceResponse, MeResponse};

pub async fn get_current_user(pool: &PgPool, actor_user_id: Uuid) -> AppResult<MeResponse> {
    let Some(user) = auth_repo::find_active_user_by_id(pool, actor_user_id).await? else {
        return Err(AppError::unauthorized(
            "Authenticated user is not active anymore",
        ));
    };

    Ok(MeResponse {
        id: user.id.to_string(),
        email: user.email,
        display_name: user.display_name,
    })
}

pub async fn list_devices(pool: &PgPool, actor_user_id: Uuid) -> AppResult<Vec<DeviceResponse>> {
    let rows = sqlx::query(
        r#"
        select id, display_name, platform
        from devices
        where user_id = $1
          and deleted_at is null
          and revoked_at is null
        order by last_seen_at desc nulls last, created_at desc
        "#,
    )
    .bind(actor_user_id)
    .fetch_all(pool)
    .await?;

    rows.into_iter()
        .map(|row| {
            Ok(DeviceResponse {
                id: row.try_get::<Uuid, _>("id")?.to_string(),
                display_name: row.try_get("display_name")?,
                platform: row.try_get("platform")?,
            })
        })
        .collect()
}

pub async fn revoke_device(pool: &PgPool, actor_user_id: Uuid, device_id: Uuid) -> AppResult<()> {
    auth_repo::revoke_device(pool, actor_user_id, device_id).await
}
