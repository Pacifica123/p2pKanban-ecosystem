use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::common::{require_workspace_access, require_workspace_write, AuthContext},
};

use super::dto::{
    ClientChangeEvent, PullChangesResponse, PushChangesResponse, PushEventResult,
    RegisterReplicaRequest, RegisterReplicaResponse, ReplicaListResponse, ReplicaResponse,
    ServerChangeEvent, SyncCursorResponse, SyncScopeResponse, SyncStatusResponse,
};

fn timestamp_sql(alias: &str, column: &str) -> String {
    format!(
        r#"case when {column} is null then null else to_char({column} at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as {alias}"#,
    )
}

fn map_replica(row: &sqlx::postgres::PgRow) -> AppResult<ReplicaResponse> {
    let revoked_at: Option<String> = row.try_get("revoked_at")?;
    Ok(ReplicaResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        replica_key: row.try_get("client_instance_key")?,
        kind: row.try_get("replica_kind")?,
        status: if revoked_at.is_some() {
            "disabled"
        } else {
            "active"
        }
        .to_string(),
        user_id: row
            .try_get::<Option<Uuid>, _>("user_id")?
            .map(|id| id.to_string()),
        device_id: row
            .try_get::<Option<Uuid>, _>("device_id")?
            .map(|id| id.to_string()),
        display_name: row.try_get("display_name")?,
        platform: row.try_get("platform")?,
        protocol_version: row.try_get("protocol_version")?,
        app_version: row.try_get("app_version")?,
        last_seen_at: row.try_get("last_seen_at")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

fn map_server_event(row: &sqlx::postgres::PgRow) -> AppResult<ServerChangeEvent> {
    Ok(ServerChangeEvent {
        event_id: row.try_get::<Uuid, _>("id")?.to_string(),
        replica_id: row.try_get::<Uuid, _>("replica_id")?.to_string(),
        replica_seq: row.try_get("replica_seq")?,
        entity_type: row.try_get("entity_type")?,
        entity_id: row.try_get::<Uuid, _>("entity_id")?.to_string(),
        operation: row.try_get("operation")?,
        field_mask: row.try_get::<Vec<String>, _>("field_mask")?,
        logical_clock: row.try_get("lamport")?,
        base_server_order: row.try_get("base_server_order")?,
        payload: row.try_get::<Value, _>("payload_jsonb")?,
        metadata: row.try_get::<Value, _>("metadata_jsonb")?,
        server_order: row.try_get("server_order")?,
        accepted_at: row.try_get("accepted_at")?,
        actor_user_id: row
            .try_get::<Option<Uuid>, _>("actor_user_id")?
            .map(|id| id.to_string()),
        actor_device_id: row
            .try_get::<Option<Uuid>, _>("device_id")?
            .map(|id| id.to_string()),
    })
}

fn sensitive_json_key(key: &str) -> bool {
    let normalized = key
        .chars()
        .filter(|ch| *ch != '_' && *ch != '-')
        .collect::<String>()
        .to_ascii_lowercase();

    matches!(
        normalized.as_str(),
        "password"
            | "passwordhash"
            | "refreshtoken"
            | "accesstoken"
            | "authorization"
            | "cookie"
            | "secret"
            | "token"
            | "jwt"
            | "apikey"
    )
}

fn truncate_string(value: &str) -> Value {
    if value.len() > 512 {
        Value::String(format!("{}…", &value[..512]))
    } else {
        Value::String(value.to_string())
    }
}

fn sanitize_json_value(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut sanitized = serde_json::Map::new();
            for (key, inner) in map {
                sanitized.insert(
                    key.clone(),
                    if sensitive_json_key(key) {
                        Value::String("[redacted]".to_string())
                    } else {
                        sanitize_json_value(inner)
                    },
                );
            }
            Value::Object(sanitized)
        }
        Value::Array(items) => Value::Array(items.iter().map(sanitize_json_value).collect()),
        Value::String(value) => truncate_string(value),
        _ => value.clone(),
    }
}

