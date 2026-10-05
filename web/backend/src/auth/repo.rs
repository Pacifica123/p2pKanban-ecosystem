use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::error::{AppError, AppResult};

use super::dto::DevBootstrapUserResponse;

#[derive(Debug, Clone)]
pub struct AuthUserRecord {
    pub id: Uuid,
    pub email: String,
    pub display_name: String,
    pub password_hash: Option<String>,
}

#[derive(Debug, Clone)]
pub struct DeviceRecord {
    pub id: Uuid,
    pub display_name: String,
    pub platform: String,
}

#[derive(Debug, Clone)]
pub struct SessionRecord {
    pub id: Uuid,
    pub user_id: Uuid,
    pub device_id: Uuid,
    pub email: String,
    pub display_name: String,
}

#[derive(Debug, Clone)]
pub struct SessionLookupRecord {
    pub session_id: Uuid,
    pub user_id: Uuid,
    pub device_id: Option<Uuid>,
    pub email: String,
    pub display_name: String,
    pub revoked: bool,
}

pub async fn bootstrap_dev_user(
    pool: &PgPool,
    user_id: Uuid,
    email: &str,
    display_name: &str,
) -> AppResult<DevBootstrapUserResponse> {
    let conflicting_user_id = sqlx::query_scalar::<_, Uuid>(
        r#"
        select id
        from users
        where lower(email) = lower($1)
          and deleted_at is null
          and id <> $2
        limit 1
        "#,
    )
    .bind(email)
    .bind(user_id)
    .fetch_optional(pool)
    .await?;

    if conflicting_user_id.is_some() {
        return Err(AppError::conflict(
            "Another active user already uses this email",
        ));
    }

    let row = sqlx::query(
        r#"
        insert into users (id, email, display_name, password_hash, deleted_at)
        values ($1, $2, $3, null, null)
        on conflict (id) do update
          set email = excluded.email,
              display_name = excluded.display_name,
              deleted_at = null,
              updated_at = now()
        returning id, email, display_name
        "#,
    )
    .bind(user_id)
    .bind(email)
    .bind(display_name)
    .fetch_one(pool)
    .await?;

    Ok(DevBootstrapUserResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        email: row.try_get("email")?,
        display_name: row.try_get("display_name")?,
        mode: "dev_header",
    })
}

pub async fn find_active_user_by_email(
    pool: &PgPool,
    email: &str,
) -> AppResult<Option<AuthUserRecord>> {
    let row = sqlx::query(
        r#"
        select id, email, display_name, password_hash
        from users
        where lower(email) = lower($1)
          and deleted_at is null
        limit 1
        "#,
    )
    .bind(email)
    .fetch_optional(pool)
    .await?;

    row.map(map_auth_user).transpose()
}

pub async fn find_active_user_by_id(
    pool: &PgPool,
    user_id: Uuid,
) -> AppResult<Option<AuthUserRecord>> {
    let row = sqlx::query(
        r#"
        select id, email, display_name, password_hash
        from users
        where id = $1
          and deleted_at is null
        limit 1
        "#,
    )
    .bind(user_id)
    .fetch_optional(pool)
    .await?;

    row.map(map_auth_user).transpose()
}

pub async fn create_user(
    pool: &PgPool,
    user_id: Uuid,
    email: &str,
    display_name: &str,
    password_hash: &str,
) -> AppResult<AuthUserRecord> {
    let row = sqlx::query(
        r#"
        insert into users (id, email, display_name, password_hash)
        values ($1, $2, $3, $4)
        returning id, email, display_name, password_hash
        "#,
    )
    .bind(user_id)
    .bind(email)
    .bind(display_name)
    .bind(password_hash)
    .fetch_one(pool)
    .await?;

    map_auth_user(row)
}

