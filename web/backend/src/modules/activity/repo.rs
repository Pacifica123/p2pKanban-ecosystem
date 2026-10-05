use serde_json::Value;
use sqlx::{Executor, PgPool, Postgres, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::common::{
        board_workspace_id, card_board_and_workspace_id, normalize_limit, require_workspace_access,
    },
};

use super::dto::{
    ActivityActorResponse, ActivityEntryResponse, ActivityListResponse, BoardProductivityResponse,
    ListActivityQuery, ProductivityDayResponse,
};

const BOARD_FEED_KINDS: &[&str] = &[
    "board.created",
    "board.updated",
    "board.archived",
    "board.deleted",
    "board.appearance.updated",
    "column.created",
    "column.updated",
    "column.deleted",
    "column.reordered",
    "card.created",
    "card.updated",
    "card.moved",
    "card.reordered",
    "card.archived",
    "card.restored",
    "card.deleted",
    "card.labels.updated",
    "label.created",
    "label.updated",
    "label.deleted",
    "checklist.created",
    "checklist.updated",
    "checklist.deleted",
    "checklist_item.created",
    "checklist_item.updated",
    "checklist_item.completed",
    "checklist_item.reopened",
    "checklist_item.deleted",
    "comment.created",
    "comment.updated",
    "comment.deleted",
];

pub struct NewActivityEntry<'a> {
    pub workspace_id: Uuid,
    pub board_id: Uuid,
    pub card_id: Option<Uuid>,
    pub actor_user_id: Option<Uuid>,
    pub kind: &'a str,
    pub entity_type: &'a str,
    pub entity_id: Uuid,
    pub field_mask: Vec<String>,
    pub payload_jsonb: Value,
    pub request_id: Option<Uuid>,
    pub source_change_event_id: Option<Uuid>,
    pub source_audit_log_id: Option<Uuid>,
}

fn decode_cursor(cursor: Option<&str>) -> AppResult<(Option<String>, Option<Uuid>)> {
    let Some(cursor) = cursor else {
        return Ok((None, None));
    };

    let mut parts = cursor.splitn(2, '|');
    let created_at = parts
        .next()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| AppError::bad_request("Invalid cursor"))?
        .to_string();
    let id = parts
        .next()
        .ok_or_else(|| AppError::bad_request("Invalid cursor"))
        .and_then(|value| {
            Uuid::parse_str(value).map_err(|_| AppError::bad_request("Invalid cursor"))
        })?;

    Ok((Some(created_at), Some(id)))
}

fn encode_cursor(created_at: &str, id: Uuid) -> String {
    format!("{created_at}|{id}")
}

fn parse_actor_user_id(value: Option<String>) -> AppResult<Option<Uuid>> {
    value
        .as_deref()
        .map(Uuid::parse_str)
        .transpose()
        .map_err(|_| AppError::bad_request("actorUserId must be a valid UUID"))
}

fn normalize_kinds(mut kinds: Option<Vec<String>>) -> Option<Vec<String>> {
    let Some(values) = kinds.as_mut() else {
        return None;
    };

    values.retain(|value| !value.trim().is_empty());
    if values.is_empty() {
        None
    } else {
        Some(values.clone())
    }
}

fn redact_string(value: &str) -> Value {
    if value.len() > 256 {
        Value::String(format!("{}…", &value[..256]))
    } else {
        Value::String(value.to_string())
    }
}

fn sanitize_json_value(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut sanitized = serde_json::Map::new();
            for (key, inner) in map {
                let lower = key.to_ascii_lowercase();
                let redacted = matches!(
                    lower.as_str(),
                    "password"
                        | "passwordhash"
                        | "refreshtoken"
                        | "accesstoken"
                        | "authorization"
                        | "cookie"
                        | "description"
                        | "customproperties"
                        | "wallpapervalue"
                        | "secret"
                        | "token"
                );
                sanitized.insert(
                    key.clone(),
                    if redacted {
                        Value::String("[redacted]".to_string())
                    } else {
                        sanitize_json_value(inner)
                    },
                );
            }
            Value::Object(sanitized)
        }
        Value::Array(items) => Value::Array(items.iter().map(sanitize_json_value).collect()),
        Value::String(value) => redact_string(value),
        _ => value.clone(),
    }
}

