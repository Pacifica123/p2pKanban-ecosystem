use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::{
        activity::repo::{record_activity, NewActivityEntry},
        audit::repo::{record_audit, NewAuditLogEntry},
        common::{
            board_workspace_id, ensure_user_exists, require_workspace_access,
            require_workspace_write,
        },
    },
};

use super::dto::{BoardAppearanceResponse, UserAppearancePreferencesResponse, WallpaperResponse};

fn map_user_preferences(
    row: &sqlx::postgres::PgRow,
) -> AppResult<UserAppearancePreferencesResponse> {
    Ok(UserAppearancePreferencesResponse {
        user_id: row.try_get::<Uuid, _>("user_id")?.to_string(),
        is_customized: row.try_get("is_customized")?,
        app_theme: row.try_get("app_theme")?,
        density: row.try_get("density")?,
        reduce_motion: row.try_get("reduce_motion")?,
        checklist_item_submit_mode: row.try_get("checklist_item_submit_mode")?,
        card_details_mode: row.try_get("card_details_mode")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

fn map_board_appearance(row: &sqlx::postgres::PgRow) -> AppResult<BoardAppearanceResponse> {
    Ok(BoardAppearanceResponse {
        board_id: row.try_get::<Uuid, _>("board_id")?.to_string(),
        is_customized: row.try_get("is_customized")?,
        theme_preset: row.try_get("theme_preset")?,
        wallpaper: WallpaperResponse {
            kind: row.try_get("wallpaper_kind")?,
            value: row.try_get("wallpaper_value")?,
        },
        column_density: row.try_get("column_density")?,
        card_preview_mode: row.try_get("card_preview_mode")?,
        show_card_description: row.try_get("show_card_description")?,
        show_card_dates: row.try_get("show_card_dates")?,
        show_checklist_progress: row.try_get("show_checklist_progress")?,
        custom_properties: row.try_get::<Value, _>("custom_properties_jsonb")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

pub async fn get_my_preferences(
    pool: &PgPool,
    actor_user_id: Uuid,
) -> AppResult<UserAppearancePreferencesResponse> {
    ensure_user_exists(pool, actor_user_id).await?;

    let row = sqlx::query(
        r#"
        select
          u.id as user_id,
          coalesce(p.app_theme, 'system') as app_theme,
          coalesce(p.density, 'comfortable') as density,
          coalesce(p.reduce_motion, false) as reduce_motion,
          coalesce(p.checklist_item_submit_mode, 'ctrl_enter') as checklist_item_submit_mode,
          coalesce(p.card_details_mode, 'drawer') as card_details_mode,
          (p.user_id is not null) as is_customized,
          case when p.created_at is null then null else to_char(p.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as created_at,
          case when p.updated_at is null then null else to_char(p.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as updated_at
        from users u
        left join user_appearance_preferences p on p.user_id = u.id
        where u.id = $1 and u.deleted_at is null
        "#,
    )
    .bind(actor_user_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("User not found"))?;

    map_user_preferences(&row)
}

pub async fn upsert_my_preferences(
    pool: &PgPool,
    actor_user_id: Uuid,
    app_theme: Option<String>,
    density: Option<String>,
    reduce_motion: Option<bool>,
    checklist_item_submit_mode: Option<String>,
    card_details_mode: Option<String>,
) -> AppResult<UserAppearancePreferencesResponse> {
    ensure_user_exists(pool, actor_user_id).await?;

    let row = sqlx::query(
        r#"
        insert into user_appearance_preferences (
          user_id,
          app_theme,
          density,
          reduce_motion,
          checklist_item_submit_mode,
          card_details_mode
        )
        values (
          $1,
          coalesce($2, 'system'),
          coalesce($3, 'comfortable'),
          coalesce($4, false),
          coalesce($5, 'ctrl_enter'),
          coalesce($6, 'drawer')
        )
        on conflict (user_id) do update
        set
          app_theme = coalesce($2, user_appearance_preferences.app_theme),
          density = coalesce($3, user_appearance_preferences.density),
          reduce_motion = coalesce($4, user_appearance_preferences.reduce_motion),
          checklist_item_submit_mode = coalesce($5, user_appearance_preferences.checklist_item_submit_mode),
          card_details_mode = coalesce($6, user_appearance_preferences.card_details_mode),
          updated_at = now()
        returning
          user_id,
          app_theme,
          density,
          reduce_motion,
          checklist_item_submit_mode,
          card_details_mode,
          true as is_customized,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        "#,
    )
    .bind(actor_user_id)
    .bind(app_theme)
    .bind(density)
    .bind(reduce_motion)
    .bind(checklist_item_submit_mode)
    .bind(card_details_mode)
    .fetch_one(pool)
    .await?;

    map_user_preferences(&row)
}

pub async fn get_board_appearance(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<BoardAppearanceResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;

    let row = sqlx::query(
        r#"
        select
          b.id as board_id,
          coalesce(a.theme_preset, 'system') as theme_preset,
          coalesce(a.wallpaper_kind, 'none') as wallpaper_kind,
          a.wallpaper_value,
          coalesce(a.column_density, 'comfortable') as column_density,
          coalesce(a.card_preview_mode, 'expanded') as card_preview_mode,
          coalesce(a.show_card_description, true) as show_card_description,
          coalesce(a.show_card_dates, true) as show_card_dates,
          coalesce(a.show_checklist_progress, true) as show_checklist_progress,
          coalesce(a.custom_properties_jsonb, '{}'::jsonb) as custom_properties_jsonb,
          (a.board_id is not null) as is_customized,
          case when a.created_at is null then null else to_char(a.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as created_at,
          case when a.updated_at is null then null else to_char(a.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as updated_at
        from boards b
        left join board_appearance_settings a on a.board_id = b.id
        where b.id = $1 and b.deleted_at is null
        "#,
    )
    .bind(board_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Board not found"))?;

    map_board_appearance(&row)
}

#[allow(clippy::too_many_arguments)]
pub async fn upsert_board_appearance(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
    theme_preset: Option<String>,
    wallpaper_changed: bool,
    wallpaper_kind: Option<String>,
    wallpaper_value: Option<String>,
    column_density: Option<String>,
    card_preview_mode: Option<String>,
    show_card_description: Option<bool>,
    show_card_dates: Option<bool>,
    show_checklist_progress: Option<bool>,
    custom_properties: Option<Value>,
) -> AppResult<BoardAppearanceResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let before = get_board_appearance(pool, actor_user_id, board_id).await?;

    let row = sqlx::query(
        r#"
        insert into board_appearance_settings (
          board_id,
          theme_preset,
          wallpaper_kind,
          wallpaper_value,
          column_density,
          card_preview_mode,
          show_card_description,
          show_card_dates,
          show_checklist_progress,
          custom_properties_jsonb
        )
        values (
          $1,
          coalesce($2, 'system'),
          case when $3 then coalesce($4, 'none') else 'none' end,
          case when $3 then $5 else null end,
          coalesce($6, 'comfortable'),
          coalesce($7, 'expanded'),
          coalesce($8, true),
          coalesce($9, true),
          coalesce($10, true),
          coalesce($11, '{}'::jsonb)
        )
        on conflict (board_id) do update
        set
          theme_preset = coalesce($2, board_appearance_settings.theme_preset),
          wallpaper_kind = case when $3 then coalesce($4, 'none') else board_appearance_settings.wallpaper_kind end,
          wallpaper_value = case when $3 then $5 else board_appearance_settings.wallpaper_value end,
          column_density = coalesce($6, board_appearance_settings.column_density),
          card_preview_mode = coalesce($7, board_appearance_settings.card_preview_mode),
          show_card_description = coalesce($8, board_appearance_settings.show_card_description),
          show_card_dates = coalesce($9, board_appearance_settings.show_card_dates),
          show_checklist_progress = coalesce($10, board_appearance_settings.show_checklist_progress),
          custom_properties_jsonb = coalesce($11, board_appearance_settings.custom_properties_jsonb),
          updated_at = now()
        returning
          board_id,
          theme_preset,
          wallpaper_kind,
          wallpaper_value,
          column_density,
          card_preview_mode,
          show_card_description,
          show_card_dates,
          show_checklist_progress,
          custom_properties_jsonb,
          true as is_customized,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        "#,
    )
    .bind(board_id)
    .bind(theme_preset)
    .bind(wallpaper_changed)
    .bind(wallpaper_kind)
    .bind(wallpaper_value)
    .bind(column_density)
    .bind(card_preview_mode)
    .bind(show_card_description)
    .bind(show_card_dates)
    .bind(show_checklist_progress)
    .bind(custom_properties)
    .fetch_one(pool)
    .await?;

    let appearance = map_board_appearance(&row)?;
    let mut field_mask = Vec::new();
    let mut changes = serde_json::Map::new();
    if before.theme_preset != appearance.theme_preset {
        field_mask.push("themePreset".to_string());
        changes.insert(
            "themePreset".to_string(),
            json!({"before": before.theme_preset, "after": appearance.theme_preset.clone()}),
        );
    }
    if before.wallpaper.kind != appearance.wallpaper.kind
        || before.wallpaper.value != appearance.wallpaper.value
    {
        field_mask.push("wallpaper".to_string());
        changes.insert(
            "wallpaper".to_string(),
            json!({
                "before": {"kind": before.wallpaper.kind, "value": before.wallpaper.value},
                "after": {"kind": appearance.wallpaper.kind.clone(), "value": appearance.wallpaper.value.clone()},
            }),
        );
    }
    if before.column_density != appearance.column_density {
        field_mask.push("columnDensity".to_string());
        changes.insert(
            "columnDensity".to_string(),
            json!({"before": before.column_density, "after": appearance.column_density.clone()}),
        );
    }
    if before.card_preview_mode != appearance.card_preview_mode {
        field_mask.push("cardPreviewMode".to_string());
        changes.insert("cardPreviewMode".to_string(), json!({"before": before.card_preview_mode, "after": appearance.card_preview_mode.clone()}));
    }
    if before.show_card_description != appearance.show_card_description {
        field_mask.push("showCardDescription".to_string());
        changes.insert("showCardDescription".to_string(), json!({"before": before.show_card_description, "after": appearance.show_card_description}));
    }
    if before.show_card_dates != appearance.show_card_dates {
        field_mask.push("showCardDates".to_string());
        changes.insert(
            "showCardDates".to_string(),
            json!({"before": before.show_card_dates, "after": appearance.show_card_dates}),
        );
    }
    if before.show_checklist_progress != appearance.show_checklist_progress {
        field_mask.push("showChecklistProgress".to_string());
        changes.insert("showChecklistProgress".to_string(), json!({"before": before.show_checklist_progress, "after": appearance.show_checklist_progress}));
    }
    if before.custom_properties != appearance.custom_properties {
        field_mask.push("customProperties".to_string());
        changes.insert("customProperties".to_string(), json!({"before": before.custom_properties, "after": appearance.custom_properties.clone()}));
    }
    if !field_mask.is_empty() {
        let audit_id = record_audit(
            pool,
            &NewAuditLogEntry {
                workspace_id: Some(workspace_id),
                actor_user_id: Some(actor_user_id),
                actor_device_id: None,
                actor_replica_id: None,
                action_type: "board.appearance.updated".to_string(),
                target_entity_type: Some("board".to_string()),
                target_entity_id: Some(board_id),
                request_id: None,
                metadata_jsonb: Value::Object(changes.clone()),
            },
        )
        .await?;
        let _activity_id = record_activity(
            pool,
            &NewActivityEntry {
                workspace_id,
                board_id,
                card_id: None,
                actor_user_id: Some(actor_user_id),
                kind: "board.appearance.updated",
                entity_type: "board",
                entity_id: board_id,
                field_mask,
                payload_jsonb: json!({"changes": changes}),
                request_id: None,
                source_change_event_id: None,
                source_audit_log_id: Some(audit_id),
            },
        )
        .await?;
    }

    Ok(appearance)
}
