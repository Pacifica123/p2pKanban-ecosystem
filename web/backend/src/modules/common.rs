use axum::http::HeaderMap;
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    auth::{repo, token::verify_access_token},
    error::{AppError, AppResult},
    http::middleware::bearer_token,
    state::AppState,
};

pub const POSITION_GAP: f64 = 1024.0;

#[derive(Debug, Clone)]
pub struct AuthContext {
    pub user_id: Uuid,
    pub session_id: Uuid,
    pub device_id: Uuid,
    pub mode: &'static str,
}

pub async fn auth_context(state: &AppState, headers: &HeaderMap) -> AppResult<AuthContext> {
    if let Some(token) = bearer_token(headers) {
        let claims = verify_access_token(
            &token,
            &state.settings.auth.jwt_secret,
            &state.settings.auth.previous_jwt_secrets,
        )?;
        let user_id = claims.user_id()?;
        let session_id = claims.session_id()?;
        let device_id = claims
            .device_id()?
            .ok_or_else(|| AppError::unauthorized("Access token is missing device binding"))?;

        let Some(session) = repo::find_session_principal(&state.db, user_id, session_id).await?
        else {
            return Err(AppError::unauthorized("Session is no longer active"));
        };

        if session.device_id != device_id {
            return Err(AppError::unauthorized(
                "Access token device binding mismatch",
            ));
        }

        return Ok(AuthContext {
            user_id,
            session_id,
            device_id,
            mode: "bearer",
        });
    }

    if state.settings.dev_header_auth_allowed() {
        let user_id = headers
            .get("x-user-id")
            .and_then(|value| value.to_str().ok())
            .and_then(|value| Uuid::parse_str(value).ok())
            .ok_or_else(|| AppError::unauthorized("Missing bearer token"))?;

        ensure_user_exists(&state.db, user_id).await?;
        return Ok(AuthContext {
            user_id,
            session_id: Uuid::nil(),
            device_id: Uuid::nil(),
            mode: "dev_header",
        });
    }

    Err(AppError::unauthorized(
        "Authentication is required. Sign in to obtain a session.",
    ))
}

pub async fn actor_user_id(state: &AppState, headers: &HeaderMap) -> AppResult<Uuid> {
    Ok(auth_context(state, headers).await?.user_id)
}

pub fn normalize_limit(limit: Option<i64>) -> i64 {
    limit.unwrap_or(50).clamp(1, 100)
}

pub fn trim_to_option(value: Option<String>) -> Option<String> {
    value.and_then(|v| {
        let trimmed = v.trim();
        (!trimmed.is_empty()).then(|| trimmed.to_string())
    })
}

pub async fn ensure_user_exists(pool: &PgPool, user_id: Uuid) -> AppResult<()> {
    let exists = sqlx::query_scalar::<_, bool>(
        r#"
        select exists(
            select 1
            from users
            where id = $1 and deleted_at is null
        )
        "#,
    )
    .bind(user_id)
    .fetch_one(pool)
    .await?;

    if exists {
        Ok(())
    } else {
        Err(AppError::unauthorized(
            "Authenticated user is not active anymore",
        ))
    }
}

pub async fn workspace_role(
    pool: &PgPool,
    workspace_id: Uuid,
    user_id: Uuid,
) -> AppResult<Option<String>> {
    let row = sqlx::query(
        r#"
        select
          case
            when w.owner_user_id = $2 then 'owner'
            else (
              select wm.role
              from workspace_members wm
              where wm.workspace_id = w.id
                and wm.user_id = $2
                and wm.deactivated_at is null
                and wm.deleted_at is null
              limit 1
            )
          end as role,
          w.visibility as visibility
        from workspaces w
        where w.id = $1
          and w.deleted_at is null
        "#,
    )
    .bind(workspace_id)
    .bind(user_id)
    .fetch_optional(pool)
    .await?;

    let Some(row) = row else {
        return Err(AppError::not_found("Workspace not found"));
    };

    let role: Option<String> = row.try_get("role")?;
    let visibility: String = row.try_get("visibility")?;

    if role.is_some() || visibility == "public_readonly" {
        Ok(role)
    } else {
        Ok(None)
    }
}