fn map_activity_entry(row: &sqlx::postgres::PgRow) -> AppResult<ActivityEntryResponse> {
    Ok(ActivityEntryResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        created_at: row.try_get("created_at")?,
        kind: row.try_get("kind")?,
        workspace_id: row.try_get::<Uuid, _>("workspace_id")?.to_string(),
        board_id: row.try_get::<Uuid, _>("board_id")?.to_string(),
        card_id: row
            .try_get::<Option<Uuid>, _>("card_id")?
            .map(|id| id.to_string()),
        entity_type: row.try_get("entity_type")?,
        entity_id: row.try_get::<Uuid, _>("entity_id")?.to_string(),
        actor: ActivityActorResponse {
            user_id: row
                .try_get::<Option<Uuid>, _>("actor_user_id")?
                .map(|id| id.to_string()),
            display_name: row.try_get("actor_display_name")?,
        },
        field_mask: row.try_get::<Vec<String>, _>("field_mask")?,
        payload: row.try_get::<Value, _>("payload_jsonb")?,
        request_id: row
            .try_get::<Option<Uuid>, _>("request_id")?
            .map(|id| id.to_string()),
    })
}

pub async fn record_activity<'e, E>(executor: E, entry: &NewActivityEntry<'_>) -> AppResult<Uuid>
where
    E: Executor<'e, Database = Postgres>,
{
    let id = Uuid::now_v7();
    sqlx::query(
        r#"
        insert into activity_entries (
          id,
          workspace_id,
          board_id,
          card_id,
          actor_user_id,
          kind,
          entity_type,
          entity_id,
          field_mask,
          payload_jsonb,
          request_id,
          source_change_event_id,
          source_audit_log_id
        )
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        "#,
    )
    .bind(id)
    .bind(entry.workspace_id)
    .bind(entry.board_id)
    .bind(entry.card_id)
    .bind(entry.actor_user_id)
    .bind(entry.kind)
    .bind(entry.entity_type)
    .bind(entry.entity_id)
    .bind(&entry.field_mask)
    .bind(sanitize_json_value(&entry.payload_jsonb))
    .bind(entry.request_id)
    .bind(entry.source_change_event_id)
    .bind(entry.source_audit_log_id)
    .execute(executor)
    .await?;

    Ok(id)
}

pub async fn get_board_productivity(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
    days: i64,
) -> AppResult<BoardProductivityResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    let days = days.clamp(28, 366) as i32;
    let rows = sqlx::query(
        r#"
        select
          to_char(series.day, 'YYYY-MM-DD') as day,
          count(ae.id)::bigint as action_count
        from generate_series(
          current_date - ($2::int - 1),
          current_date,
          interval '1 day'
        ) as series(day)
        left join activity_entries ae
          on ae.board_id = $1
         and ae.created_at >= series.day
         and ae.created_at < series.day + interval '1 day'
        group by series.day
        order by series.day asc
        "#,
    )
    .bind(board_id)
    .bind(days)
    .fetch_all(pool)
    .await?;

    let values = rows
        .iter()
        .map(|row| {
            Ok(ProductivityDayResponse {
                date: row.try_get("day")?,
                action_count: row.try_get("action_count")?,
            })
        })
        .collect::<AppResult<Vec<_>>>()?;
    let total_actions = values.iter().map(|day| day.action_count).sum();
    Ok(BoardProductivityResponse {
        days: values,
        total_actions,
    })
}