pub async fn resolve_or_create_device(
    pool: &PgPool,
    cookie_device_id: Option<Uuid>,
    user_id: Uuid,
    display_name: &str,
    platform: &str,
) -> AppResult<DeviceRecord> {
    if let Some(device_id) = cookie_device_id {
        let row = sqlx::query(
            r#"
            select id, display_name, platform
            from devices
            where id = $1
              and user_id = $2
              and deleted_at is null
              and revoked_at is null
            limit 1
            "#,
        )
        .bind(device_id)
        .bind(user_id)
        .fetch_optional(pool)
        .await?;

        if let Some(row) = row {
            sqlx::query(
                r#"
                update devices
                set last_seen_at = now(),
                    updated_at = now()
                where id = $1
                "#,
            )
            .bind(device_id)
            .execute(pool)
            .await?;

            return Ok(DeviceRecord {
                id: row.try_get("id")?,
                display_name: row.try_get("display_name")?,
                platform: row.try_get("platform")?,
            });
        }
    }

    let device_id = Uuid::now_v7();
    let row = sqlx::query(
        r#"
        insert into devices (id, user_id, display_name, platform, last_seen_at)
        values ($1, $2, $3, $4, now())
        returning id, display_name, platform
        "#,
    )
    .bind(device_id)
    .bind(user_id)
    .bind(display_name)
    .bind(platform)
    .fetch_one(pool)
    .await?;

    Ok(DeviceRecord {
        id: row.try_get("id")?,
        display_name: row.try_get("display_name")?,
        platform: row.try_get("platform")?,
    })
}

pub async fn create_session(
    pool: &PgPool,
    user: &AuthUserRecord,
    device: &DeviceRecord,
    refresh_token_hash: &str,
    user_agent: Option<&str>,
    ip_address: Option<&str>,
    refresh_ttl_days: i64,
) -> AppResult<SessionRecord> {
    let session_id = Uuid::now_v7();
    sqlx::query(
        r#"
        insert into user_sessions (
          id,
          user_id,
          device_id,
          refresh_token_hash,
          user_agent,
          ip_address,
          last_seen_at,
          expires_at
        )
        values (
          $1,
          $2,
          $3,
          $4,
          $5,
          nullif($6, '')::inet,
          now(),
          now() + ($7 * interval '1 day')
        )
        "#,
    )
    .bind(session_id)
    .bind(user.id)
    .bind(device.id)
    .bind(refresh_token_hash)
    .bind(user_agent)
    .bind(ip_address.unwrap_or_default())
    .bind(refresh_ttl_days)
    .execute(pool)
    .await?;

    Ok(SessionRecord {
        id: session_id,
        user_id: user.id,
        device_id: device.id,
        email: user.email.clone(),
        display_name: user.display_name.clone(),
    })
}

pub async fn find_session_by_refresh_hash(
    pool: &PgPool,
    refresh_token_hash: &str,
) -> AppResult<Option<SessionLookupRecord>> {
    let row = sqlx::query(
        r#"
        select
          s.id as session_id,
          s.user_id,
          s.device_id,
          u.email,
          u.display_name,
          (s.revoked_at is not null or s.expires_at <= now()) as revoked
        from user_sessions s
        join users u on u.id = s.user_id
        where s.refresh_token_hash = $1
          and u.deleted_at is null
        limit 1
        "#,
    )
    .bind(refresh_token_hash)
    .fetch_optional(pool)
    .await?;

    row.map(|row| {
        Ok(SessionLookupRecord {
            session_id: row.try_get("session_id")?,
            user_id: row.try_get("user_id")?,
            device_id: row.try_get("device_id")?,
            email: row.try_get("email")?,
            display_name: row.try_get("display_name")?,
            revoked: row.try_get("revoked")?,
        })
    })
    .transpose()
}

