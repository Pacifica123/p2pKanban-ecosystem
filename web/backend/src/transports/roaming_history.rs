use p2p_kanban_nostr_transport::{
    NostrTransport, RecoveredRoamingEvent, RoamingBoardEvent, ROAMING_PROTOCOL_VERSION,
};
use serde_json::{json, Value};
use sqlx::{PgPool, Row};
use uuid::Uuid;

// Freeze an activity once per node/epoch, including retained common history.
// Canonical activity ids deduplicate peer copies and transport retries.
pub(super) async fn publish(pool: &PgPool, transport: &NostrTransport, limit: i64) {
    let result: anyhow::Result<()> = async {
        let rows = sqlx::query(r#"
          select ae.*,u.display_name,n.replica_id,w.access_epoch,
            to_char(ae.created_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') occurred_at,
            coalesce((select event_json->>'eventId' from roaming_board_outbox o where o.source_activity_id=ae.id),
              (select event_json->>'eventId' from roaming_board_settings_outbox o where o.source_activity_id=ae.id),ae.payload_jsonb->>'eventId') mutation_id,
            (select chain_json from roaming_device_grants g where g.board_id=ae.board_id and g.epoch=w.access_epoch) delegation
          from activity_entries ae join boards b on b.id=ae.board_id join workspaces w on w.id=ae.workspace_id
          left join users u on u.id=ae.actor_user_id cross join local_node_identity n
          where b.deleted_at is null and w.deleted_at is null
            and (coalesce(ae.payload_jsonb->>'source','') <> 'roaming' or ae.payload_jsonb->>'commonHistory'='true')
            and not exists(select 1 from roaming_activity_outbox o where o.activity_id=ae.id and o.capability_epoch=w.access_epoch)
          order by ae.created_at,ae.id limit $1
        "#).bind(limit.clamp(1,500)).fetch_all(pool).await?;
        for row in rows {
            let id: Uuid = row.try_get("id")?;
            let board: Uuid = row.try_get("board_id")?;
            let mut payload = json!({"activity":{
                "id":id,"boardId":board,"cardId":row.try_get::<Option<Uuid>,_>("card_id")?,
                "kind":row.try_get::<String,_>("kind")?,"createdAt":row.try_get::<String,_>("occurred_at")?,
                "entityType":row.try_get::<String,_>("entity_type")?,"entityId":row.try_get::<Uuid,_>("entity_id")?,
                "actor":{"userId":row.try_get::<Option<Uuid>,_>("actor_user_id")?,"displayName":row.try_get::<Option<String>,_>("display_name")?},
                "fieldMask":row.try_get::<Vec<String>,_>("field_mask")?
            },"mutationEventId":row.try_get::<Option<String>,_>("mutation_id")?});
            if let Some(chain) = row.try_get::<Option<Value>,_>("delegation")? { payload["_deviceDelegation"] = chain; }
            let event = RoamingBoardEvent {protocol_version:ROAMING_PROTOCOL_VERSION.into(),event_id:Uuid::now_v7().to_string(),
                workspace_id:row.try_get::<Uuid,_>("workspace_id")?.to_string(),board_id:board.to_string(),
                capability_epoch:row.try_get("access_epoch")?,replica_id:row.try_get::<Uuid,_>("replica_id")?.to_string(),
                replica_seq:1,logical_clock:1,entity_type:"board".into(),entity_id:board.to_string(),
                operation:"board.activity".into(),field_mask:vec![],payload,occurred_at:row.try_get("occurred_at")?};
            sqlx::query("insert into roaming_activity_outbox(activity_id,capability_epoch,event_json) values($1,$2,$3) on conflict do nothing")
                .bind(id).bind(event.capability_epoch).bind(serde_json::to_value(event)?).execute(pool).await?;
        }
        let rows = sqlx::query(r#"select o.activity_id,o.event_json,c.board_key_base64 from roaming_activity_outbox o
          join activity_entries ae on ae.id=o.activity_id join workspaces w on w.id=ae.workspace_id
          join roaming_board_capabilities c on c.board_id=ae.board_id and c.capability_epoch=w.access_epoch
          where not o.delivered and o.capability_epoch=w.access_epoch and o.next_attempt_at<=now() and (o.event_json->>'capabilityEpoch')::bigint=w.access_epoch
          order by ae.created_at,ae.id limit $1"#).bind(limit.clamp(1,500)).fetch_all(pool).await?;
        for row in rows {
            let id:Uuid=row.try_get("activity_id")?;
            let event:RoamingBoardEvent=serde_json::from_value(row.try_get("event_json")?)?;
            let key:String=row.try_get("board_key_base64")?;
            match transport.publish_roaming_with_board_key(&event,&key).await {
                Ok(_) => {sqlx::query("update roaming_activity_outbox set delivered=true where activity_id=$1 and capability_epoch=$2").bind(id).bind(event.capability_epoch).execute(pool).await?;},
                Err(_) => {sqlx::query("update roaming_activity_outbox set next_attempt_at=now()+interval '10 seconds' where activity_id=$1 and capability_epoch=$2").bind(id).bind(event.capability_epoch).execute(pool).await?;}
            }
        }
        Ok(())
    }.await;
    if let Err(error) = result {
        tracing::warn!(%error,"shared history delivery remains pending");
    }
}

pub(super) fn validate_activity(event: &RoamingBoardEvent) -> anyhow::Result<&Value> {
    let value = event
        .payload
        .get("activity")
        .ok_or_else(|| anyhow::anyhow!("activity is missing"))?;
    anyhow::ensure!(
        value["boardId"].as_str() == Some(event.board_id.as_str()),
        "activity board scope mismatch"
    );
    for field in ["id", "entityId"] {
        Uuid::parse_str(
            value[field]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("activity {field} is missing"))?,
        )?;
    }
    anyhow::ensure!(
        value["kind"]
            .as_str()
            .is_some_and(|v| !v.is_empty() && v.len() < 100),
        "invalid activity kind"
    );
    anyhow::ensure!(
        value["entityType"]
            .as_str()
            .is_some_and(|v| !v.is_empty() && v.len() < 100),
        "invalid activity entity type"
    );
    anyhow::ensure!(
        value["createdAt"].as_str().is_some(),
        "activity timestamp missing"
    );
    anyhow::ensure!(
        value["fieldMask"]
            .as_array()
            .is_some_and(|v| v.len() < 100 && v.iter().all(Value::is_string)),
        "invalid activity fields"
    );
    Ok(value)
}

pub(super) async fn ingest(
    pool: &PgPool,
    recovered: &RecoveredRoamingEvent,
    actor: Uuid,
) -> anyhow::Result<()> {
    let event = &recovered.event;
    let value = validate_activity(event)?;
    let board = Uuid::parse_str(&event.board_id)?;
    let workspace = Uuid::parse_str(&event.workspace_id)?;
    let id = Uuid::parse_str(value["id"].as_str().unwrap())?;
    let entity = Uuid::parse_str(value["entityId"].as_str().unwrap())?;
    let card = value["cardId"].as_str().map(Uuid::parse_str).transpose()?;
    let actor_id = if event.operation == "board.activity" {
        value["actor"]["userId"]
            .as_str()
            .map(Uuid::parse_str)
            .transpose()?
    } else {
        Some(actor)
    };
    let fields: Vec<String> = serde_json::from_value(value["fieldMask"].clone())?;
    let mutation = if event.operation == "board.activity" {
        event.payload["mutationEventId"].as_str()
    } else {
        Some(event.event_id.as_str())
    };
    let mut tx = pool.begin().await?;
    let collision=sqlx::query_scalar::<_,bool>("select exists(select 1 from activity_entries where id=$1 and (board_id<>$2 or workspace_id<>$3))")
      .bind(id).bind(board).bind(workspace).fetch_one(&mut *tx).await?;
    anyhow::ensure!(!collision, "activity id belongs to another board");
    if let Some(card) = card {
        let matches = sqlx::query_scalar::<_, bool>(
            "select exists(select 1 from cards where id=$1 and board_id=$2)",
        )
        .bind(card)
        .bind(board)
        .fetch_one(&mut *tx)
        .await?;
        // Dependencies may arrive in a later fetch. Do not permanently mark it.
        anyhow::ensure!(matches, "activity card is not installed yet");
    }
    if let Some(user) = actor_id {
        let known = sqlx::query_scalar::<_, bool>("select exists(select 1 from users where id=$1)")
            .bind(user)
            .fetch_one(&mut *tx)
            .await?;
        anyhow::ensure!(known, "activity actor is not installed yet");
    }
    if let Some(mutation) = mutation {
        sqlx::query("delete from activity_entries where board_id=$1 and payload_jsonb->>'source'='roaming' and payload_jsonb->>'eventId'=$2 and id<>$3")
          .bind(board).bind(mutation).bind(id).execute(&mut *tx).await?;
    }
    sqlx::query(r#"insert into activity_entries(id,workspace_id,board_id,card_id,actor_user_id,kind,entity_type,entity_id,field_mask,payload_jsonb,created_at)
      values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::timestamptz) on conflict(id) do nothing"#)
      .bind(id).bind(workspace).bind(board).bind(card).bind(actor_id).bind(value["kind"].as_str().unwrap())
      .bind(value["entityType"].as_str().unwrap()).bind(entity).bind(fields)
      .bind(json!({"source":"roaming","commonHistory":true,"eventId":mutation,"publisher":recovered.author_public_key}))
      .bind(value["createdAt"].as_str().unwrap()).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn event() -> RoamingBoardEvent {
        serde_json::from_value(json!({"protocolVersion":ROAMING_PROTOCOL_VERSION,
          "eventId":Uuid::nil(),"workspaceId":Uuid::nil(),"boardId":Uuid::nil(),"capabilityEpoch":1,
          "replicaId":Uuid::nil(),"replicaSeq":1,"logicalClock":1,"entityType":"board","entityId":Uuid::nil(),
          "operation":"board.activity","fieldMask":[],"occurredAt":"2026-10-01T00:00:00Z",
          "payload":{"activity":{"id":Uuid::nil(),"boardId":Uuid::nil(),"entityId":Uuid::nil(),
             "entityType":"comment","kind":"comment.created","createdAt":"2026-10-01T00:00:00Z","fieldMask":["body"]}}})).unwrap()
    }
    #[test]
    fn shared_history_scope_and_fields_are_validated() {
        let mut e = event();
        assert!(validate_activity(&e).is_ok());
        e.payload["activity"]["boardId"] = json!(Uuid::from_u128(4));
        assert!(validate_activity(&e).is_err());
        e = event();
        e.payload["activity"]["fieldMask"] = json!([{"secret":"invalid"}]);
        assert!(validate_activity(&e).is_err());
    }
}
