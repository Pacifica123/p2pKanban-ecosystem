use p2p_kanban_sync_core::validate_client_event;
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::common::{
        board_workspace_id, require_workspace_access, require_workspace_write,
        workspace_access_epoch, AuthContext,
    },
    state::AppState,
};

use super::dto::{
    ClientChangeEvent, CreateRoamingCapabilityRequest, PullChangesQuery, PullChangesResponse,
    PushChangesRequest, PushChangesResponse, RegisterReplicaRequest, RegisterReplicaResponse,
    ReplicaListResponse, RoamingCapabilityResponse, SyncStatusQuery, SyncStatusResponse,
    TransportAdapterStatus, TransportStatusResponse,
};

const MAX_PUSH_EVENTS: usize = 500;
const DEFAULT_PULL_LIMIT: i64 = 100;
const MAX_PULL_LIMIT: i64 = 1000;

pub async fn create_roaming_capability(
    state: &AppState,
    auth: AuthContext,
    payload: CreateRoamingCapabilityRequest,
) -> AppResult<RoamingCapabilityResponse> {
    #[cfg(not(feature = "nostr-shadow"))]
    {
        let _ = (state, auth, payload);
        return Err(AppError::conflict(
            "This backend build does not include independent board sync",
        ));
    }

    #[cfg(feature = "nostr-shadow")]
    {
        let nostr = &state.settings.transports.nostr;
        if !nostr.enabled {
            return Err(AppError::conflict(
                "Independent board sync is not enabled on this node",
            ));
        }

        let workspace_id = board_workspace_id(&state.db, payload.board_id).await?;
        let role = require_workspace_access(&state.db, workspace_id, auth.user_id)
            .await?
            .ok_or_else(|| AppError::forbidden("Workspace membership is required"))?;
        let can_write = matches!(role.as_str(), "owner" | "member");
        let author_public_key = payload.author_public_key.map(|value| value.trim().to_lowercase());
        if author_public_key.as_ref().is_some_and(|value| {
            value.len() != 64 || !value.chars().all(|character| character.is_ascii_hexdigit())
        }) {
            return Err(AppError::bad_request(
                "authorPublicKey must be a 64-character hexadecimal Nostr key",
            ));
        }
        if role == "guest" && author_public_key.is_none() {
            return Err(AppError::bad_request(
                "Guest roaming capability requires a bound device public key",
            ));
        }

        let access_epoch = workspace_access_epoch(&state.db, workspace_id).await?;
        let imported = sqlx::query_as::<_, (String, String, i64)>(
            r#"
            select board_tag, board_key_base64, capability_epoch
            from roaming_board_capabilities
            where board_id = $1
            "#,
        )
        .bind(payload.board_id)
        .fetch_optional(&state.db)
        .await?;
        let material = if let Some((board_tag, board_key, _capability_epoch)) = imported
            .filter(|(_, _, capability_epoch)| *capability_epoch == access_epoch)
        {
            let material =
                p2p_kanban_nostr_transport::NostrCodec::roaming_capability_from_board_key(
                    &payload.board_id.to_string(),
                    &board_key,
                )
                .map_err(|_| AppError::internal())?;
            if material.board_tag != board_tag {
                return Err(AppError::internal());
            }
            material
        } else {
            let material =
                p2p_kanban_nostr_transport::NostrCodec::random_roaming_capability(
                    &payload.board_id.to_string(),
                )
                .map_err(|_| AppError::internal())?;
            let stored = sqlx::query_as::<_, (String, String)>(
                r#"
                insert into roaming_board_capabilities (
                  board_id, board_tag, board_key_base64, source_kind, capability_epoch
                ) values ($1, $2, $3, 'linked_node', $4)
                on conflict (board_id) do update set
                  board_tag = case when roaming_board_capabilities.capability_epoch = excluded.capability_epoch then roaming_board_capabilities.board_tag else excluded.board_tag end,
                  board_key_base64 = case when roaming_board_capabilities.capability_epoch = excluded.capability_epoch then roaming_board_capabilities.board_key_base64 else excluded.board_key_base64 end,
                  capability_epoch = excluded.capability_epoch,
                  updated_at = now()
                returning board_tag, board_key_base64
                "#,
            )
            .bind(payload.board_id)
            .bind(&material.board_tag)
            .bind(&material.board_key)
            .bind(access_epoch)
            .fetch_one(&state.db)
            .await?;
            let winning = p2p_kanban_nostr_transport::NostrCodec::roaming_capability_from_board_key(&payload.board_id.to_string(), &stored.1).map_err(|_| AppError::internal())?;
            if winning.board_tag != stored.0 { return Err(AppError::internal()); }
            winning
        };

        if let Some(author_public_key) = &author_public_key {
            sqlx::query(
                r#"
                insert into roaming_board_authorizations (
                  id, workspace_id, board_id, user_id, device_id,
                  author_public_key, role, capability_epoch
                ) values ($1, $2, $3, $4, $5, $6, $7, $8)
                on conflict (board_id, author_public_key) where revoked_at is null
                do update set
                  user_id = excluded.user_id,
                  device_id = excluded.device_id,
                  role = excluded.role,
                  capability_epoch = excluded.capability_epoch
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(workspace_id)
            .bind(payload.board_id)
            .bind(auth.user_id)
            .bind((auth.device_id != Uuid::nil()).then_some(auth.device_id))
            .bind(author_public_key)
            .bind(&role)
            .bind(access_epoch)
            .execute(&state.db)
            .await?;
        }

        let mut writer_public_keys = sqlx::query_scalar::<_, String>(
            r#"
            select distinct a.author_public_key
            from roaming_board_authorizations a
            join workspaces w on w.id = a.workspace_id and w.deleted_at is null
            left join workspace_members wm
              on wm.workspace_id = a.workspace_id
             and wm.user_id = a.user_id
             and wm.deactivated_at is null
             and wm.deleted_at is null
            where a.board_id = $1
              and a.capability_epoch = $2
              and a.revoked_at is null
              and a.role in ('owner', 'member')
              and (w.owner_user_id = a.user_id or wm.role = 'member')
            order by a.author_public_key
            "#,
        )
        .bind(payload.board_id)
        .bind(access_epoch)
        .fetch_all(&state.db)
        .await?;
        writer_public_keys.push(p2p_kanban_nostr_transport::device_link::public_key(nostr.secret_key.as_deref().ok_or_else(AppError::internal)?).map_err(|_|AppError::internal())?);
        writer_public_keys.sort();
        writer_public_keys.dedup();
        let provisioned_at = sqlx::query_scalar::<_, String>(
            r#"select to_char(now() at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')"#,
        )
        .fetch_one(&state.db)
        .await?;

        let mut delegation_roots=sqlx::query_scalar::<_,String>("select distinct author_public_key from roaming_board_authorizations where board_id=$1 and role='owner' and capability_epoch=$2 and revoked_at is null union select root_key from roaming_device_grants where board_id=$1 and epoch=$2").bind(payload.board_id).bind(access_epoch).fetch_all(&state.db).await?;
        delegation_roots.push(p2p_kanban_nostr_transport::device_link::public_key(nostr.secret_key.as_deref().ok_or_else(AppError::internal)?).map_err(|_|AppError::internal())?);
        delegation_roots.sort();delegation_roots.dedup();
        let delegation_chain=if role=="owner"{if let Some(author)=&author_public_key{crate::auth::device_link::issue_chain(state,payload.board_id,auth.user_id,author).await?}else{vec![]}}else{vec![]};
        Ok(RoamingCapabilityResponse {
            format_version: 1,
            protocol_version: material.protocol_version,
            workspace_id: workspace_id.to_string(),
            board_id: payload.board_id.to_string(),
            board_tag: material.board_tag,
            board_key: material.board_key,
            capability_epoch: access_epoch,
            can_write,
            writer_public_keys,delegation_roots,delegation_chain,
            relays: nostr.relays.clone(),
            event_kind: nostr
                .event_kind
                .saturating_add(p2p_kanban_nostr_transport::ROAMING_EVENT_KIND_OFFSET),
            minimum_relay_acks: nostr.min_relay_acks,
            provisioned_at,
        })
    }
}

fn parse_uuid(value: &str, field: &str) -> AppResult<Uuid> {
    Uuid::parse_str(value)
        .map_err(|_| AppError::bad_request(format!("{field} must be a valid UUID")))
}

fn normalize_scope(scope: Option<String>) -> AppResult<String> {
    let scope = scope.unwrap_or_else(|| "global".to_string());
    match scope.as_str() {
        "global" | "workspace" => Ok(scope),
        _ => Err(AppError::bad_request("Unsupported sync scope")),
    }
}

fn normalize_replica_kind(kind: Option<String>) -> AppResult<String> {
    let kind = kind.unwrap_or_else(|| "browser_profile".to_string());
    match kind.as_str() {
        "device" | "browser_profile" | "client" => Ok("client".to_string()),
        "import_worker" | "import" => Ok("import".to_string()),
        "server" => Ok("server".to_string()),
        _ => Err(AppError::bad_request("Unsupported replica kind")),
    }
}

fn requires_workspace_scope(entity_type: &str) -> bool {
    !matches!(entity_type, "workspace")
}

fn validate_workspace_scoping(
    workspace_id: Option<Uuid>,
    event: &ClientChangeEvent,
) -> AppResult<()> {
    if workspace_id.is_none() && requires_workspace_scope(&event.entity_type) {
        return Err(AppError::bad_request(
            "workspaceId is required for workspace-scoped sync events",
        ));
    }

    if let Some(workspace_id) = workspace_id {
        if event.entity_type == "workspace" {
            let entity_id = parse_uuid(&event.entity_id, "entityId")?;
            if entity_id != workspace_id {
                return Err(AppError::bad_request(
                    "workspace sync event entityId must match request workspaceId",
                ));
            }
        }
    }

    Ok(())
}

fn validate_event_shape(event: &ClientChangeEvent) -> AppResult<()> {
    validate_client_event(event).map_err(|error| AppError::bad_request(error.to_string()))
}

pub async fn get_status(
    state: &AppState,
    auth: AuthContext,
    query: SyncStatusQuery,
) -> AppResult<SyncStatusResponse> {
    let replica_id = query
        .replica_id
        .as_deref()
        .map(|id| parse_uuid(id, "replicaId"))
        .transpose()?;
    super::repo::get_status(&state.db, auth, replica_id).await
}

pub async fn list_replicas(state: &AppState, auth: AuthContext) -> AppResult<ReplicaListResponse> {
    super::repo::list_replicas(&state.db, auth).await
}

pub async fn register_replica(
    state: &AppState,
    auth: AuthContext,
    mut payload: RegisterReplicaRequest,
) -> AppResult<RegisterReplicaResponse> {
    payload.replica_key = payload.replica_key.trim().to_string();
    if payload.replica_key.is_empty() {
        return Err(AppError::bad_request("replicaKey is required"));
    }
    if payload.replica_key.len() > 160 {
        return Err(AppError::bad_request("replicaKey is too long"));
    }
    let kind = normalize_replica_kind(payload.kind.clone())?;
    super::repo::register_replica(&state.db, auth, payload, kind).await
}

pub async fn push_changes(
    state: &AppState,
    auth: AuthContext,
    payload: PushChangesRequest,
) -> AppResult<PushChangesResponse> {
    let replica_id = parse_uuid(&payload.replica_id, "replicaId")?;
    let workspace_id = payload
        .workspace_id
        .as_deref()
        .map(|id| parse_uuid(id, "workspaceId"))
        .transpose()?;
    if let Some(workspace_id) = workspace_id {
        require_workspace_write(&state.db, workspace_id, auth.user_id).await?;
        let current_epoch = workspace_access_epoch(&state.db, workspace_id).await?;
        if payload.access_epoch != Some(current_epoch) {
            return Err(AppError::forbidden(
                "Sync event belongs to a stale workspace access generation",
            ));
        }
    }
    if payload.events.is_empty() {
        return Err(AppError::bad_request("At least one sync event is required"));
    }
    if payload.events.len() > MAX_PUSH_EVENTS {
        return Err(AppError::bad_request("Too many sync events in one push"));
    }

    let mut previous_seq: Option<i64> = None;
    for event in &payload.events {
        validate_event_shape(event)?;
        validate_workspace_scoping(workspace_id, event)?;
        let event_replica_id = parse_uuid(&event.replica_id, "event.replicaId")?;
        if event_replica_id != replica_id {
            return Err(AppError::bad_request(
                "All events must belong to request replicaId",
            ));
        }
        if let Some(previous_seq) = previous_seq {
            if event.replica_seq <= previous_seq {
                return Err(AppError::bad_request(
                    "events must be sorted by monotonically increasing replicaSeq",
                ));
            }
        }
        previous_seq = Some(event.replica_seq);
    }

    super::repo::push_changes(
        &state.db,
        auth,
        replica_id,
        workspace_id,
        payload.events,
        state.settings.transports.nostr.enabled,
    )
    .await
}

pub async fn pull_changes(
    state: &AppState,
    auth: AuthContext,
    query: PullChangesQuery,
) -> AppResult<PullChangesResponse> {
    let replica_id = parse_uuid(&query.replica_id, "replicaId")?;
    let scope = normalize_scope(query.scope)?;
    let workspace_id = query
        .workspace_id
        .as_deref()
        .map(|id| parse_uuid(id, "workspaceId"))
        .transpose()?;
    if scope == "workspace" && workspace_id.is_none() {
        return Err(AppError::bad_request(
            "workspaceId is required for workspace sync scope",
        ));
    }
    if scope == "global" && workspace_id.is_some() {
        return Err(AppError::bad_request(
            "workspaceId is only valid for workspace sync scope",
        ));
    }
    let last_server_order = query.last_server_order.unwrap_or(0).max(0);
    let limit = query
        .limit
        .unwrap_or(DEFAULT_PULL_LIMIT)
        .clamp(1, MAX_PULL_LIMIT);

    super::repo::pull_changes(
        &state.db,
        auth,
        replica_id,
        scope,
        workspace_id,
        last_server_order,
        limit,
    )
    .await
}

pub async fn get_transport_status(
    state: &AppState,
    _auth: AuthContext,
) -> AppResult<TransportStatusResponse> {
    let queue = crate::transports::transport_queue_status(&state.db).await?;
    Ok(TransportStatusResponse {
        coordinator: TransportAdapterStatus {
            enabled: true,
            mode: "canonical".to_string(),
            configured_endpoints: 1,
        },
        nostr: TransportAdapterStatus {
            enabled: state.settings.transports.nostr.enabled,
            mode: "shadow_store_and_forward".to_string(),
            configured_endpoints: state.settings.transports.nostr.relays.len(),
        },
        iroh: TransportAdapterStatus {
            enabled: state.settings.transports.iroh.enabled,
            mode: "direct_fast_path".to_string(),
            configured_endpoints: state.settings.transports.iroh.peers.len(),
        },
        queue,
    })
}
