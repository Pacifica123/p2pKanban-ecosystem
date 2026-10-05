use serde_json::Value;
use sqlx::{Executor, PgPool, Postgres, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::common::require_workspace_owner,
};

use super::dto::{AuditLogEntryResponse, AuditLogListResponse, ListAuditLogQuery};

pub struct NewAuditLogEntry {
    pub workspace_id: Option<Uuid>,
    pub actor_user_id: Option<Uuid>,
    pub actor_device_id: Option<Uuid>,
    pub actor_replica_id: Option<Uuid>,
    pub action_type: String,
    pub target_entity_type: Option<String>,
    pub target_entity_id: Option<Uuid>,
    pub request_id: Option<Uuid>,
    pub metadata_jsonb: Value,
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

fn parse_uuid_filter(value: Option<String>, field_name: &str) -> AppResult<Option<Uuid>> {
    value
        .as_deref()
        .map(Uuid::parse_str)
        .transpose()
        .map_err(|_| AppError::bad_request(format!("{field_name} must be a valid UUID")))
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

fn map_audit_entry(row: &sqlx::postgres::PgRow) -> AppResult<AuditLogEntryResponse> {
    Ok(AuditLogEntryResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        created_at: row.try_get("created_at")?,
        action_type: row.try_get("action_type")?,
        workspace_id: row
            .try_get::<Option<Uuid>, _>("workspace_id")?
            .map(|id| id.to_string()),
        actor_user_id: row
            .try_get::<Option<Uuid>, _>("actor_user_id")?
            .map(|id| id.to_string()),
        target_entity_type: row.try_get("target_entity_type")?,
        target_entity_id: row
            .try_get::<Option<Uuid>, _>("target_entity_id")?
            .map(|id| id.to_string()),
        request_id: row
            .try_get::<Option<Uuid>, _>("request_id")?
            .map(|id| id.to_string()),
        metadata: row.try_get::<Value, _>("metadata_jsonb")?,
    })
}

pub async fn record_audit<'e, E>(executor: E, entry: &NewAuditLogEntry) -> AppResult<Uuid>
where
    E: Executor<'e, Database = Postgres>,
{
    let id = Uuid::now_v7();
    sqlx::query(
        r#"
        insert into audit_log (
          id,
          workspace_id,
          actor_user_id,
          actor_device_id,
          actor_replica_id,
          action_type,
          target_entity_type,
          target_entity_id,
          request_id,
          metadata_jsonb
        )
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        "#,
    )
    .bind(id)
    .bind(entry.workspace_id)
    .bind(entry.actor_user_id)
    .bind(entry.actor_device_id)
    .bind(entry.actor_replica_id)
    .bind(&entry.action_type)
    .bind(&entry.target_entity_type)
    .bind(entry.target_entity_id)
    .bind(entry.request_id)
    .bind(sanitize_json_value(&entry.metadata_jsonb))
    .execute(executor)
    .await?;

    Ok(id)
}

pub async fn list_workspace_audit_log(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    query: ListAuditLogQuery,
) -> AppResult<AuditLogListResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;

    let limit = query.limit.unwrap_or(100).clamp(1, 200);
    let (cursor_created_at, cursor_id) = decode_cursor(query.cursor.as_deref())?;
    let actor_filter = parse_uuid_filter(query.actor_user_id, "actorUserId")?;
    let target_entity_id = parse_uuid_filter(query.target_entity_id, "targetEntityId")?;

    let rows = sqlx::query(
        r#"
        select
          id,
          workspace_id,
          actor_user_id,
          action_type,
          target_entity_type,
          target_entity_id,
          request_id,
          metadata_jsonb,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at
        from audit_log
        where workspace_id = $1
          and ($2::timestamptz is null or (created_at, id) < ($2::timestamptz, $3::uuid))
          and ($4::text is null or action_type = $4)
          and ($5::uuid is null or actor_user_id = $5)
          and ($6::text is null or target_entity_type = $6)
          and ($7::uuid is null or target_entity_id = $7)
        order by created_at desc, id desc
        limit $8
        "#,
    )
    .bind(workspace_id)
    .bind(cursor_created_at)
    .bind(cursor_id)
    .bind(query.action_type)
    .bind(actor_filter)
    .bind(query.target_entity_type)
    .bind(target_entity_id)
    .bind(limit + 1)
    .fetch_all(pool)
    .await?;

    let mut items = rows
        .iter()
        .map(map_audit_entry)
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

    Ok(AuditLogListResponse { items, next_cursor })
}
