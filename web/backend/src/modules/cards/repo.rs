use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::{
        activity::repo::{record_activity, NewActivityEntry},
        audit::repo::{record_audit, NewAuditLogEntry},
        common::{
            board_workspace_id, card_board_and_workspace_id, column_board_and_workspace_id,
            ensure_user_exists, next_position_for_card, normalize_limit, require_workspace_access,
            require_workspace_write, trim_to_option,
        },
    },
};

use super::dto::{
    CardListResponse, CardResponse, CreateCardRequest, ListCardsQuery, MoveCardRequest, PageInfo,
    ReorderColumnCardsRequest, UpdateCardRequest,
};

fn map_card(row: &sqlx::postgres::PgRow) -> AppResult<CardResponse> {
    Ok(CardResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        board_id: row.try_get::<Uuid, _>("board_id")?.to_string(),
        column_id: row.try_get::<Uuid, _>("column_id")?.to_string(),
        parent_card_id: row
            .try_get::<Option<Uuid>, _>("parent_card_id")?
            .map(|id| id.to_string()),
        title: row.try_get("title")?,
        description: row.try_get("description")?,
        priority: row.try_get("priority")?,
        position: row.try_get("position")?,
        start_at: row.try_get("start_at")?,
        due_at: row.try_get("due_at")?,
        is_archived: row.try_get::<Option<String>, _>("archived_at")?.is_some(),
        label_ids: row
            .try_get::<Option<Vec<Uuid>>, _>("label_ids")?
            .unwrap_or_default()
            .into_iter()
            .map(|id| id.to_string())
            .collect(),
        checklist_count: row.try_get("checklist_count")?,
        checklist_item_count: row.try_get("checklist_item_count")?,
        checklist_completed_item_count: row.try_get("checklist_completed_item_count")?,
        comment_count: row.try_get("comment_count")?,
        created_by_user_id: row
            .try_get::<Option<Uuid>, _>("created_by_user_id")?
            .map(|id| id.to_string()),
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
        archived_at: row.try_get("archived_at")?,
    })
}

