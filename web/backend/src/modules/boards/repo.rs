use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::{
        activity::repo::{record_activity, NewActivityEntry},
        audit::repo::{record_audit, NewAuditLogEntry},
        common::{
            board_workspace_id, column_board_and_workspace_id, ensure_user_exists,
            next_position_for_column, normalize_limit, require_workspace_access,
            require_workspace_write, trim_to_option,
        },
    },
};

use super::dto::{
    BoardListResponse, BoardResponse, ColumnListResponse, ColumnResponse, CreateBoardRequest,
    CreateColumnRequest, ListBoardsQuery, PageInfo, UpdateBoardRequest, UpdateColumnRequest,
};

fn map_board(row: &sqlx::postgres::PgRow) -> AppResult<BoardResponse> {
    Ok(BoardResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        workspace_id: row.try_get::<Uuid, _>("workspace_id")?.to_string(),
        name: row.try_get("name")?,
        description: row.try_get("description")?,
        board_type: row.try_get("board_type")?,
        is_archived: row.try_get::<Option<String>, _>("archived_at")?.is_some(),
        label_ids: row
            .try_get::<Option<Vec<Uuid>>, _>("label_ids")?
            .unwrap_or_default()
            .into_iter()
            .map(|id| id.to_string())
            .collect(),
        checklist_count: row.try_get("checklist_count")?,
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

fn map_column(row: &sqlx::postgres::PgRow) -> AppResult<ColumnResponse> {
    Ok(ColumnResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        board_id: row.try_get::<Uuid, _>("board_id")?.to_string(),
        name: row.try_get("name")?,
        description: row.try_get("description")?,
        position: row.try_get::<f64, _>("position")?,
        color_token: row.try_get("color_token")?,
        wip_limit: row.try_get("wip_limit")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

async fn fetch_board(pool: &PgPool, board_id: Uuid) -> AppResult<BoardResponse> {
    let row = sqlx::query(
        r#"
        select
          b.id,
          b.workspace_id,
          b.name,
          b.description,
          b.board_type,
          b.created_by_user_id,
          to_char(b.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(b.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when b.archived_at is null then null else to_char(b.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as archived_at,
          array_remove(array_agg(distinct bl.id), null::uuid) as label_ids,
          (
            select count(*)::bigint from checklists ch
            join cards c on c.id = ch.card_id
            where c.board_id = b.id and ch.deleted_at is null and c.deleted_at is null
          ) as checklist_count,
          (
            select count(*)::bigint from checklist_items chi
            join checklists ch on ch.id = chi.checklist_id
            join cards c on c.id = ch.card_id
            where c.board_id = b.id and chi.deleted_at is null and ch.deleted_at is null and c.deleted_at is null and chi.is_done = true
          ) as checklist_completed_item_count,
          (
            select count(*)::bigint from comments cm
            join cards c on c.id = cm.card_id
            where c.board_id = b.id and cm.deleted_at is null and c.deleted_at is null
          ) as comment_count
        from boards b
        left join board_labels bl on bl.board_id = b.id and bl.deleted_at is null
        where b.id = $1 and b.deleted_at is null
        group by b.id
        "#,
    )
    .bind(board_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Board not found"))?;

    map_board(&row)
}

async fn fetch_column(pool: &PgPool, column_id: Uuid) -> AppResult<ColumnResponse> {
    let row = sqlx::query(
        r#"
        select
          c.id,
          c.board_id,
          c.name,
          c.description,
          c.position::double precision as position,
          c.color_token,
          c.wip_limit,
          to_char(c.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(c.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        from board_columns c
        where c.id = $1
          and c.deleted_at is null
        "#,
    )
    .bind(column_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Column not found"))?;

    map_column(&row)
}

async fn fetch_columns_for_board(pool: &PgPool, board_id: Uuid) -> AppResult<Vec<ColumnResponse>> {
    let rows = sqlx::query(
        r#"
        select
          c.id,
          c.board_id,
          c.name,
          c.description,
          c.position::double precision as position,
          c.color_token,
          c.wip_limit,
          to_char(c.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(c.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        from board_columns c
        where c.board_id = $1
          and c.deleted_at is null
        order by c.position asc, c.id asc
        "#,
    )
    .bind(board_id)
    .fetch_all(pool)
    .await?;

    rows.iter().map(map_column).collect()
}

pub async fn list_boards(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    query: ListBoardsQuery,
) -> AppResult<BoardListResponse> {
    require_workspace_access(pool, workspace_id, actor_user_id).await?;

    let limit = normalize_limit(query.limit);
    let search = trim_to_option(query.q);
    let archived = query.archived.unwrap_or(false);
    let _cursor = query.cursor;

    let rows = sqlx::query(
        r#"
        select
          b.id,
          b.workspace_id,
          b.name,
          b.description,
          b.board_type,
          b.created_by_user_id,
          to_char(b.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(b.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when b.archived_at is null then null else to_char(b.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as archived_at,
          array_remove(array_agg(distinct bl.id), null::uuid) as label_ids,
          (
            select count(*)::bigint from checklists ch
            join cards c on c.id = ch.card_id
            where c.board_id = b.id and ch.deleted_at is null and c.deleted_at is null
          ) as checklist_count,
          (
            select count(*)::bigint from checklist_items chi
            join checklists ch on ch.id = chi.checklist_id
            join cards c on c.id = ch.card_id
            where c.board_id = b.id and chi.deleted_at is null and ch.deleted_at is null and c.deleted_at is null and chi.is_done = true
          ) as checklist_completed_item_count,
          (
            select count(*)::bigint from comments cm
            join cards c on c.id = cm.card_id
            where c.board_id = b.id and cm.deleted_at is null and c.deleted_at is null
          ) as comment_count
        from boards b
        left join board_labels bl on bl.board_id = b.id and bl.deleted_at is null
        where b.workspace_id = $1
          and b.deleted_at is null
          and (($2 = true and b.archived_at is not null) or ($2 = false and b.archived_at is null))
          and ($3::text is null or b.name ilike '%' || $3 || '%' or coalesce(b.description, '') ilike '%' || $3 || '%')
        group by b.id
        order by b.updated_at desc, b.id desc
        limit $4
        "#,
    )
    .bind(workspace_id)
    .bind(archived)
    .bind(search)
    .bind(limit)
    .fetch_all(pool)
    .await?;

    let items = rows.iter().map(map_board).collect::<AppResult<Vec<_>>>()?;

    Ok(BoardListResponse {
        items,
        page_info: PageInfo {
            has_next_page: false,
            next_cursor: None,
        },
    })
}

pub async fn create_board(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    payload: CreateBoardRequest,
) -> AppResult<BoardResponse> {
    ensure_user_exists(pool, actor_user_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let board_id = Uuid::now_v7();

    sqlx::query(
        r#"
        insert into boards (id, workspace_id, name, description, board_type, created_by_user_id)
        values ($1, $2, $3, $4, $5, $6)
        "#,
    )
    .bind(board_id)
    .bind(workspace_id)
    .bind(payload.name.trim())
    .bind(trim_to_option(payload.description))
    .bind(payload.board_type.unwrap_or_else(|| "kanban".to_string()))
    .bind(actor_user_id)
    .execute(pool)
    .await?;

    let board = fetch_board(pool, board_id).await?;
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "board.created".to_string(),
            target_entity_type: Some("board".to_string()),
            target_entity_id: Some(board_id),
            request_id: None,
            metadata_jsonb: json!({
                "name": board.name.clone(),
                "boardType": board.board_type.clone(),
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
            kind: "board.created",
            entity_type: "board",
            entity_id: board_id,
            field_mask: vec![
                "name".to_string(),
                "description".to_string(),
                "boardType".to_string(),
            ],
            payload_jsonb: json!({
                "name": board.name.clone(),
                "description": board.description.clone(),
                "boardType": board.board_type.clone(),
            }),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;

    Ok(board)
}

pub async fn get_board(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<BoardResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    fetch_board(pool, board_id).await
}

pub async fn update_board(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: UpdateBoardRequest,
) -> AppResult<BoardResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let before = fetch_board(pool, board_id).await?;
    let name = payload.name.map(|v| v.trim().to_string());
    let description_changed = payload.description.is_some();
    let description = payload.description.map(trim_to_option);

    let res = sqlx::query(
        r#"
        update boards
        set
          name = coalesce($2, name),
          description = case when $3 then $4 else description end
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(board_id)
    .bind(name)
    .bind(description_changed)
    .bind(description.flatten())
    .execute(pool)
    .await?;

    if res.rows_affected() == 0 {
        return Err(AppError::not_found("Board not found"));
    }

    let board = fetch_board(pool, board_id).await?;
    let mut field_mask = Vec::new();
    let mut changes = serde_json::Map::new();
    if before.name != board.name {
        field_mask.push("name".to_string());
        changes.insert(
            "name".to_string(),
            json!({"before": before.name, "after": board.name.clone()}),
        );
    }
    if before.description != board.description {
        field_mask.push("description".to_string());
        changes.insert(
            "description".to_string(),
            json!({"before": before.description, "after": board.description.clone()}),
        );
    }
    if !field_mask.is_empty() {
        let audit_id = record_audit(
            pool,
            &NewAuditLogEntry {
                workspace_id: Some(workspace_id),
                actor_user_id: Some(actor_user_id),
                actor_device_id: None,
                actor_replica_id: None,
                action_type: "board.updated".to_string(),
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
                kind: "board.updated",
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

    Ok(board)
}

pub async fn archive_board(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<BoardResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let before = fetch_board(pool, board_id).await?;

    let res = sqlx::query(
        "update boards set archived_at = coalesce(archived_at, now()), updated_at = now() where id = $1 and deleted_at is null",
    )
    .bind(board_id)
    .execute(pool)
    .await?;

    if res.rows_affected() == 0 {
        return Err(AppError::not_found("Board not found"));
    }

    let board = fetch_board(pool, board_id).await?;
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "board.archived".to_string(),
            target_entity_type: Some("board".to_string()),
            target_entity_id: Some(board_id),
            request_id: None,
            metadata_jsonb: json!({
                "name": board.name.clone(),
                "wasArchived": before.is_archived,
                "isArchived": board.is_archived,
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
            kind: "board.archived",
            entity_type: "board",
            entity_id: board_id,
            field_mask: vec!["isArchived".to_string()],
            payload_jsonb: json!({"boardName": board.name.clone()}),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;

    Ok(board)
}

pub async fn delete_board(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<BoardResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let board = fetch_board(pool, board_id).await?;

    let mut tx = pool.begin().await?;
    sqlx::query("update boards set deleted_at = now(), updated_at = now() where id = $1 and deleted_at is null")
        .bind(board_id)
        .execute(&mut *tx)
        .await?;
    sqlx::query("update board_columns set deleted_at = now(), updated_at = now() where board_id = $1 and deleted_at is null")
        .bind(board_id)
        .execute(&mut *tx)
        .await?;
    sqlx::query("update cards set deleted_at = now(), updated_at = now() where board_id = $1 and deleted_at is null")
        .bind(board_id)
        .execute(&mut *tx)
        .await?;
    let audit_id = record_audit(
        &mut *tx,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "board.deleted".to_string(),
            target_entity_type: Some("board".to_string()),
            target_entity_id: Some(board_id),
            request_id: None,
            metadata_jsonb: json!({"name": board.name}),
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
            kind: "board.deleted",
            entity_type: "board",
            entity_id: board_id,
            field_mask: vec![],
            payload_jsonb: json!({"name": board.name}),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    tx.commit().await?;

    Ok(board)
}

pub async fn list_columns(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<ColumnListResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    let items = fetch_columns_for_board(pool, board_id).await?;
    Ok(ColumnListResponse { items })
}

pub async fn create_column(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: CreateColumnRequest,
) -> AppResult<ColumnResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let column_id = Uuid::now_v7();
    let position = match payload.position {
        Some(position) => position,
        None => next_position_for_column(pool, board_id).await?,
    };

    let res = sqlx::query(
        r#"
        insert into board_columns (id, board_id, name, description, position, color_token, wip_limit)
        values ($1, $2, $3, $4, $5, $6, $7)
        returning
          id,
          board_id,
          name,
          description,
          position::double precision as position,
          color_token,
          wip_limit,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        "#,
    )
    .bind(column_id)
    .bind(board_id)
    .bind(payload.name.trim())
    .bind(trim_to_option(payload.description))
    .bind(position)
    .bind(trim_to_option(payload.color_token))
    .bind(payload.wip_limit)
    .fetch_one(pool)
    .await;

    match res {
        Ok(row) => {
            let column = map_column(&row)?;
            let audit_id = record_audit(
                pool,
                &NewAuditLogEntry {
                    workspace_id: Some(workspace_id),
                    actor_user_id: Some(actor_user_id),
                    actor_device_id: None,
                    actor_replica_id: None,
                    action_type: "column.created".to_string(),
                    target_entity_type: Some("column".to_string()),
                    target_entity_id: Some(Uuid::parse_str(&column.id).expect("valid column id")),
                    request_id: None,
                    metadata_jsonb: json!({"name": column.name.clone(), "boardId": column.board_id}),
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
                    kind: "column.created",
                    entity_type: "column",
                    entity_id: Uuid::parse_str(&column.id).expect("valid column id"),
                    field_mask: vec!["name".to_string(), "description".to_string(), "position".to_string()],
                    payload_jsonb: json!({"columnName": column.name.clone(), "position": column.position}),
                    request_id: None,
                    source_change_event_id: None,
                    source_audit_log_id: Some(audit_id),
                },
            )
            .await?;
            Ok(column)
        }
        Err(sqlx::Error::Database(db_err)) if db_err.code().as_deref() == Some("23505") => Err(
            AppError::conflict("Column name already exists on this board"),
        ),
        Err(err) => Err(err.into()),
    }
}

pub async fn update_column(
    pool: &PgPool,
    actor_user_id: Uuid,
    column_id: Uuid,
    payload: UpdateColumnRequest,
) -> AppResult<ColumnResponse> {
    let (_board_id, workspace_id) = column_board_and_workspace_id(pool, column_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let before = fetch_column(pool, column_id).await?;
    let name = payload.name.map(|v| v.trim().to_string());
    let description_changed = payload.description.is_some();
    let color_token_changed = payload.color_token.is_some();
    let description = payload.description.map(trim_to_option);
    let color_token = payload.color_token.map(trim_to_option);

    let res = sqlx::query(
        r#"
        update board_columns
        set
          name = coalesce($2, name),
          description = case when $3 then $4 else description end,
          position = coalesce($5, position),
          color_token = case when $6 then $7 else color_token end,
          wip_limit = case when $8 then $9 else wip_limit end
        where id = $1 and deleted_at is null
        returning
          id,
          board_id,
          name,
          description,
          position::double precision as position,
          color_token,
          wip_limit,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        "#,
    )
    .bind(column_id)
    .bind(name)
    .bind(description_changed)
    .bind(description.flatten())
    .bind(payload.position)
    .bind(color_token_changed)
    .bind(color_token.flatten())
    .bind(payload.wip_limit.is_some())
    .bind(payload.wip_limit.flatten())
    .fetch_one(pool)
    .await;

    match res {
        Ok(row) => {
            let column = map_column(&row)?;
            let mut field_mask = Vec::new();
            let mut changes = serde_json::Map::new();
            if before.name != column.name {
                field_mask.push("name".to_string());
                changes.insert(
                    "name".to_string(),
                    json!({"before": before.name, "after": column.name.clone()}),
                );
            }
            if before.description != column.description {
                field_mask.push("description".to_string());
                changes.insert(
                    "description".to_string(),
                    json!({"before": before.description, "after": column.description.clone()}),
                );
            }
            if (before.position - column.position).abs() > f64::EPSILON {
                field_mask.push("position".to_string());
                changes.insert(
                    "position".to_string(),
                    json!({"before": before.position, "after": column.position}),
                );
            }
            if before.color_token != column.color_token {
                field_mask.push("colorToken".to_string());
                changes.insert(
                    "colorToken".to_string(),
                    json!({"before": before.color_token, "after": column.color_token.clone()}),
                );
            }
            if before.wip_limit != column.wip_limit {
                field_mask.push("wipLimit".to_string());
                changes.insert(
                    "wipLimit".to_string(),
                    json!({"before": before.wip_limit, "after": column.wip_limit}),
                );
            }
            if !field_mask.is_empty() {
                let kind = if field_mask.len() == 1 && field_mask[0] == "position" {
                    "column.reordered"
                } else {
                    "column.updated"
                };
                let audit_id = record_audit(
                    pool,
                    &NewAuditLogEntry {
                        workspace_id: Some(workspace_id),
                        actor_user_id: Some(actor_user_id),
                        actor_device_id: None,
                        actor_replica_id: None,
                        action_type: kind.to_string(),
                        target_entity_type: Some("column".to_string()),
                        target_entity_id: Some(column_id),
                        request_id: None,
                        metadata_jsonb: Value::Object(changes.clone()),
                    },
                )
                .await?;
                let _activity_id = record_activity(
                    pool,
                    &NewActivityEntry {
                        workspace_id,
                        board_id: Uuid::parse_str(&column.board_id).expect("valid board id"),
                        card_id: None,
                        actor_user_id: Some(actor_user_id),
                        kind,
                        entity_type: "column",
                        entity_id: column_id,
                        field_mask,
                        payload_jsonb: json!({"columnName": column.name.clone(), "changes": changes}),
                        request_id: None,
                        source_change_event_id: None,
                        source_audit_log_id: Some(audit_id),
                    },
                )
                .await?;
            }
            Ok(column)
        }
        Err(sqlx::Error::RowNotFound) => Err(AppError::not_found("Column not found")),
        Err(sqlx::Error::Database(db_err)) if db_err.code().as_deref() == Some("23505") => Err(
            AppError::conflict("Column name already exists on this board"),
        ),
        Err(err) => Err(err.into()),
    }
}

pub async fn delete_column(
    pool: &PgPool,
    actor_user_id: Uuid,
    column_id: Uuid,
) -> AppResult<ColumnResponse> {
    let (board_id, workspace_id) = column_board_and_workspace_id(pool, column_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;

    let card_count = sqlx::query_scalar::<_, i64>(
        "select count(*)::bigint from cards where column_id = $1 and deleted_at is null",
    )
    .bind(column_id)
    .fetch_one(pool)
    .await?;

    if card_count > 0 {
        return Err(AppError::conflict(
            "Cannot delete a column that still contains active cards",
        ));
    }

    let row = sqlx::query(
        r#"
        update board_columns
        set deleted_at = now(), updated_at = now()
        where id = $1 and deleted_at is null
        returning
          id,
          board_id,
          name,
          description,
          position::double precision as position,
          color_token,
          wip_limit,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at
        "#,
    )
    .bind(column_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Column not found"))?;

    let column = map_column(&row)?;
    let audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "column.deleted".to_string(),
            target_entity_type: Some("column".to_string()),
            target_entity_id: Some(column_id),
            request_id: None,
            metadata_jsonb: json!({"name": column.name.clone(), "boardId": board_id}),
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
            kind: "column.deleted",
            entity_type: "column",
            entity_id: column_id,
            field_mask: vec![],
            payload_jsonb: json!({"columnName": column.name}),
            request_id: None,
            source_change_event_id: None,
            source_audit_log_id: Some(audit_id),
        },
    )
    .await?;
    Ok(column)
}