pub async fn list_board_activity(
    pool: &PgPool,
    actor_user_id: Uuid,
    board_id: Uuid,
    query: ListActivityQuery,
) -> AppResult<ActivityListResponse> {
    let workspace_id = board_workspace_id(pool, board_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;

    let limit = normalize_limit(query.limit);
    let (cursor_created_at, cursor_id) = decode_cursor(query.cursor.as_deref())?;
    let actor_filter = parse_actor_user_id(query.actor_user_id)?;
    let mut kinds = normalize_kinds(query.kinds);
    if kinds.is_none() {
        kinds = Some(
            BOARD_FEED_KINDS
                .iter()
                .map(|value| value.to_string())
                .collect(),
        );
    }

    let rows = sqlx::query(
        r#"
        select
          ae.id,
          ae.workspace_id,
          ae.board_id,
          ae.card_id,
          ae.kind,
          ae.entity_type,
          ae.entity_id,
          ae.actor_user_id,
          u.display_name as actor_display_name,
          ae.field_mask,
          ae.payload_jsonb,
          ae.request_id,
          to_char(ae.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at
        from activity_entries ae
        left join users u on u.id = ae.actor_user_id
        where ae.board_id = $1
          and ($2::timestamptz is null or (ae.created_at, ae.id) < ($2::timestamptz, $3::uuid))
          and ($4::uuid is null or ae.actor_user_id = $4)
          and ($5::text[] is null or ae.kind = any($5))
        order by ae.created_at desc, ae.id desc
        limit $6
        "#,
    )
    .bind(board_id)
    .bind(cursor_created_at)
    .bind(cursor_id)
    .bind(actor_filter)
    .bind(kinds)
    .bind(limit + 1)
    .fetch_all(pool)
    .await?;

    let mut items = rows
        .iter()
        .map(map_activity_entry)
        .collect::<AppResult<Vec<_>>>()?;
    let has_more = items.len() as i64 > limit;
    if has_more {
        items.truncate(limit as usize);
    }
    let next_cursor = items.last().filter(|_| has_more).map(|item| {
        encode_cursor(
            &item.created_at,
            Uuid::parse_str(&item.id).expect("valid uuid"),
        )
    });

    Ok(ActivityListResponse { items, next_cursor })
}

pub async fn list_card_activity(
    pool: &PgPool,
    actor_user_id: Uuid,
    card_id: Uuid,
    query: ListActivityQuery,
) -> AppResult<ActivityListResponse> {
    let (_board_id, workspace_id) = card_board_and_workspace_id(pool, card_id).await?;
    require_workspace_access(pool, workspace_id, actor_user_id).await?;

    let limit = normalize_limit(query.limit);
    let (cursor_created_at, cursor_id) = decode_cursor(query.cursor.as_deref())?;
    let actor_filter = parse_actor_user_id(query.actor_user_id)?;
    let kinds = normalize_kinds(query.kinds);

    let rows = sqlx::query(
        r#"
        select
          ae.id,
          ae.workspace_id,
          ae.board_id,
          ae.card_id,
          ae.kind,
          ae.entity_type,
          ae.entity_id,
          ae.actor_user_id,
          u.display_name as actor_display_name,
          ae.field_mask,
          ae.payload_jsonb,
          ae.request_id,
          to_char(ae.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at
        from activity_entries ae
        left join users u on u.id = ae.actor_user_id
        where ae.card_id = $1
          and ($2::timestamptz is null or (ae.created_at, ae.id) < ($2::timestamptz, $3::uuid))
          and ($4::uuid is null or ae.actor_user_id = $4)
          and ($5::text[] is null or ae.kind = any($5))
        order by ae.created_at desc, ae.id desc
        limit $6
        "#,
    )
    .bind(card_id)
    .bind(cursor_created_at)
    .bind(cursor_id)
    .bind(actor_filter)
    .bind(kinds)
    .bind(limit + 1)
    .fetch_all(pool)
    .await?;

    let mut items = rows
        .iter()
        .map(map_activity_entry)
        .collect::<AppResult<Vec<_>>>()?;
    let has_more = items.len() as i64 > limit;
    if has_more {
        items.truncate(limit as usize);
    }
    let next_cursor = items.last().filter(|_| has_more).map(|item| {
        encode_cursor(
            &item.created_at,
            Uuid::parse_str(&item.id).expect("valid uuid"),
        )
    });

    Ok(ActivityListResponse { items, next_cursor })
}