pub async fn fetch_card(pool: &PgPool, card_id: Uuid) -> AppResult<CardResponse> {
    let row = sqlx::query(
        r#"
        select
          c.id,
          c.board_id,
          c.column_id,
          c.parent_card_id,
          c.title,
          c.description,
          c.priority,
          c.position::double precision as position,
          case when c.start_at is null then null else to_char(c.start_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as start_at,
          case when c.due_at is null then null else to_char(c.due_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as due_at,
          c.created_by_user_id,
          to_char(c.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(c.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when c.archived_at is null then null else to_char(c.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as archived_at,
          array_remove(array_agg(distinct cl.label_id), null::uuid) as label_ids,
          (
            select count(*)::bigint from checklists ch
            where ch.card_id = c.id and ch.deleted_at is null
          ) as checklist_count,
          (
            select count(*)::bigint from checklist_items chi
            join checklists ch on ch.id = chi.checklist_id
            where ch.card_id = c.id and ch.deleted_at is null and chi.deleted_at is null
          ) as checklist_item_count,
          (
            select count(*)::bigint from checklist_items chi
            join checklists ch on ch.id = chi.checklist_id
            where ch.card_id = c.id and ch.deleted_at is null and chi.deleted_at is null and chi.is_done = true
          ) as checklist_completed_item_count,
          (
            select count(*)::bigint from comments cm
            where cm.card_id = c.id and cm.deleted_at is null
          ) as comment_count
        from cards c
        left join card_labels cl on cl.card_id = c.id and cl.deleted_at is null
        where c.id = $1 and c.deleted_at is null
        group by c.id
        "#,
    )
    .bind(card_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Card not found"))?;

    map_card(&row)
}

pub async fn list_cards(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
    query: ListCardsQuery,
) -> AppResult<CardListResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;

    let limit = normalize_limit(query.limit);
    let search = trim_to_option(query.q);
    let _cursor = query.cursor;
    let column_id = query
        .column_id
        .as_deref()
        .map(Uuid::parse_str)
        .transpose()
        .map_err(|_| AppError::bad_request("columnId must be a valid UUID"))?;
    let label_id = query
        .label_id
        .as_deref()
        .map(Uuid::parse_str)
        .transpose()
        .map_err(|_| AppError::bad_request("labelId must be a valid UUID"))?;
    let sort_by = query.sort_by.unwrap_or_else(|| "updatedAt".to_string());
    let sort_dir = query.sort_dir.unwrap_or_else(|| "desc".to_string());
    let local_visibility = query
        .local_visibility
        .unwrap_or_else(|| "visible".to_string());
    if !matches!(local_visibility.as_str(), "visible" | "hidden" | "all") {
        return Err(AppError::bad_request(
            "localVisibility must be visible, hidden, or all",
        ));
    }

    let order_clause = match (sort_by.as_str(), sort_dir.as_str()) {
        ("position", "asc") => "c.position asc, c.id asc",
        ("position", _) => "c.position desc, c.id desc",
        ("createdAt", "asc") => "c.created_at asc, c.id asc",
        ("createdAt", _) => "c.created_at desc, c.id desc",
        ("updatedAt", "asc") => "c.updated_at asc, c.id asc",
        ("updatedAt", _) => "c.updated_at desc, c.id desc",
        ("dueAt", "asc") => "c.due_at asc nulls last, c.id asc",
        ("dueAt", _) => "c.due_at desc nulls last, c.id desc",
        ("priority", "asc") => "c.priority asc nulls last, c.id asc",
        ("priority", _) => "c.priority desc nulls last, c.id desc",
        _ => return Err(AppError::bad_request("Unsupported card sorting")),
    };

    let sql = format!(
        r#"
        select
          c.id,
          c.board_id,
          c.column_id,
          c.parent_card_id,
          c.title,
          c.description,
          c.priority,
          c.position::double precision as position,
          case when c.start_at is null then null else to_char(c.start_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as start_at,
          case when c.due_at is null then null else to_char(c.due_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as due_at,
          c.created_by_user_id,
          to_char(c.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(c.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when c.archived_at is null then null else to_char(c.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as archived_at,
          array_remove(array_agg(distinct cl.label_id), null::uuid) as label_ids,
          (
            select count(*)::bigint from checklists ch
            where ch.card_id = c.id and ch.deleted_at is null
          ) as checklist_count,
          (
            select count(*)::bigint from checklist_items chi
            join checklists ch on ch.id = chi.checklist_id
            where ch.card_id = c.id and ch.deleted_at is null and chi.deleted_at is null
          ) as checklist_item_count,
          (
            select count(*)::bigint from checklist_items chi
            join checklists ch on ch.id = chi.checklist_id
            where ch.card_id = c.id and ch.deleted_at is null and chi.deleted_at is null and chi.is_done = true
          ) as checklist_completed_item_count,
          (
            select count(*)::bigint from comments cm
            where cm.card_id = c.id and cm.deleted_at is null
          ) as comment_count
        from cards c
        left join card_labels cl on cl.card_id = c.id and cl.deleted_at is null
        where c.board_id = $1
          and c.deleted_at is null
          and (
            $5::text = 'all'
            or ($5 = 'visible' and not exists (
              select 1
              from local_card_hides lch
              cross join local_node_identity lni
              where lch.node_replica_id = lni.replica_id
                and lch.user_id = $6
                and lch.card_id = c.id
            ))
            or ($5 = 'hidden' and exists (
              select 1
              from local_card_hides lch
              cross join local_node_identity lni
              where lch.node_replica_id = lni.replica_id
                and lch.user_id = $6
                and lch.card_id = c.id
            ))
          )
          and ($2::uuid is null or c.column_id = $2)
          and ($3::uuid is null or exists (
                select 1 from card_labels cl2
                where cl2.card_id = c.id and cl2.label_id = $3 and cl2.deleted_at is null
          ))
          and (
            $4::text is null
            or c.title ilike '%' || $4 || '%'
            or coalesce(c.description, '') ilike '%' || $4 || '%'
          )
        group by c.id
        order by {order_clause}
        limit $7
        "#,
    );

    let rows = sqlx::query(&sql)
        .bind(board_id)
        .bind(column_id)
        .bind(label_id)
        .bind(search)
        .bind(local_visibility)
        .bind(actor_user_id)
        .bind(limit)
        .fetch_all(pool)
        .await?;

    let items = rows.iter().map(map_card).collect::<AppResult<Vec<_>>>()?;

    Ok(CardListResponse {
        items,
        page_info: PageInfo {
            has_next_page: false,
            next_cursor: None,
        },
    })
}

pub async fn create_card(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: CreateCardRequest,
) -> AppResult<CardResponse> {
    ensure_user_exists(pool, actor_user_id).await?;
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let card_id = Uuid::now_v7();
    let position = match payload.position {
        Some(position) => position,
        None => next_position_for_card(pool, board_id, payload.column_id).await?,
    };
    sqlx::query(
        r#"
        insert into cards (
          id, board_id, column_id, parent_card_id, title, description, position,
          priority, start_at, due_at, created_by_user_id
        )
        values (
          $1, $2, $3, $4, $5, $6, $7,
          $8, $9::timestamptz, $10::timestamptz, $11
        )
        "#,
    )
    .bind(card_id)
    .bind(board_id)
    .bind(payload.column_id)
    .bind(payload.parent_card_id)
    .bind(payload.title.trim())
    .bind(payload.description.filter(|s| !s.is_empty()))
    .bind(position)
    .bind(payload.priority)
    .bind(payload.start_at)
    .bind(payload.due_at)
    .bind(actor_user_id)
    .execute(pool)
    .await?;

    let card = fetch_card(pool, card_id).await?;
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "card.created".to_string(),
            target_entity_type: Some("card".to_string()),
            target_entity_id: Some(card_id),
            request_id: None,
            metadata_jsonb: json!({
                "title": card.title.clone(),
                "columnId": card.column_id.clone(),
                "boardId": card.board_id.clone(),
            }),
        },
    )
    .await?;
    let _activity_id = record_activity(
        pool,
        &NewActivityEntry {
            workspace_id,
            board_id,
            card_id: Some(card_id),
            actor_user_id: Some(actor_user_id),
            kind: "card.created",
            entity_type: "card",
            entity_id: card_id,
            field_mask: vec![
                "title".to_string(),
                "description".to_string(),
                "columnId".to_string(),
            ],
            payload_jsonb: json!({
                "cardTitle": card.title.clone(),
                "columnId": card.column_id.clone(),
                "description": card.description.clone(),
            }),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;

    Ok(card)
}

pub async fn get_card(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    let hidden_here = sqlx::query_scalar::<_, bool>(
        r#"
        select exists(
          select 1
          from local_card_hides lch
          cross join local_node_identity lni
          where lch.node_replica_id = lni.replica_id
            and lch.user_id = $1
            and lch.card_id = $2
        )
        "#,
    )
    .bind(actor_user_id)
    .bind(card_id)
    .fetch_one(pool)
    .await?;
    if hidden_here {
        return Err(AppError::not_found("Card is hidden on this node"));
    }
    fetch_card(pool, card_id).await
}

pub async fn hide_card_locally(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    let card = fetch_card(pool, card_id).await?;
    sqlx::query(
        r#"
        insert into local_card_hides (node_replica_id, user_id, card_id)
        select replica_id, $1, $2
        from local_node_identity
        on conflict (node_replica_id, user_id, card_id) do update set
          hidden_at = now()
        "#,
    )
    .bind(actor_user_id)
    .bind(card_id)
    .execute(pool)
    .await?;
    Ok(card)
}

pub async fn unhide_card_locally(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    let card = fetch_card(pool, card_id).await?;
    sqlx::query(
        r#"
        delete from local_card_hides lch
        using local_node_identity lni
        where lch.node_replica_id = lni.replica_id
          and lch.user_id = $1
          and lch.card_id = $2
        "#,
    )
    .bind(actor_user_id)
    .bind(card_id)
    .execute(pool)
    .await?;
    Ok(card)
}

pub async fn update_card(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: UpdateCardRequest,
) -> AppResult<CardResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let before = fetch_card(pool, card_id).await?;
    let title = payload.title.map(|v| v.trim().to_string());
    let description_changed = payload.description.is_some();
    let description = payload.description.map(|v| v.filter(|s| !s.is_empty()));
    let start_at = payload.start_at.clone();
    let due_at = payload.due_at.clone();
    let row = sqlx::query(
        r#"
        update cards
        set
          title = coalesce($2, title),
          description = case when $3 then $4 else description end,
          column_id = coalesce($5, column_id),
          parent_card_id = case when $6 then $7 else parent_card_id end,
          priority = case when $8 then $9 else priority end,
          position = coalesce($10, position),
          start_at = case when $11 then $12::timestamptz else start_at end,
          due_at = case when $13 then $14::timestamptz else due_at end,
          archived_at = case
            when $15 then now()
            when $16 then null
            else archived_at
          end
        where id = $1 and deleted_at is null
        returning id
        "#,
    )
    .bind(card_id)
    .bind(title)
    .bind(description_changed)
    .bind(description.flatten())
    .bind(payload.column_id)
    .bind(payload.parent_card_id.is_some())
    .bind(payload.parent_card_id.flatten())
    .bind(payload.priority.is_some())
    .bind(payload.priority.flatten())
    .bind(payload.position)
    .bind(payload.start_at.is_some())
    .bind(start_at.flatten())
    .bind(payload.due_at.is_some())
    .bind(due_at.flatten())
    .bind(matches!(payload.is_archived, Some(true)))
    .bind(matches!(payload.is_archived, Some(false)))
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Card not found"))?;

    let _id: Uuid = row.try_get("id")?;
    let card = fetch_card(pool, card_id).await?;
    let mut field_mask = Vec::new();
    let mut changes = serde_json::Map::new();
    if before.title != card.title {
        field_mask.push("title".to_string());
        changes.insert(
            "title".to_string(),
            json!({"before": before.title, "after": card.title.clone()}),
        );
    }
    if before.description != card.description {
        field_mask.push("description".to_string());
        changes.insert(
            "description".to_string(),
            json!({"before": before.description, "after": card.description.clone()}),
        );
    }
    if before.column_id != card.column_id {
        field_mask.push("columnId".to_string());
        changes.insert(
            "columnId".to_string(),
            json!({"before": before.column_id, "after": card.column_id.clone()}),
        );
    }
    if before.priority != card.priority {
        field_mask.push("priority".to_string());
        changes.insert(
            "priority".to_string(),
            json!({"before": before.priority, "after": card.priority.clone()}),
        );
    }
    if before.start_at != card.start_at {
        field_mask.push("startAt".to_string());
        changes.insert(
            "startAt".to_string(),
            json!({"before": before.start_at, "after": card.start_at.clone()}),
        );
    }
    if before.due_at != card.due_at {
        field_mask.push("dueAt".to_string());
        changes.insert(
            "dueAt".to_string(),
            json!({"before": before.due_at, "after": card.due_at.clone()}),
        );
    }
    if before.is_archived != card.is_archived {
        field_mask.push("isArchived".to_string());
        changes.insert(
            "isArchived".to_string(),
            json!({"before": before.is_archived, "after": card.is_archived}),
        );
    }
    if !field_mask.is_empty() {
        let kind = if before.is_archived != card.is_archived {
            if card.is_archived {
                "card.archived"
            } else {
                "card.restored"
            }
        } else if before.column_id != card.column_id {
            "card.moved"
        } else {
            "card.updated"
        };
        let audit_id = record_audit(
            pool,
            &NewAuditLogEntry {
                workspace_id: Some(workspace_id),
                actor_user_id: Some(actor_user_id),
                actor_device_id: None,
                actor_replica_id: None,
                action_type: kind.to_string(),
                target_entity_type: Some("card".to_string()),
                target_entity_id: Some(card_id),
                request_id: None,
                metadata_jsonb: Value::Object(changes.clone()),
            },
        )
        .await?;
        let payload_jsonb = if kind == "card.moved" {
            json!({
                "cardTitle": card.title.clone(),
                "fromColumnId": before.column_id,
                "toColumnId": card.column_id.clone(),
                "changes": changes,
            })
        } else {
            json!({
                "cardTitle": card.title.clone(),
                "changes": changes,
            })
        };
        let _activity_id = record_activity(
            pool,
            &NewActivityEntry {
                workspace_id,
                board_id: Uuid::parse_str(&card.board_id).expect("valid board id"),
                card_id: Some(card_id),
                actor_user_id: Some(actor_user_id),
                kind,
                entity_type: "card",
                entity_id: card_id,
                field_mask,
                payload_jsonb,
                request_id: None,
                source_change_event_id: None,
                source_audit_log_id: Some(audit_id),
            },
        )
        .await?;
    }
    Ok(card)
}

pub async fn delete_card(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let card = fetch_card(pool, card_id).await?;

    let mut tx = pool.begin().await?;
    sqlx::query("update cards set deleted_at = now(), updated_at = now() where id = $1 and deleted_at is null")
        .bind(card_id)
        .execute(&mut *tx)
        .await?;

    sqlx::query(
        r#"
        insert into tombstones (
          id, workspace_id, entity_type, entity_id,
          deleted_by_user_id, deleted_by_replica_id, deleted_at, metadata_jsonb
        )
        select
          gen_random_uuid(), $2, 'card', c.id,
          $3, n.replica_id, c.deleted_at,
          jsonb_build_object(
            'boardId', c.board_id,
            'cardTitle', c.title,
            'scope', 'all_devices',
            'source', 'card.delete'
          )
        from cards c
        cross join local_node_identity n
        where c.id = $1
        on conflict (entity_type, entity_id) do update set
          deleted_by_user_id = excluded.deleted_by_user_id,
          deleted_by_replica_id = excluded.deleted_by_replica_id,
          deleted_at = greatest(tombstones.deleted_at, excluded.deleted_at),
          metadata_jsonb = tombstones.metadata_jsonb || excluded.metadata_jsonb
        "#,
    )
    .bind(card_id)
    .bind(workspace_id)
    .bind(actor_user_id)
    .execute(&mut *tx)
    .await?;

    let audit_id = record_audit(
        &mut *tx,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "card.deleted".to_string(),
            target_entity_type: Some("card".to_string()),
            target_entity_id: Some(card_id),
            request_id: None,
            metadata_jsonb: json!({
                "title": card.title.clone(),
                "boardId": card.board_id,
                "scope": "all_devices",
            }),
        },
    )
    .await?;
    let _activity_id = record_activity(
        &mut *tx,
        &NewActivityEntry {
            workspace_id,
            board_id: Uuid::parse_str(&card.board_id).expect("valid board id"),
            card_id: Some(card_id),
            actor_user_id: Some(actor_user_id),
            kind: "card.deleted",
            entity_type: "card",
            entity_id: card_id,
            field_mask: vec!["__lifecycle".to_string()],
            payload_jsonb: json!({
                "cardTitle": card.title,
                "scope": "all_devices",
            }),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    tx.commit().await?;

    Ok(card)
}

pub async fn move_card(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: MoveCardRequest,
) -> AppResult<CardResponse> {
    let (board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let before = fetch_card(pool, card_id).await?;
    let position = match payload.position {
        Some(position) => position,
        None => next_position_for_card(pool, board_id, payload.target_column_id).await?,
    };

    let row = sqlx::query(
        r#"
        update cards
        set column_id = $2, position = $3
        where id = $1 and deleted_at is null
        returning id
        "#,
    )
    .bind(card_id)
    .bind(payload.target_column_id)
    .bind(position)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Card not found"))?;

    let _id: Uuid = row.try_get("id")?;
    let card = fetch_card(pool, card_id).await?;
    let mut field_mask = Vec::new();
    let mut changes = serde_json::Map::new();
    if before.title != card.title {
        field_mask.push("title".to_string());
        changes.insert(
            "title".to_string(),
            json!({"before": before.title, "after": card.title.clone()}),
        );
    }
    if before.description != card.description {
        field_mask.push("description".to_string());
        changes.insert(
            "description".to_string(),
            json!({"before": before.description, "after": card.description.clone()}),
        );
    }
    if before.column_id != card.column_id {
        field_mask.push("columnId".to_string());
        changes.insert(
            "columnId".to_string(),
            json!({"before": before.column_id, "after": card.column_id.clone()}),
        );
    }
    if before.priority != card.priority {
        field_mask.push("priority".to_string());
        changes.insert(
            "priority".to_string(),
            json!({"before": before.priority, "after": card.priority.clone()}),
        );
    }
    if before.start_at != card.start_at {
        field_mask.push("startAt".to_string());
        changes.insert(
            "startAt".to_string(),
            json!({"before": before.start_at, "after": card.start_at.clone()}),
        );
    }
    if before.due_at != card.due_at {
        field_mask.push("dueAt".to_string());
        changes.insert(
            "dueAt".to_string(),
            json!({"before": before.due_at, "after": card.due_at.clone()}),
        );
    }
    if before.is_archived != card.is_archived {
        field_mask.push("isArchived".to_string());
        changes.insert(
            "isArchived".to_string(),
            json!({"before": before.is_archived, "after": card.is_archived}),
        );
    }
    if !field_mask.is_empty() {
        let kind = if before.is_archived != card.is_archived {
            if card.is_archived {
                "card.archived"
            } else {
                "card.restored"
            }
        } else if before.column_id != card.column_id {
            "card.moved"
        } else {
            "card.updated"
        };
        let audit_id = record_audit(
            pool,
            &NewAuditLogEntry {
                workspace_id: Some(workspace_id),
                actor_user_id: Some(actor_user_id),
                actor_device_id: None,
                actor_replica_id: None,
                action_type: kind.to_string(),
                target_entity_type: Some("card".to_string()),
                target_entity_id: Some(card_id),
                request_id: None,
                metadata_jsonb: Value::Object(changes.clone()),
            },
        )
        .await?;
        let payload_jsonb = if kind == "card.moved" {
            json!({
                "cardTitle": card.title.clone(),
                "fromColumnId": before.column_id,
                "toColumnId": card.column_id.clone(),
                "changes": changes,
            })
        } else {
            json!({
                "cardTitle": card.title.clone(),
                "changes": changes,
            })
        };
        let _activity_id = record_activity(
            pool,
            &NewActivityEntry {
                workspace_id,
                board_id: Uuid::parse_str(&card.board_id).expect("valid board id"),
                card_id: Some(card_id),
                actor_user_id: Some(actor_user_id),
                kind,
                entity_type: "card",
                entity_id: card_id,
                field_mask,
                payload_jsonb,
                request_id: None,
                source_change_event_id: None,
                source_audit_log_id: Some(audit_id),
            },
        )
        .await?;
    }
    Ok(card)
}

pub async fn reorder_column_cards(
    pool: &PgPool,
    actor_user_id: Uuid,
    column_id: Uuid,
    payload: ReorderColumnCardsRequest,
) -> AppResult<CardListResponse> {
    let (board_id, workspace_id) = column_board_and_workspace_id(pool, column_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let card_ids = payload
        .items
        .iter()
        .map(|item| item.card_id)
        .collect::<Vec<_>>();
    let existing_count = sqlx::query_scalar::<_, i64>(
        r#"
        select count(*)::bigint
        from cards
        where board_id = $1
          and column_id = $2
          and id = any($3)
          and deleted_at is null
        "#,
    )
    .bind(board_id)
    .bind(column_id)
    .bind(&card_ids)
    .fetch_one(pool)
    .await?;

    if existing_count != card_ids.len() as i64 {
        return Err(AppError::bad_request(
            "All reordered cards must belong to the target column",
        ));
    }

    let mut tx = pool.begin().await?;
    for item in &payload.items {
        sqlx::query(
            r#"
            update cards
            set position = $3
            where id = $1
              and column_id = $2
              and board_id = $4
              and deleted_at is null
            "#,
        )
        .bind(item.card_id)
        .bind(column_id)
        .bind(item.position)
        .bind(board_id)
        .execute(&mut *tx)
        .await?;
    }

    let items_json = payload
        .items
        .iter()
        .map(|item| json!({"cardId": item.card_id.to_string(), "position": item.position}))
        .collect::<Vec<_>>();
    let audit_id = record_audit(
        &mut *tx,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "card.reordered".to_string(),
            target_entity_type: Some("column".to_string()),
            target_entity_id: Some(column_id),
            request_id: None,
            metadata_jsonb: json!({
                "boardId": board_id.to_string(),
                "columnId": column_id.to_string(),
                "items": items_json.clone(),
            }),
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
            kind: "card.reordered",
            entity_type: "column",
            entity_id: column_id,
            field_mask: vec!["position".to_string()],
            payload_jsonb: json!({
                "columnId": column_id.to_string(),
                "items": items_json,
            }),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    tx.commit().await?;

    list_cards(
        pool,
        actor_user_id,
        board_id,
        ListCardsQuery {
            limit: Some(100),
            cursor: None,
            q: None,
            column_id: Some(column_id.to_string()),
            label_id: None,
            sort_by: Some("position".to_string()),
            sort_dir: Some("asc".to_string()),
            local_visibility: Some("visible".to_string()),
        },
    )
    .await
}

pub async fn archive_card(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    sqlx::query("update cards set archived_at = now(), updated_at = now() where id = $1 and deleted_at is null")
        .bind(card_id)
        .execute(pool)
        .await?;

    let card = fetch_card(pool, card_id).await?;
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "card.archived".to_string(),
            target_entity_type: Some("card".to_string()),
            target_entity_id: Some(card_id),
            request_id: None,
            metadata_jsonb: json!({"title": card.title}),
        },
    )
    .await?;
    let _activity_id = record_activity(
        pool,
        &NewActivityEntry {
            workspace_id,
            board_id: Uuid::parse_str(&card.board_id).expect("valid board id"),
            card_id: Some(card_id),
            actor_user_id: Some(actor_user_id),
            kind: "card.archived",
            entity_type: "card",
            entity_id: card_id,
            field_mask: vec!["isArchived".to_string()],
            payload_jsonb: json!({"cardTitle": card.title}),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    Ok(card)
}

pub async fn unarchive_card(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
) -> AppResult<CardResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    sqlx::query("update cards set archived_at = null, updated_at = now() where id = $1 and deleted_at is null")
        .bind(card_id)
        .execute(pool)
        .await?;

    let card = fetch_card(pool, card_id).await?;
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "card.restored".to_string(),
            target_entity_type: Some("card".to_string()),
            target_entity_id: Some(card_id),
            request_id: None,
            metadata_jsonb: json!({"title": card.title}),
        },
    )
    .await?;
    let _activity_id = record_activity(
        pool,
        &NewActivityEntry {
            workspace_id,
            board_id: Uuid::parse_str(&card.board_id).expect("valid board id"),
            card_id: Some(card_id),
            actor_user_id: Some(actor_user_id),
            kind: "card.restored",
            entity_type: "card",
            entity_id: card_id,
            field_mask: vec!["isArchived".to_string()],
            payload_jsonb: json!({"cardTitle": card.title}),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    Ok(card)
}