fn replica_select_sql(extra_where: &str, order_by: &str) -> String {
    format!(
        r#"
        select
          id,
          user_id,
          device_id,
          replica_kind,
          client_instance_key,
          display_name,
          platform,
          protocol_version,
          app_version,
          {last_seen_at},
          {created_at},
          {updated_at},
          {revoked_at}
        from replicas
        {extra_where}
        {order_by}
        "#,
        last_seen_at = timestamp_sql("last_seen_at", "last_seen_at"),
        created_at = timestamp_sql("created_at", "created_at"),
        updated_at = timestamp_sql("updated_at", "coalesce(last_seen_at, created_at)"),
        revoked_at = timestamp_sql("revoked_at", "revoked_at"),
    )
}

async fn fetch_replica_for_user(
    pool: &PgPool,
    replica_id: Uuid,
    auth: &AuthContext,
) -> AppResult<ReplicaResponse> {
    let sql = replica_select_sql("where id = $1", "");
    let row = sqlx::query(&sql)
        .bind(replica_id)
        .fetch_optional(pool)
        .await?
        .ok_or_else(|| AppError::not_found("Replica not found"))?;

    let replica = map_replica(&row)?;
    if replica.user_id.as_deref() != Some(&auth.user_id.to_string()) {
        return Err(AppError::forbidden(
            "Replica does not belong to current user",
        ));
    }
    if replica.status != "active" {
        return Err(AppError::forbidden("Replica is disabled"));
    }
    if auth.device_id != Uuid::nil()
        && replica.device_id.as_deref() != Some(&auth.device_id.to_string())
    {
        return Err(AppError::forbidden(
            "Replica is not bound to current device",
        ));
    }
    Ok(replica)
}