pub async fn require_workspace_access(
    pool: &PgPool,
    workspace_id: Uuid,
    user_id: Uuid,
) -> AppResult<Option<String>> {
    let role = workspace_role(pool, workspace_id, user_id).await?;
    if role.is_none() {
        return Err(AppError::forbidden(
            "Workspace is not accessible for current user",
        ));
    }
    Ok(role)
}

pub async fn require_workspace_write(
    pool: &PgPool,
    workspace_id: Uuid,
    user_id: Uuid,
) -> AppResult<String> {
    let role = require_workspace_access(pool, workspace_id, user_id)
        .await?
        .ok_or_else(|| AppError::forbidden("Workspace write access is required"))?;

    match role.as_str() {
        "owner" | "member" => Ok(role),
        _ => Err(AppError::forbidden("Workspace write access is required")),
    }
}

pub async fn require_workspace_owner(
    pool: &PgPool,
    workspace_id: Uuid,
    user_id: Uuid,
) -> AppResult<()> {
    let role = require_workspace_access(pool, workspace_id, user_id)
        .await?
        .ok_or_else(|| AppError::forbidden("Workspace owner access is required"))?;

    if role == "owner" {
        Ok(())
    } else {
        Err(AppError::forbidden("Workspace owner access is required"))
    }
}

pub async fn workspace_access_epoch(pool: &PgPool, workspace_id: Uuid) -> AppResult<i64> {
    sqlx::query_scalar::<_, i64>(
        "select access_epoch from workspaces where id = $1 and deleted_at is null",
    )
    .bind(workspace_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Workspace not found"))
}

pub async fn board_workspace_id(pool: &PgPool, board_id: Uuid) -> AppResult<Uuid> {
    sqlx::query_scalar::<_, Uuid>(
        r#"
        select workspace_id
        from boards
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(board_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Board not found"))
}

pub async fn column_board_and_workspace_id(
    pool: &PgPool,
    column_id: Uuid,
) -> AppResult<(Uuid, Uuid)> {
    let row = sqlx::query(
        r#"
        select c.board_id, b.workspace_id
        from board_columns c
        join boards b on b.id = c.board_id
        where c.id = $1
          and c.deleted_at is null
          and b.deleted_at is null
        "#,
    )
    .bind(column_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Column not found"))?;

    Ok((row.try_get("board_id")?, row.try_get("workspace_id")?))
}

pub async fn card_board_and_workspace_id(pool: &PgPool, card_id: Uuid) -> AppResult<(Uuid, Uuid)> {
    let row = sqlx::query(
        r#"
        select c.board_id, b.workspace_id
        from cards c
        join boards b on b.id = c.board_id
        where c.id = $1
          and c.deleted_at is null
          and b.deleted_at is null
        "#,
    )
    .bind(card_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Card not found"))?;

    Ok((row.try_get("board_id")?, row.try_get("workspace_id")?))
}

pub async fn next_position_for_column(pool: &PgPool, board_id: Uuid) -> AppResult<f64> {
    let max_position = sqlx::query_scalar::<_, Option<f64>>(
        r#"
        select max(position::double precision)
        from board_columns
        where board_id = $1 and deleted_at is null
        "#,
    )
    .bind(board_id)
    .fetch_one(pool)
    .await?;

    Ok(max_position.unwrap_or(0.0) + POSITION_GAP)
}

pub async fn next_position_for_card(
    pool: &PgPool,
    board_id: Uuid,
    column_id: Uuid,
) -> AppResult<f64> {
    let max_position = sqlx::query_scalar::<_, Option<f64>>(
        r#"
        select max(position::double precision)
        from cards
        where board_id = $1 and column_id = $2 and deleted_at is null
        "#,
    )
    .bind(board_id)
    .bind(column_id)
    .fetch_one(pool)
    .await?;

    Ok(max_position.unwrap_or(0.0) + POSITION_GAP)
}
