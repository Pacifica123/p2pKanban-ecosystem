use p2p_kanban_sync_core::{ServerChangeEvent, SyncEnvelope};
use serde_json::Value;
use sqlx::{PgPool, Postgres, Row, Transaction};
use uuid::Uuid;

use crate::{error::AppResult, modules::sync::dto::TransportQueueCount};

#[derive(Debug)]
pub struct ClaimedMirrorEvent {
    pub outbox_id: Uuid,
    pub envelope: SyncEnvelope,
}

pub async fn ensure_nostr_outbox(pool: &PgPool, change_event_id: Uuid) -> AppResult<()> {
    sqlx::query(
        r#"
        insert into sync_transport_outbox (
          id, change_event_id, workspace_id, transport, status
        )
        select $1, id, workspace_id, 'nostr', 'pending'
        from change_events
        where id = $2 and workspace_id is not null
        on conflict (change_event_id, transport) do nothing
        "#,
    )
    .bind(Uuid::now_v7())
    .bind(change_event_id)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn enqueue_nostr_backfill(pool: &PgPool) -> AppResult<u64> {
    let result = sqlx::query(
        r#"
        insert into sync_transport_outbox (
          id, change_event_id, workspace_id, transport, status
        )
        select gen_random_uuid(), id, workspace_id, 'nostr', 'pending'
        from change_events
        where workspace_id is not null
        on conflict (change_event_id, transport) do nothing
        "#,
    )
    .execute(pool)
    .await?;
    Ok(result.rows_affected())
}

pub async fn claim_nostr_batch(
    pool: &PgPool,
    limit: i64,
    max_attempts: i32,
) -> AppResult<Vec<ClaimedMirrorEvent>> {
    let mut tx = pool.begin().await?;
    release_expired_leases(&mut tx).await?;

    let claimed = sqlx::query(
        r#"
        with candidates as (
          select id
          from sync_transport_outbox
          where transport = 'nostr'
            and status in ('pending', 'retry')
            and next_attempt_at <= now()
            and attempt_count < $1
          order by created_at asc
          for update skip locked
          limit $2
        )
        update sync_transport_outbox outbox
        set
          status = 'processing',
          attempt_count = attempt_count + 1,
          lease_until = now() + interval '60 seconds',
          updated_at = now()
        from candidates
        where outbox.id = candidates.id
        returning outbox.id, outbox.change_event_id, outbox.workspace_id
        "#,
    )
    .bind(max_attempts)
    .bind(limit)
    .fetch_all(&mut *tx)
    .await?;

    let mut events = Vec::with_capacity(claimed.len());
    for row in claimed {
        let outbox_id: Uuid = row.try_get("id")?;
        let change_event_id: Uuid = row.try_get("change_event_id")?;
        let workspace_id: Uuid = row.try_get("workspace_id")?;
        if let Some(envelope) =
            load_envelope(&mut tx, outbox_id, change_event_id, workspace_id).await?
        {
            events.push(envelope);
        }
    }
    tx.commit().await?;
    Ok(events)
}

async fn release_expired_leases(tx: &mut Transaction<'_, Postgres>) -> AppResult<()> {
    sqlx::query(
        r#"
        update sync_transport_outbox
        set
          status = 'retry',
          lease_until = null,
          next_attempt_at = now(),
          last_error = coalesce(last_error, 'worker lease expired'),
          updated_at = now()
        where status = 'processing'
          and lease_until < now()
        "#,
    )
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn load_envelope(
    tx: &mut Transaction<'_, Postgres>,
    outbox_id: Uuid,
    change_event_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<Option<ClaimedMirrorEvent>> {
    let row = sqlx::query(
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
        where id = $1
        "#,
    )
    .bind(change_event_id)
    .fetch_optional(&mut **tx)
    .await?;

    let Some(row) = row else {
        return Ok(None);
    };
    let accepted_at: String = row.try_get("accepted_at")?;
    let event = ServerChangeEvent {
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
        accepted_at: accepted_at.clone(),
        actor_user_id: row
            .try_get::<Option<Uuid>, _>("actor_user_id")?
            .map(|id| id.to_string()),
        actor_device_id: row
            .try_get::<Option<Uuid>, _>("device_id")?
            .map(|id| id.to_string()),
    };
    let mut envelope = SyncEnvelope::new(workspace_id.to_string(), event);
    envelope.emitted_at = accepted_at;
    Ok(Some(ClaimedMirrorEvent {
        outbox_id,
        envelope,
    }))
}

pub async fn mark_delivered(
    pool: &PgPool,
    outbox_id: Uuid,
    remote_event_id: &str,
) -> AppResult<()> {
    sqlx::query(
        r#"
        update sync_transport_outbox
        set
          status = 'delivered',
          lease_until = null,
          remote_event_id = $2,
          last_error = null,
          delivered_at = now(),
          updated_at = now()
        where id = $1
        "#,
    )
    .bind(outbox_id)
    .bind(remote_event_id)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn mark_failed(
    pool: &PgPool,
    outbox_id: Uuid,
    error: &str,
    max_attempts: i32,
) -> AppResult<()> {
    sqlx::query(
        r#"
        update sync_transport_outbox
        set
          status = case when attempt_count >= $3 then 'dead_letter' else 'retry' end,
          lease_until = null,
          next_attempt_at = now() + make_interval(
            secs => least(3600, (power(2, least(attempt_count, 10))::integer * 5))
          ),
          last_error = left($2, 2000),
          updated_at = now()
        where id = $1
        "#,
    )
    .bind(outbox_id)
    .bind(error)
    .bind(max_attempts)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn transport_queue_status(pool: &PgPool) -> AppResult<Vec<TransportQueueCount>> {
    let rows = sqlx::query(
        r#"
        select transport, status, count(*)::bigint as count
        from sync_transport_outbox
        group by transport, status
        order by transport, status
        "#,
    )
    .fetch_all(pool)
    .await?;
    rows.into_iter()
        .map(|row| {
            Ok(TransportQueueCount {
                transport: row.try_get("transport")?,
                status: row.try_get("status")?,
                count: row.try_get("count")?,
            })
        })
        .collect()
}