pub async fn get_status(
    pool: &PgPool,
    auth: AuthContext,
    replica_id: Option<Uuid>,
) -> AppResult<SyncStatusResponse> {
    let replica = match replica_id {
        Some(replica_id) => Some(fetch_replica_for_user(pool, replica_id, &auth).await?),
        None => None,
    };

    let row = sqlx::query(
        r#"
        select
          to_char(now() at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as server_time,
          coalesce(max(server_order), 0)::bigint as max_server_order
        from change_events
        "#,
    )
    .fetch_one(pool)
    .await?;

    Ok(SyncStatusResponse {
        healthy: true,
        mode: auth.mode.to_string(),
        server_time: row.try_get("server_time")?,
        max_server_order: Some(row.try_get("max_server_order")?),
        replica,
    })
}

pub async fn list_replicas(pool: &PgPool, auth: AuthContext) -> AppResult<ReplicaListResponse> {
    let sql = replica_select_sql(
        "where user_id = $1",
        "order by coalesce(last_seen_at, created_at) desc",
    );
    let rows = sqlx::query(&sql).bind(auth.user_id).fetch_all(pool).await?;
    let items = rows
        .iter()
        .map(map_replica)
        .collect::<AppResult<Vec<_>>>()?;
    Ok(ReplicaListResponse { items })
}

pub async fn register_replica(
    pool: &PgPool,
    auth: AuthContext,
    payload: RegisterReplicaRequest,
    kind: String,
) -> AppResult<RegisterReplicaResponse> {
    let existing = sqlx::query(
        r#"
        select id
        from replicas
        where user_id = $1
          and client_instance_key = $2
          and (($3::uuid is null and device_id is null) or device_id = $3)
          and revoked_at is null
        order by created_at desc
        limit 1
        "#,
    )
    .bind(auth.user_id)
    .bind(&payload.replica_key)
    .bind(if auth.device_id == Uuid::nil() {
        None
    } else {
        Some(auth.device_id)
    })
    .fetch_optional(pool)
    .await?;

    let replica_id = existing
        .map(|row| row.try_get::<Uuid, _>("id"))
        .transpose()?
        .unwrap_or_else(Uuid::now_v7);

    let row = sqlx::query(
        r#"
        insert into replicas (
          id,
          user_id,
          device_id,
          replica_kind,
          client_instance_key,
          display_name,
          platform,
          protocol_version,
          app_version,
          last_seen_at
        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
        on conflict (id) do update set
          replica_kind = excluded.replica_kind,
          display_name = excluded.display_name,
          platform = excluded.platform,
          protocol_version = excluded.protocol_version,
          app_version = excluded.app_version,
          last_seen_at = now(),
          revoked_at = null
        returning
          id,
          user_id,
          device_id,
          replica_kind,
          client_instance_key,
          display_name,
          platform,
          protocol_version,
          app_version,
          case when last_seen_at is null then null else to_char(last_seen_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as last_seen_at,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(coalesce(last_seen_at, created_at) at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when revoked_at is null then null else to_char(revoked_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as revoked_at
        "#,
    )
    .bind(replica_id)
    .bind(auth.user_id)
    .bind(if auth.device_id == Uuid::nil() { None } else { Some(auth.device_id) })
    .bind(kind)
    .bind(payload.replica_key)
    .bind(payload.display_name)
    .bind(payload.platform)
    .bind(payload.protocol_version)
    .bind(payload.app_version)
    .fetch_one(pool)
    .await?;

    Ok(RegisterReplicaResponse {
        replica: map_replica(&row)?,
    })
}

async fn duplicate_result(
    pool: &PgPool,
    event_id: Uuid,
    replica_id: Uuid,
    replica_seq: i64,
) -> AppResult<Option<PushEventResult>> {
    let row = sqlx::query(
        r#"
        select id, replica_seq, server_order
        from change_events
        where (id = $1 and replica_id = $2) or (replica_id = $2 and replica_seq = $3)
        order by case when id = $1 then 0 else 1 end
        limit 1
        "#,
    )
    .bind(event_id)
    .bind(replica_id)
    .bind(replica_seq)
    .fetch_optional(pool)
    .await?;

    Ok(row.map(|row| PushEventResult {
        event_id: row
            .try_get::<Uuid, _>("id")
            .map(|id| id.to_string())
            .unwrap_or_else(|_| event_id.to_string()),
        replica_seq: row.try_get("replica_seq").unwrap_or(replica_seq),
        status: "duplicate".to_string(),
        server_order: row.try_get("server_order").ok(),
        error: None,
    }))
}

fn metadata_with_source(event: &ClientChangeEvent, auth: &AuthContext) -> Value {
    let mut metadata = if event.metadata.is_object() {
        event.metadata.clone()
    } else {
        json!({})
    };

    if let Some(map) = metadata.as_object_mut() {
        map.insert("syncBaseline".to_string(), json!(true));
        map.insert("authMode".to_string(), json!(auth.mode));
        map.insert("clientOperation".to_string(), json!(event.operation));
    }

    metadata
}

fn normalize_operation(operation: &str) -> &'static str {
    match operation {
        "move" | "complete" => "update",
        "create" => "create",
        "delete" => "delete",
        "restore" => "restore",
        "reorder" => "reorder",
        "add" => "add",
        "remove" => "remove",
        "archive" => "archive",
        "unarchive" => "unarchive",
        _ => "update",
    }
}

fn is_tombstone_operation(operation: &str) -> bool {
    matches!(operation, "delete" | "archive")
}

fn is_core_entity(entity_type: &str) -> bool {
    matches!(entity_type, "workspace" | "board" | "column" | "card")
}

async fn record_tombstone_if_needed(
    pool: &PgPool,
    workspace_id: Option<Uuid>,
    event_id: Uuid,
    replica_id: Uuid,
    auth: &AuthContext,
    event: &ClientChangeEvent,
) -> AppResult<()> {
    let operation = normalize_operation(&event.operation);
    if !is_tombstone_operation(operation) || !is_core_entity(&event.entity_type) {
        return Ok(());
    }

    let entity_id = Uuid::parse_str(&event.entity_id)
        .map_err(|_| AppError::bad_request("entityId must be a valid UUID"))?;
    sqlx::query(
        r#"
        insert into tombstones (
          id,
          workspace_id,
          entity_type,
          entity_id,
          delete_event_id,
          deleted_by_user_id,
          deleted_by_replica_id,
          deleted_at,
          metadata_jsonb
        ) values ($1, $2, $3, $4, $5, $6, $7, now(), $8)
        on conflict (entity_type, entity_id) do update set
          workspace_id = excluded.workspace_id,
          delete_event_id = excluded.delete_event_id,
          deleted_by_user_id = excluded.deleted_by_user_id,
          deleted_by_replica_id = excluded.deleted_by_replica_id,
          deleted_at = excluded.deleted_at,
          metadata_jsonb = excluded.metadata_jsonb
        "#,
    )
    .bind(Uuid::now_v7())
    .bind(workspace_id)
    .bind(&event.entity_type)
    .bind(entity_id)
    .bind(event_id)
    .bind(auth.user_id)
    .bind(replica_id)
    .bind(json!({ "operation": operation, "syncBaseline": true }))
    .execute(pool)
    .await?;

    Ok(())
}

pub async fn push_changes(
    pool: &PgPool,
    auth: AuthContext,
    replica_id: Uuid,
    workspace_id: Option<Uuid>,
    events: Vec<ClientChangeEvent>,
    mirror_to_nostr: bool,
) -> AppResult<PushChangesResponse> {
    let _replica = fetch_replica_for_user(pool, replica_id, &auth).await?;
    if let Some(workspace_id) = workspace_id {
        require_workspace_write(pool, workspace_id, auth.user_id).await?;
    }

    sqlx::query("update replicas set last_seen_at = now() where id = $1")
        .bind(replica_id)
        .execute(pool)
        .await?;

    let mut results = Vec::with_capacity(events.len());

    for event in events {
        let event_id = Uuid::parse_str(&event.event_id)
            .map_err(|_| AppError::bad_request("eventId must be a valid UUID"))?;
        let entity_id = Uuid::parse_str(&event.entity_id)
            .map_err(|_| AppError::bad_request("entityId must be a valid UUID"))?;

        if let Some(result) =
            duplicate_result(pool, event_id, replica_id, event.replica_seq).await?
        {
            if mirror_to_nostr {
                let stored_event_id =
                    Uuid::parse_str(&result.event_id).map_err(|_| AppError::internal())?;
                crate::transports::repo::ensure_nostr_outbox(pool, stored_event_id).await?;
            }
            results.push(result);
            continue;
        }

        let max_seq = sqlx::query_scalar::<_, Option<i64>>(
            "select max(replica_seq) from change_events where replica_id = $1",
        )
        .bind(replica_id)
        .fetch_one(pool)
        .await?
        .unwrap_or(0);

        if event.replica_seq <= max_seq {
            results.push(PushEventResult {
                event_id: event.event_id.clone(),
                replica_seq: event.replica_seq,
                status: "rejected".to_string(),
                server_order: None,
                error: Some(format!(
                    "replicaSeq must be greater than current max {max_seq}"
                )),
            });
            continue;
        }

        let field_mask = event.field_mask.clone().unwrap_or_default();
        let operation = normalize_operation(&event.operation);
        let metadata = sanitize_json_value(&metadata_with_source(&event, &auth));
        let occurred_at = event.occurred_at.clone();

        let inserted = sqlx::query(
            r#"
            insert into change_events (
              id,
              workspace_id,
              replica_id,
              device_id,
              actor_user_id,
              entity_type,
              entity_id,
              operation,
              field_mask,
              payload_jsonb,
              metadata_jsonb,
              lamport,
              replica_seq,
              base_server_order,
              occurred_at,
              applied_at,
              status
            ) values (
              $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
              case when $15::text is null then null else $15::timestamptz end,
              now(),
              'applied'
            )
            returning server_order
            "#,
        )
        .bind(event_id)
        .bind(workspace_id)
        .bind(replica_id)
        .bind(if auth.device_id == Uuid::nil() {
            None
        } else {
            Some(auth.device_id)
        })
        .bind(auth.user_id)
        .bind(&event.entity_type)
        .bind(entity_id)
        .bind(operation)
        .bind(&field_mask)
        .bind(sanitize_json_value(&event.payload))
        .bind(metadata)
        .bind(event.logical_clock)
        .bind(event.replica_seq)
        .bind(event.base_server_order)
        .bind(occurred_at)
        .fetch_one(pool)
        .await;

        match inserted {
            Ok(row) => {
                record_tombstone_if_needed(pool, workspace_id, event_id, replica_id, &auth, &event)
                    .await?;
                if mirror_to_nostr {
                    crate::transports::repo::ensure_nostr_outbox(pool, event_id).await?;
                }
                results.push(PushEventResult {
                    event_id: event.event_id,
                    replica_seq: event.replica_seq,
                    status: "accepted".to_string(),
                    server_order: row.try_get("server_order").ok(),
                    error: None,
                });
            }
            Err(sqlx::Error::Database(db_error))
                if matches!(db_error.kind(), sqlx::error::ErrorKind::UniqueViolation) =>
            {
                if let Some(result) =
                    duplicate_result(pool, event_id, replica_id, event.replica_seq).await?
                {
                    if mirror_to_nostr {
                        let stored_event_id =
                            Uuid::parse_str(&result.event_id).map_err(|_| AppError::internal())?;
                        crate::transports::repo::ensure_nostr_outbox(pool, stored_event_id).await?;
                    }
                    results.push(result);
                } else {
                    results.push(PushEventResult {
                        event_id: event.event_id,
                        replica_seq: event.replica_seq,
                        status: "duplicate".to_string(),
                        server_order: None,
                        error: None,
                    });
                }
            }
            Err(error) => return Err(error.into()),
        }
    }

    Ok(PushChangesResponse { results })
}

pub async fn pull_changes(
    pool: &PgPool,
    auth: AuthContext,
    replica_id: Uuid,
    scope: String,
    workspace_id: Option<Uuid>,
    last_server_order: i64,
    limit: i64,
) -> AppResult<PullChangesResponse> {
    let _replica = fetch_replica_for_user(pool, replica_id, &auth).await?;
    if let Some(workspace_id) = workspace_id {
        require_workspace_access(pool, workspace_id, auth.user_id).await?;
    }

    let rows = sqlx::query(
        r#"
        select
          id,
          replica_id,
          replica_seq,
          entity_type,
          entity_id,
          operation,
          field_mask,
          lamport,
          base_server_order,
          payload_jsonb,
          metadata_jsonb,
          server_order,
          to_char(coalesce(applied_at, received_at) at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as accepted_at,
          actor_user_id,
          device_id
        from change_events
        where server_order > $1
          and ($2::text = 'global' or workspace_id = $3)
          and (
            workspace_id is null
            or exists (
              select 1
              from workspaces w
              left join workspace_members wm
                on wm.workspace_id = w.id
               and wm.user_id = $4
               and wm.deactivated_at is null
               and wm.deleted_at is null
              where w.id = change_events.workspace_id
                and w.deleted_at is null
                and (w.owner_user_id = $4 or wm.user_id is not null or w.visibility = 'public_readonly')
            )
          )
        order by server_order asc
        limit $5
        "#,
    )
    .bind(last_server_order)
    .bind(&scope)
    .bind(workspace_id)
    .bind(auth.user_id)
    .bind(limit + 1)
    .fetch_all(pool)
    .await?;

    let has_more = rows.len() as i64 > limit;
    let events = rows
        .iter()
        .take(limit as usize)
        .map(map_server_event)
        .collect::<AppResult<Vec<_>>>()?;
    let next_order = events
        .last()
        .map(|event| event.server_order)
        .unwrap_or(last_server_order);

    let scope_id = if scope == "workspace" {
        workspace_id
    } else {
        None
    };

    if scope == "global" {
        sqlx::query(
            r#"
            insert into sync_cursors (id, replica_id, cursor_scope, scope_id, last_server_order, last_event_received_at, updated_at)
            values ($1, $2, 'global', null, $3, now(), now())
            on conflict (replica_id, cursor_scope) where cursor_scope = 'global' and scope_id is null
            do update set
              last_server_order = greatest(sync_cursors.last_server_order, excluded.last_server_order),
              last_event_received_at = excluded.last_event_received_at,
              updated_at = now()
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(replica_id)
        .bind(next_order)
        .execute(pool)
        .await
        .ok();
    }

    if scope == "workspace" {
        sqlx::query(
            r#"
            insert into sync_cursors (id, replica_id, cursor_scope, scope_id, last_server_order, last_event_received_at, updated_at)
            values ($1, $2, 'workspace', $3, $4, now(), now())
            on conflict (replica_id, cursor_scope, scope_id) where cursor_scope = 'workspace' and scope_id is not null
            do update set
              last_server_order = greatest(sync_cursors.last_server_order, excluded.last_server_order),
              last_event_received_at = excluded.last_event_received_at,
              updated_at = now()
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(replica_id)
        .bind(scope_id)
        .bind(next_order)
        .execute(pool)
        .await
        .ok();
    }

    Ok(PullChangesResponse {
        events,
        next_cursor: SyncCursorResponse {
            scope: SyncScopeResponse {
                scope,
                workspace_id: workspace_id.map(|id| id.to_string()),
            },
            replica_id: replica_id.to_string(),
            last_server_order: next_order,
        },
        has_more,
    })
}
