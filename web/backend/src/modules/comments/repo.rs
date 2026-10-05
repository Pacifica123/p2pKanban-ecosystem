use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::{
        activity::repo::{record_activity, NewActivityEntry},
        audit::repo::{record_audit, NewAuditLogEntry},
        common::{
            card_board_and_workspace_id, normalize_limit, require_workspace_access,
            require_workspace_write,
        },
    },
};

use super::dto::{
    CommentListResponse, CommentResponse, CreateCommentRequest, ListCommentsQuery, PageInfo,
    UpdateCommentRequest,
};

fn map_comment(row: &sqlx::postgres::PgRow) -> AppResult<CommentResponse> {
    Ok(CommentResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        card_id: row.try_get::<Uuid, _>("card_id")?.to_string(),
        author_user_id: row
            .try_get::<Option<Uuid>, _>("author_user_id")?
            .map(|id| id.to_string()),
        body: row.try_get("body")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
        edited_at: row.try_get("edited_at")?,
    })
}

async fn fetch_comment(pool: &PgPool, comment_id: Uuid) -> AppResult<CommentResponse> {
    let row = sqlx::query(
        r#"
        select
          id,
          card_id,
          author_user_id,
          body,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when updated_at > created_at then to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') else null end as edited_at
        from comments
        where id = $1 and deleted_at is null
        "#,
    )
    .bind(comment_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Comment not found"))?;
    map_comment(&row)
}

async fn comment_context(pool: &PgPool, comment_id: Uuid) -> AppResult<(Uuid, Uuid, Uuid)> {
    let row = sqlx::query(
        r#"
        select c.card_id, card.board_id, b.workspace_id
        from comments c
        join cards card on card.id = c.card_id
        join boards b on b.id = card.board_id
        where c.id = $1
          and c.deleted_at is null
          and card.deleted_at is null
          and b.deleted_at is null
        "#,
    )
    .bind(comment_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Comment not found"))?;

    Ok((
        row.try_get("card_id")?,
        row.try_get("board_id")?,
        row.try_get("workspace_id")?,
    ))
}

fn encode_cursor(created_at: &str, id: &str) -> String {
    format!("{created_at}|{id}")
}

pub async fn list_comments(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
    query: ListCommentsQuery,
) -> AppResult<CommentListResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    let limit = normalize_limit(query.limit);
    let _cursor = query.cursor;

    let rows = sqlx::query(
        r#"
        select
          id,
          card_id,
          author_user_id,
          body,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when updated_at > created_at then to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') else null end as edited_at
        from comments
        where card_id = $1 and deleted_at is null
        order by created_at asc, id asc
        limit $2
        "#,
    )
    .bind(card_id)
    .bind(limit + 1)
    .fetch_all(pool)
    .await?;

    let mut items = rows
        .iter()
        .map(map_comment)
        .collect::<AppResult<Vec<_>>>()?;
    let has_more = items.len() as i64 > limit;
    if has_more {
        items.truncate(limit as usize);
    }
    let next_cursor = items
        .last()
        .filter(|_| has_more)
        .map(|comment| encode_cursor(&comment.created_at, &comment.id));

    Ok(CommentListResponse {
        items,
        page_info: PageInfo {
            has_next_page: has_more,
            next_cursor,
        },
    })
}

pub async fn create_comment(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
    payload: CreateCommentRequest,
) -> AppResult<CommentResponse> {
    let (board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let comment_id = Uuid::now_v7();

    sqlx::query(
        r#"
        insert into comments (id, card_id, author_user_id, body)
        values ($1, $2, $3, $4)
        "#,
    )
    .bind(comment_id)
    .bind(card_id)
    .bind(actor_user_id)
    .bind(payload.body.trim())
    .execute(pool)
    .await?;

    let comment = fetch_comment(pool, comment_id).await?;
    record_comment_activity(
        pool,
        workspace_id,
        board_id,
        card_id,
        actor_user_id,
        "comment.created",
        comment_id,
        vec!["body".to_string()],
        json!({"commentId": comment_id, "body": comment.body.clone()}),
    )
    .await?;
    Ok(comment)
}

pub async fn update_comment(
    pool: &PgPool,
    actor_user_id: Uuid,
    comment_id: Uuid,
    payload: UpdateCommentRequest,
) -> AppResult<CommentResponse> {
    let (card_id, board_id, workspace_id) = comment_context(pool, comment_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let before = fetch_comment(pool, comment_id).await?;

    sqlx::query(
        "update comments set body = coalesce($2, body) where id = $1 and deleted_at is null",
    )
    .bind(comment_id)
    .bind(payload.body.map(|value| value.trim().to_string()))
    .execute(pool)
    .await?;

    let comment = fetch_comment(pool, comment_id).await?;
    if before.body != comment.body {
        record_comment_activity(
            pool,
            workspace_id,
            board_id,
            card_id,
            actor_user_id,
            "comment.updated",
            comment_id,
            vec!["body".to_string()],
            json!({"commentId": comment_id, "body": comment.body.clone()}),
        )
        .await?;
    }
    Ok(comment)
}

pub async fn delete_comment(
    pool: &PgPool,
    actor_user_id: Uuid,
    comment_id: Uuid,
) -> AppResult<CommentResponse> {
    let (card_id, board_id, workspace_id) = comment_context(pool, comment_id).await?;
    require_workspace_write(pool, workspace_id, actor_user_id).await?;
    let comment = fetch_comment(pool, comment_id).await?;

    sqlx::query("update comments set deleted_at = now() where id = $1 and deleted_at is null")
        .bind(comment_id)
        .execute(pool)
        .await?;

    record_comment_activity(
        pool,
        workspace_id,
        board_id,
        card_id,
        actor_user_id,
        "comment.deleted",
        comment_id,
        vec![],
        json!({"commentId": comment_id}),
    )
    .await?;
    Ok(comment)
}

async fn record_comment_activity(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Uuid,
    card_id: Uuid,
    actor_user_id: Uuid,
    kind: &'static str,
    comment_id: Uuid,
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
            target_entity_type: Some("comment".to_string()),
            target_entity_id: Some(comment_id),
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
            entity_type: "comment",
            entity_id: comment_id,
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
