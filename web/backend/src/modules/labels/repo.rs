use std::collections::HashSet;

use serde_json::json;
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::{
        activity::repo::{record_activity, NewActivityEntry},
        audit::repo::{record_audit, NewAuditLogEntry},
        cards::{dto::CardResponse, repo::fetch_card},
        common::{
            board_workspace_id, card_board_and_workspace_id, require_workspace_access,
            require_workspace_write, trim_to_option,
        },
    },
};

use super::dto::{
    CreateLabelRequest, LabelListResponse, LabelResponse, ReplaceCardLabelsRequest,
    UpdateLabelRequest,
};

fn map_label(row: &sqlx::postgres::PgRow) -> AppResult<LabelResponse> {
    Ok(LabelResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        board_id: row.try_get::<Uuid, _>("board_id")?.to_string(),
        name: row.try_get("name")?,
        color: row.try_get("color")?,
        description: row.try_get("description")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

async fn fetch_label(pool: &PgPool, label_id: Uuid) -> AppResult<LabelResponse> {
    let row = sqlx::query(
        r#"
        select
          id,
          board_id,
          name,
          color,
          description,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        from board_labels
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(label_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Label not found"))?;

    map_label(&row)
}

async fn label_board_and_workspace_id(pool: &PgPool, label_id: Uuid) -> AppResult<(Uuid, Uuid)> {
    let row = sqlx::query(
        r#"
        select bl.board_id, b.workspace_id
        from board_labels bl
        join boards b on b.id = bl.board_id
        where bl.id = $1
          and bl.deleted_at is null
          and b.deleted_at is null
        "#,
    )
    .bind(label_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Label not found"))?;

    Ok((row.try_get("board_id")?, row.try_get("workspace_id")?))
}

pub async fn list_labels(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<LabelListResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;

    let rows = sqlx::query(
        r#"
        select
          id,
          board_id,
          name,
          color,
          description,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        from board_labels
        where board_id = $1 and deleted_at is null
        order by name asc, id asc
        "#,
    )
    .bind(board_id)
    .fetch_all(pool)
    .await?;

    Ok(LabelListResponse {
        items: rows.iter().map(map_label).collect::<AppResult<Vec<_>>>()?,
    })
}

pub async fn create_label(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: CreateLabelRequest,
) -> AppResult<LabelResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let label_id = Uuid::now_v7();
    let label_name = payload.name.trim().to_string();
    let label_color = payload.color.trim().to_string();

    sqlx::query(
        r#"
        insert into board_labels (id, board_id, name, color, description)
        values ($1, $2, $3, $4, $5)
        "#,
    )
    .bind(label_id)
    .bind(board_id)
    .bind(&label_name)
    .bind(&label_color)
    .bind(trim_to_option(payload.description))
    .execute(pool)
    .await?;

    let label = fetch_label(pool, label_id).await?;
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "label.created".to_string(),
            target_entity_type: Some("label".to_string()),
            target_entity_id: Some(label_id),
            request_id: None,
            metadata_jsonb: json!({"boardId": board_id, "labelName": label.name.clone(), "color": label.color.clone()}),
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
            kind: "label.created",
            entity_type: "board",
            entity_id: board_id,
            field_mask: vec!["labels".to_string()],
            payload_jsonb: json!({"labelId": label_id, "labelName": label.name.clone(), "color": label.color.clone()}),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;

    Ok(label)
}

pub async fn update_label(
    pool: &PgPool,
    actor_user_id: Uuid,
    label_id: Uuid,
    payload: UpdateLabelRequest,
) -> AppResult<LabelResponse> {
    let (board_id, workspace_id) = label_board_and_workspace_id(pool, label_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let before = fetch_label(pool, label_id).await?;
    let description_changed = payload.description.is_some();
    let description = payload.description.map(trim_to_option);

    sqlx::query(
        r#"
        update board_labels
        set
          name = coalesce($2, name),
          color = coalesce($3, color),
          description = case when $4 then $5 else description end
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(label_id)
    .bind(payload.name.map(|value| value.trim().to_string()))
    .bind(payload.color.map(|value| value.trim().to_string()))
    .bind(description_changed)
    .bind(description.flatten())
    .execute(pool)
    .await?;

    let label = fetch_label(pool, label_id).await?;
    let mut field_mask = Vec::new();
    if before.name != label.name {
        field_mask.push("name".to_string());
    }
    if before.color != label.color {
        field_mask.push("color".to_string());
    }
    if before.description != label.description {
        field_mask.push("description".to_string());
    }
    if !field_mask.is_empty() {
        let audit_id = record_audit(
            pool,
            &NewAuditLogEntry {
                workspace_id: Some(workspace_id),
                actor_user_id: Some(actor_user_id),
                actor_device_id: None,
                actor_replica_id: None,
                action_type: "label.updated".to_string(),
                target_entity_type: Some("label".to_string()),
                target_entity_id: Some(label_id),
                request_id: None,
                metadata_jsonb: json!({
                    "boardId": board_id,
                    "labelId": label_id,
                    "before": {"name": before.name.clone(), "color": before.color.clone(), "description": before.description.clone()},
                    "after": {"name": label.name.clone(), "color": label.color.clone(), "description": label.description.clone()},
                }),
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
                kind: "label.updated",
                entity_type: "board",
                entity_id: board_id,
                field_mask,
                payload_jsonb: json!({"labelId": label_id, "labelName": label.name.clone(), "color": label.color.clone()}),
                request_id: None,
                source_change_event_id: None,
                source_audit_log_id: Some(audit_id),
            },
        )
        .await?;
    }

    Ok(label)
}

pub async fn delete_label(
    pool: &PgPool,
    actor_user_id: Uuid,
    label_id: Uuid,
) -> AppResult<LabelResponse> {
    let (board_id, workspace_id) = label_board_and_workspace_id(pool, label_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let label = fetch_label(pool, label_id).await?;

    let mut tx = pool.begin().await?;
    sqlx::query(
        "update card_labels set deleted_at = now() where label_id = $1 and deleted_at is null",
    )
    .bind(label_id)
    .execute(&mut *tx)
    .await?;
    sqlx::query("update board_labels set deleted_at = now() where id = $1 and deleted_at is null")
        .bind(label_id)
        .execute(&mut *tx)
        .await?;
    let audit_id = record_audit(
        &mut *tx,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "label.deleted".to_string(),
            target_entity_type: Some("label".to_string()),
            target_entity_id: Some(label_id),
            request_id: None,
            metadata_jsonb: json!({"boardId": board_id, "labelName": label.name.clone()}),
        },
    )
    .await?;
    let _activity_id = record_activity(
        &mut *tx,
        &NewActivityEntry {
            workspace_id,
            board_id,
            card_id: None,
            actor_user_id: Some(actor_user_id),
            kind: "label.deleted",
            entity_type: "board",
            entity_id: board_id,
            field_mask: vec!["labels".to_string()],
            payload_jsonb: json!({"labelId": label_id, "labelName": label.name.clone()}),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    tx.commit().await?;

    Ok(label)
}

pub async fn replace_card_labels(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: ReplaceCardLabelsRequest,
) -> AppResult<CardResponse> {
    let (board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let before_label_ids = sqlx::query_scalar::<_, Vec<Uuid>>(
        r#"
        select coalesce(array_agg(label_id order by label_id), '{}'::uuid[])
        from card_labels
        where card_id = $1 and deleted_at is null
        "#,
    )
    .bind(card_id)
    .fetch_one(pool)
    .await?;

    if !payload.label_ids.is_empty() {
        let valid_count = sqlx::query_scalar::<_, i64>(
            r#"
            select count(*)::bigint
            from board_labels
            where board_id = $1 and id = any($2) and deleted_at is null
            "#,
        )
        .bind(board_id)
        .bind(&payload.label_ids)
        .fetch_one(pool)
        .await?;
        if valid_count != payload.label_ids.len() as i64 {
            return Err(AppError::bad_request(
                "All labelIds must belong to the card board",
            ));
        }
    }

    let before_set = before_label_ids.iter().copied().collect::<HashSet<_>>();
    let after_set = payload.label_ids.iter().copied().collect::<HashSet<_>>();
    let added_label_ids = after_set
        .difference(&before_set)
        .copied()
        .collect::<Vec<_>>();
    let removed_label_ids = before_set
        .difference(&after_set)
        .copied()
        .collect::<Vec<_>>();

    let mut tx = pool.begin().await?;
    sqlx::query(
        r#"
        update card_labels
        set deleted_at = now()
        where card_id = $1
          and deleted_at is null
          and not (label_id = any($2))
        "#,
    )
    .bind(card_id)
    .bind(&payload.label_ids)
    .execute(&mut *tx)
    .await?;

    for label_id in &payload.label_ids {
        sqlx::query(
            r#"
            update card_labels
            set deleted_at = null
            where card_id = $1 and label_id = $2 and deleted_at is not null
            "#,
        )
        .bind(card_id)
        .bind(label_id)
        .execute(&mut *tx)
        .await?;

        sqlx::query(
            r#"
            insert into card_labels (id, board_id, card_id, label_id)
            select $1, $2, $3, $4
            where not exists (
              select 1 from card_labels
              where card_id = $3 and label_id = $4 and deleted_at is null
            )
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(board_id)
        .bind(card_id)
        .bind(label_id)
        .execute(&mut *tx)
        .await?;
    }

    if !added_label_ids.is_empty() || !removed_label_ids.is_empty() {
        let audit_id = record_audit(
            &mut *tx,
            &NewAuditLogEntry {
                workspace_id: Some(workspace_id),
                actor_user_id: Some(actor_user_id),
                actor_device_id: None,
                actor_replica_id: None,
                action_type: "card.labels.updated".to_string(),
                target_entity_type: Some("card".to_string()),
                target_entity_id: Some(card_id),
                request_id: None,
                metadata_jsonb: json!({
                    "boardId": board_id,
                    "cardId": card_id,
                    "labelIds": payload.label_ids.clone(),
                    "addedLabelIds": added_label_ids.clone(),
                    "removedLabelIds": removed_label_ids.clone(),
                }),
            },
        )
        .await?;
        let _activity_id = record_activity(
            &mut *tx,
            &NewActivityEntry {
                workspace_id,
                board_id,
                card_id: Some(card_id),
                actor_user_id: Some(actor_user_id),
                kind: "card.labels.updated",
                entity_type: "card",
                entity_id: card_id,
                field_mask: vec!["labelIds".to_string()],
                payload_jsonb: json!({
                    "cardId": card_id,
                    "labelIds": payload.label_ids.clone(),
                    "addedLabelIds": added_label_ids.clone(),
                    "removedLabelIds": removed_label_ids.clone(),
                }),
                request_id: None,
                source_change_event_id: None,
                source_audit_log_id: Some(audit_id),
            },
        )
        .await?;
    }
    tx.commit().await?;

    fetch_card(pool, card_id).await
}