pub async fn rotate_session_refresh(
    pool: &PgPool,
    session_id: Uuid,
    refresh_token_hash: &str,
    user_agent: Option<&str>,
    ip_address: Option<&str>,
    refresh_ttl_days: i64,
) -> AppResult<()> {
    sqlx::query(
        r#"
        update user_sessions
        set refresh_token_hash = $2,
            user_agent = coalesce($3, user_agent),
            ip_address = coalesce(nullif($4, '')::inet, ip_address),
            last_seen_at = now(),
            expires_at = now() + ($5 * interval '1 day')
        where id = $1
          and revoked_at is null
        "#,
    )
    .bind(session_id)
    .bind(refresh_token_hash)
    .bind(user_agent)
    .bind(ip_address.unwrap_or_default())
    .bind(refresh_ttl_days)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn revoke_session(pool: &PgPool, session_id: Uuid) -> AppResult<()> {
    sqlx::query(
        r#"
        update user_sessions
        set revoked_at = coalesce(revoked_at, now())
        where id = $1
        "#,
    )
    .bind(session_id)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn revoke_all_sessions_for_user(pool: &PgPool, user_id: Uuid) -> AppResult<u64> {
    let result = sqlx::query(
        r#"
        update user_sessions
        set revoked_at = coalesce(revoked_at, now())
        where user_id = $1
          and revoked_at is null
        "#,
    )
    .bind(user_id)
    .execute(pool)
    .await?;
    Ok(result.rows_affected())
}

pub async fn revoke_all_sessions_for_device(
    pool: &PgPool,
    user_id: Uuid,
    device_id: Uuid,
) -> AppResult<u64> {
    let result = sqlx::query(
        r#"
        update user_sessions
        set revoked_at = coalesce(revoked_at, now())
        where user_id = $1
          and device_id = $2
          and revoked_at is null
        "#,
    )
    .bind(user_id)
    .bind(device_id)
    .execute(pool)
    .await?;
    Ok(result.rows_affected())
}

pub async fn revoke_device(pool: &PgPool, user_id: Uuid, device_id: Uuid) -> AppResult<()> {
    let result = sqlx::query(
        r#"
        update devices
        set revoked_at = coalesce(revoked_at, now()),
            updated_at = now()
        where id = $1
          and user_id = $2
          and deleted_at is null
        "#,
    )
    .bind(device_id)
    .bind(user_id)
    .execute(pool)
    .await?;

    if result.rows_affected() == 0 {
        return Err(AppError::not_found("Device not found"));
    }

    let _ = revoke_all_sessions_for_device(pool, user_id, device_id).await?;
    Ok(())
}

pub async fn find_session_principal(
    pool: &PgPool,
    user_id: Uuid,
    session_id: Uuid,
) -> AppResult<Option<SessionRecord>> {
    let row = sqlx::query(
        r#"
        select
          s.id,
          s.user_id,
          s.device_id,
          u.email,
          u.display_name
        from user_sessions s
        join users u on u.id = s.user_id
        join devices d on d.id = s.device_id
        where s.id = $1
          and s.user_id = $2
          and s.revoked_at is null
          and s.expires_at > now()
          and u.deleted_at is null
          and d.deleted_at is null
          and d.revoked_at is null
        limit 1
        "#,
    )
    .bind(session_id)
    .bind(user_id)
    .fetch_optional(pool)
    .await?;

    row.map(|row| {
        Ok(SessionRecord {
            id: row.try_get("id")?,
            user_id: row.try_get("user_id")?,
            device_id: row.try_get("device_id")?,
            email: row.try_get("email")?,
            display_name: row.try_get("display_name")?,
        })
    })
    .transpose()
}

pub async fn list_devices_for_user(pool: &PgPool, user_id: Uuid) -> AppResult<Vec<DeviceRecord>> {
    let rows = sqlx::query(
        r#"
        select id, display_name, platform
        from devices
        where user_id = $1
          and deleted_at is null
        order by revoked_at asc nulls first, last_seen_at desc nulls last, created_at desc
        "#,
    )
    .bind(user_id)
    .fetch_all(pool)
    .await?;

    rows.into_iter()
        .map(|row| {
            Ok(DeviceRecord {
                id: row.try_get("id")?,
                display_name: row.try_get("display_name")?,
                platform: row.try_get("platform")?,
            })
        })
        .collect()
}

fn map_auth_user(row: sqlx::postgres::PgRow) -> AppResult<AuthUserRecord> {
    Ok(AuthUserRecord {
        id: row.try_get("id")?,
        email: row.try_get("email")?,
        display_name: row.try_get("display_name")?,
        password_hash: row.try_get("password_hash")?,
    })
}
