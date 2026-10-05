use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::{
        activity::repo::{record_activity, NewActivityEntry},
        audit::repo::{record_audit, NewAuditLogEntry},
        common::{
            card_board_and_workspace_id, require_workspace_access, require_workspace_write,
            POSITION_GAP,
        },
    },
};

use super::dto::{
    ChecklistItemResponse, ChecklistListResponse, ChecklistResponse, CreateChecklistItemRequest,
    CreateChecklistRequest, UpdateChecklistItemRequest, UpdateChecklistRequest,
};

fn map_checklist(
    row: &sqlx::postgres::PgRow,
    items: Vec<ChecklistItemResponse>,
) -> AppResult<ChecklistResponse> {
    Ok(ChecklistResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        card_id: row.try_get::<Uuid, _>("card_id")?.to_string(),
        title: row.try_get("title")?,
        position: row.try_get("position")?,
        items,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

fn map_item(row: &sqlx::postgres::PgRow) -> AppResult<ChecklistItemResponse> {
    Ok(ChecklistItemResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        checklist_id: row.try_get::<Uuid, _>("checklist_id")?.to_string(),
        title: row.try_get("title")?,
        is_done: row.try_get("is_done")?,
        position: row.try_get("position")?,
        completed_at: row.try_get("completed_at")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

async fn fetch_items_for_checklist(
    pool: &PgPool,
    checklist_id: Uuid,
) -> AppResult<Vec<ChecklistItemResponse>> {
    let rows = sqlx::query(
        r#"
        select
          id,
          checklist_id,
          title,
          is_done,
          position::double precision as position,
          case when completed_at is null then null else to_char(completed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as completed_at,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        from checklist_items
        where checklist_id = $1 and deleted_at is null
        order by position asc, id asc
        "#,
    )
    .bind(checklist_id)
    .fetch_all(pool)
    .await?;

    rows.iter().map(map_item).collect()
}

async fn fetch_checklist(pool: &PgPool, checklist_id: Uuid) -> AppResult<ChecklistResponse> {
    let row = sqlx::query(
        r#"
        select
          id,
          card_id,
          title,
          position::double precision as position,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        from checklists
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(checklist_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Checklist not found"))?;
    let items = fetch_items_for_checklist(pool, checklist_id).await?;
    map_checklist(&row, items)
}

async fn fetch_item(pool: &PgPool, item_id: Uuid) -> AppResult<ChecklistItemResponse> {
    let row = sqlx::query(
        r#"
        select
          id,
          checklist_id,
          title,
          is_done,
          position::double precision as position,
          case when completed_at is null then null else to_char(completed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as completed_at,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        from checklist_items
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(item_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Checklist item not found"))?;
    map_item(&row)
}

async fn checklist_context(pool: &PgPool, checklist_id: Uuid) -> AppResult<(Uuid, Uuid, Uuid)> {
    let row = sqlx::query(
        r#"
        select ch.card_id, c.board_id, b.workspace_id
        from checklists ch
        join cards c on c.id = ch.card_id
        join boards b on b.id = c.board_id
        where ch.id = $1
          and ch.deleted_at is null
          and c.deleted_at is null
          and b.deleted_at is null
        "#,
    )
    .bind(checklist_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Checklist not found"))?;

    Ok((
        row.try_get("card_id")?,
        row.try_get("board_id")?,
        row.try_get("workspace_id")?,
    ))
}

async fn item_context(pool: &PgPool, item_id: Uuid) -> AppResult<(Uuid, Uuid, Uuid, Uuid)> {
    let row = sqlx::query(
        r#"
        select chi.checklist_id, ch.card_id, c.board_id, b.workspace_id
        from checklist_items chi
        join checklists ch on ch.id = chi.checklist_id
        join cards c on c.id = ch.card_id
        join boards b on b.id = c.board_id
        where chi.id = $1
          and chi.deleted_at is null
          and ch.deleted_at is null
          and c.deleted_at is null
          and b.deleted_at is null
        "#,
    )
    .bind(item_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Checklist item not found"))?;

    Ok((
        row.try_get("checklist_id")?,
        row.try_get("card_id")?,
        row.try_get("board_id")?,
        row.try_get("workspace_id")?,
    ))
}

async fn next_checklist_position(pool: &PgPool, card_id: Uuid) -> AppResult<f64> {
    let max_position = sqlx::query_scalar::<_, Option<f64>>(
        "select max(position::double precision) from checklists where card_id = $1 and deleted_at is null",
    )
    .bind(card_id)
    .fetch_one(pool)
    .await?;
    Ok(max_position.unwrap_or(0.0) + POSITION_GAP)
}

async fn next_item_position(pool: &PgPool, checklist_id: Uuid) -> AppResult<f64> {
    let max_position = sqlx::query_scalar::<_, Option<f64>>(
        "select max(position::double precision) from checklist_items where checklist_id = $1 and deleted_at is null",
    )
    .bind(checklist_id)
    .fetch_one(pool)
    .await?;
    Ok(max_position.unwrap_or(0.0) + POSITION_GAP)
}

pub async fn list_checklists(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<ChecklistListResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;

    let rows = sqlx::query(
        r#"
        select
          id,
          card_id,
          title,
          position::double precision as position,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        from checklists
        where card_id = $1 and deleted_at is null
        order by position asc, id asc
        "#,
    )
    .bind(card_id)
    .fetch_all(pool)
    .await?;

    let mut items = Vec::with_capacity(rows.len());
    for row in rows {
        let checklist_id: Uuid = row.try_get("id")?;
        let checklist_items = fetch_items_for_checklist(pool, checklist_id).await?;
        items.push(map_checklist(&row, checklist_items)?);
    }

    Ok(ChecklistListResponse { items })
}

pub async fn create_checklist(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: CreateChecklistRequest,
) -> AppResult<ChecklistResponse> {
    let (board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let checklist_id = Uuid::now_v7();
    let position = match payload.position {
        Some(position) => position,
        None => next_checklist_position(pool, card_id).await?,
    };

    sqlx::query(
        r#"
        insert into checklists (id, card_id, title, position)
        values ($1, $2, $3, $4)
        "#,
    )
    .bind(checklist_id)
    .bind(card_id)
    .bind(payload.title.trim())
    .bind(position)
    .execute(pool)
    .await?;

    let checklist = fetch_checklist(pool, checklist_id).await?;
    record_checklist_activity(
        pool,
        workspace_id,
        board_id,
        card_id,
        actor_user_id,
        "checklist.created",
        checklist_id,
        vec!["title".to_string()],
        json!({"checklistId": checklist_id, "checklistTitle": checklist.title.clone()}),
    )
    .await?;
    Ok(checklist)
}

pub async fn update_checklist(
    pool: &PgPool,
    actor_user_id: Uuid,
    checklist_id: Uuid,
    payload: UpdateChecklistRequest,
) -> AppResult<ChecklistResponse> {
    let (card_id, board_id, workspace_id) = checklist_context(pool, checklist_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let before = fetch_checklist(pool, checklist_id).await?;

    sqlx::query(
        r#"
        update checklists
        set title = coalesce($2, title), position = coalesce($3, position)
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(checklist_id)
    .bind(payload.title.map(|value| value.trim().to_string()))
    .bind(payload.position)
    .execute(pool)
    .await?;

    let checklist = fetch_checklist(pool, checklist_id).await?;
    let mut field_mask = Vec::new();
    let mut changes = serde_json::Map::new();
    if before.title != checklist.title {
        field_mask.push("title".to_string());
        changes.insert(
            "title".to_string(),
            json!({"before": before.title, "after": checklist.title.clone()}),
        );
    }
    if (before.position - checklist.position).abs() > f64::EPSILON {
        field_mask.push("position".to_string());
        changes.insert(
            "position".to_string(),
            json!({"before": before.position, "after": checklist.position}),
        );
    }
    if !field_mask.is_empty() {
        record_checklist_activity(
            pool,
            workspace_id,
            board_id,
            card_id,
            actor_user_id,
            "checklist.updated",
            checklist_id,
            field_mask,
            Value::Object(changes),
        )
        .await?;
    }
    Ok(checklist)
}

pub async fn delete_checklist(
    pool: &PgPool,
    actor_user_id: Uuid,
    checklist_id: Uuid,
) -> AppResult<ChecklistResponse> {
    let (card_id, board_id, workspace_id) = checklist_context(pool, checklist_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let checklist = fetch_checklist(pool, checklist_id).await?;

    sqlx::query("update checklist_items set deleted_at = now() where checklist_id = $1 and deleted_at is null")
        .bind(checklist_id)
        .execute(pool)
        .await?;
    sqlx::query("update checklists set deleted_at = now() where id = $1 and deleted_at is null")
        .bind(checklist_id)
        .execute(pool)
        .await?;
    record_checklist_activity(
        pool,
        workspace_id,
        board_id,
        card_id,
        actor_user_id,
        "checklist.deleted",
        checklist_id,
        vec![],
        json!({"checklistId": checklist_id, "checklistTitle": checklist.title.clone()}),
    )
    .await?;
    Ok(checklist)
}

pub async fn create_item(
    pool: &PgPool,
    actor_user_id: Uuid,
    checklist_id: Uuid,
    payload: CreateChecklistItemRequest,
) -> AppResult<ChecklistItemResponse> {
    let (card_id, board_id, workspace_id) = checklist_context(pool, checklist_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let item_id = Uuid::now_v7();
    let position = match payload.position {
        Some(position) => position,
        None => next_item_position(pool, checklist_id).await?,
    };

    sqlx::query(
        r#"
        insert into checklist_items (id, checklist_id, title, position)
        values ($1, $2, $3, $4)
        "#,
    )
    .bind(item_id)
    .bind(checklist_id)
    .bind(payload.title.trim())
    .bind(position)
    .execute(pool)
    .await?;

    let item = fetch_item(pool, item_id).await?;
    record_checklist_item_activity(
        pool,
        workspace_id,
        board_id,
        card_id,
        actor_user_id,
        "checklist_item.created",
        item_id,
        vec!["title".to_string()],
        json!({"checklistId": checklist_id, "itemId": item_id, "itemTitle": item.title.clone()}),
    )
    .await?;
    Ok(item)
}

pub async fn update_item(
    pool: &PgPool,
    actor_user_id: Uuid,
    item_id: Uuid,
    payload: UpdateChecklistItemRequest,
) -> AppResult<ChecklistItemResponse> {
    let (_checklist_id, card_id, board_id, workspace_id) = item_context(pool, item_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let before = fetch_item(pool, item_id).await?;

    sqlx::query(
        r#"
        update checklist_items
        set
          title = coalesce($2, title),
          position = coalesce($3, position),
          is_done = coalesce($4, is_done),
          completed_at = case
            when $4::bool is null then completed_at
            when $4 = true and completed_at is null then now()
            when $4 = false then null
            else completed_at
          end
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(item_id)
    .bind(payload.title.map(|value| value.trim().to_string()))
    .bind(payload.position)
    .bind(payload.is_done)
    .execute(pool)
    .await?;

    let item = fetch_item(pool, item_id).await?;
    let mut field_mask = Vec::new();
    let mut changes = serde_json::Map::new();
    if before.title != item.title {
        field_mask.push("title".to_string());
        changes.insert(
            "title".to_string(),
            json!({"before": before.title, "after": item.title.clone()}),
        );
    }
    if (before.position - item.position).abs() > f64::EPSILON {
        field_mask.push("position".to_string());
        changes.insert(
            "position".to_string(),
            json!({"before": before.position, "after": item.position}),
        );
    }
    if before.is_done != item.is_done {
        field_mask.push("isDone".to_string());
        changes.insert(
            "isDone".to_string(),
            json!({"before": before.is_done, "after": item.is_done}),
        );
    }
    if !field_mask.is_empty() {
        let kind = if before.is_done != item.is_done {
            if item.is_done {
                "checklist_item.completed"
            } else {
                "checklist_item.reopened"
            }
        } else {
            "checklist_item.updated"
        };
        record_checklist_item_activity(
            pool,
            workspace_id,
            board_id,
            card_id,
            actor_user_id,
            kind,
            item_id,
            field_mask,
            Value::Object(changes),
        )
        .await?;
    }
    Ok(item)
}

pub async fn delete_item(
    pool: &PgPool,
    actor_user_id: Uuid,
    item_id: Uuid,
) -> AppResult<ChecklistItemResponse> {
    let (checklist_id, card_id, board_id, workspace_id) = item_context(pool, item_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let item = fetch_item(pool, item_id).await?;

    sqlx::query(
        "update checklist_items set deleted_at = now() where id = $1 and deleted_at is null",
    )
    .bind(item_id)
    .execute(pool)
    .await?;

    record_checklist_item_activity(
        pool,
        workspace_id,
        board_id,
        card_id,
        actor_user_id,
        "checklist_item.deleted",
        item_id,
        vec![],
        json!({"checklistId": checklist_id, "itemId": item_id, "itemTitle": item.title.clone()}),
    )
    .await?;
    Ok(item)
}

async fn record_checklist_activity(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Uuid,
    card_id: Uuid,
    actor_user_id: Uuid,
    kind: &'static str,
    checklist_id: Uuid,
    field_mask: Vec<String>,
    payload_jsonb: Value,
) -> AppResult<()> {
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: kind.to_string(),
            target_entity_type: Some("checklist".to_string()),
            target_entity_id: Some(checklist_id),
            request_id: None,
            metadata_jsonb: payload_jsonb.clone(),
        },
    )
    .await?;

    record_activity(
        pool,
        &NewActivityEntry {
            workspace_id,
            board_id,
            card_id: Some(card_id),
            actor_user_id: Some(actor_user_id),
            kind,
            entity_type: "checklist",
            entity_id: checklist_id,
            field_mask,
            payload_jsonb,
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    Ok(())
}

async fn record_checklist_item_activity(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Uuid,
    card_id: Uuid,
    actor_user_id: Uuid,
    kind: &'static str,
    item_id: Uuid,
    field_mask: Vec<String>,
    payload_jsonb: Value,
) -> AppResult<()> {
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: kind.to_string(),
            target_entity_type: Some("checklist_item".to_string()),
            target_entity_id: Some(item_id),
            request_id: None,
            metadata_jsonb: payload_jsonb.clone(),
        },
    )
    .await?;

    record_activity(
        pool,
        &NewActivityEntry {
            workspace_id,
            board_id,
            card_id: Some(card_id),
            actor_user_id: Some(actor_user_id),
            kind,
            entity_type: "checklist_item",
            entity_id: item_id,
            field_mask,
            payload_jsonb,
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    Ok(())
}
