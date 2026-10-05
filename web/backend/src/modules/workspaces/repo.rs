use serde_json::json;
use sqlx::{PgPool, Postgres, Row, Transaction};
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::{
        audit::repo::{record_audit, NewAuditLogEntry},
        common::{
            ensure_user_exists, normalize_limit, require_workspace_access,
            require_workspace_owner, trim_to_option,
        },
    },
};

use super::dto::{
    AddWorkspaceMemberRequest, CreateWorkspaceRequest, CreatedWorkspaceInvitationResponse,
    ListWorkspacesQuery, PageInfo, UpdateWorkspaceMemberRequest, UpdateWorkspaceRequest,
    WorkspaceInvitationPreviewResponse, WorkspaceInvitationResponse,
    WorkspaceInvitationsListResponse, WorkspaceListResponse, WorkspaceMemberResponse,
    WorkspaceMembersListResponse, WorkspaceResponse, WorkspaceWithMembersResponse,
};

fn pg_err(err: sqlx::Error, conflict_message: &'static str) -> AppError {
    match err {
        sqlx::Error::Database(db_err) if db_err.code().as_deref() == Some("23505") => {
            AppError::conflict(conflict_message)
        }
        other => other.into(),
    }
}

fn map_workspace(row: &sqlx::postgres::PgRow) -> AppResult<WorkspaceResponse> {
    Ok(WorkspaceResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        name: row.try_get("name")?,
        slug: row.try_get("slug")?,
        description: row.try_get("description")?,
        visibility: row.try_get("visibility")?,
        owner_user_id: row.try_get::<Uuid, _>("owner_user_id")?.to_string(),
        member_count: row.try_get::<i64, _>("member_count")?,
        current_user_role: row.try_get("current_user_role")?,
        access_epoch: row.try_get("access_epoch")?,
        is_archived: row.try_get::<Option<String>, _>("archived_at")?.is_some(),
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
        archived_at: row.try_get("archived_at")?,
    })
}

fn map_workspace_member(row: &sqlx::postgres::PgRow) -> AppResult<WorkspaceMemberResponse> {
    Ok(WorkspaceMemberResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        workspace_id: row.try_get::<Uuid, _>("workspace_id")?.to_string(),
        user_id: row.try_get::<Uuid, _>("user_id")?.to_string(),
        display_name: row.try_get("display_name")?,
        email: row.try_get("email")?,
        role: row.try_get("role")?,
        status: if row.try_get::<Option<String>, _>("removed_at")?.is_some() {
            "removed".to_string()
        } else {
            "active".to_string()
        },
        invited_by_user_id: row
            .try_get::<Option<Uuid>, _>("invited_by_user_id")?
            .map(|id| id.to_string()),
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
        removed_at: row.try_get("removed_at")?,
    })
}

fn map_workspace_invitation(
    row: &sqlx::postgres::PgRow,
) -> AppResult<WorkspaceInvitationResponse> {
    Ok(WorkspaceInvitationResponse {
        id: row.try_get::<Uuid, _>("id")?.to_string(),
        workspace_id: row.try_get::<Uuid, _>("workspace_id")?.to_string(),
        role: row.try_get("role")?,
        status: row.try_get("status")?,
        created_by_user_id: row
            .try_get::<Uuid, _>("created_by_user_id")?
            .to_string(),
        expires_at: row.try_get("expires_at")?,
        created_at: row.try_get("created_at")?,
        revoked_at: row.try_get("revoked_at")?,
        accepted_at: row.try_get("accepted_at")?,
        accepted_by_user_id: row
            .try_get::<Option<Uuid>, _>("accepted_by_user_id")?
            .map(|id| id.to_string()),
    })
}

async fn advance_workspace_access_epoch(
    tx: &mut Transaction<'_, Postgres>,
    workspace_id: Uuid,
) -> AppResult<i64> {
    let access_epoch = sqlx::query_scalar::<_, i64>(
        r#"
        update workspaces
        set access_epoch = access_epoch + 1,
            updated_at = now()
        where id = $1 and deleted_at is null
        returning access_epoch
        "#,
    )
    .bind(workspace_id)
    .fetch_optional(&mut **tx)
    .await?
    .ok_or_else(|| AppError::not_found("Workspace not found"))?;

    sqlx::query(
        r#"
        update roaming_board_authorizations
        set revoked_at = coalesce(revoked_at, now())
        where workspace_id = $1 and revoked_at is null
        "#,
    )
    .bind(workspace_id)
    .execute(&mut **tx)
    .await?;

    let board_ids = sqlx::query_scalar::<_, Uuid>(
        "select id from boards where workspace_id = $1 and deleted_at is null order by id",
    )
    .bind(workspace_id)
    .fetch_all(&mut **tx)
    .await?;

    #[cfg(feature = "nostr-shadow")]
    for board_id in &board_ids {
        let material = p2p_kanban_nostr_transport::NostrCodec::random_roaming_capability(
            &board_id.to_string(),
        )
        .map_err(|_| AppError::internal())?;
        sqlx::query(
            r#"
            insert into roaming_board_capabilities (
              board_id, board_tag, board_key_base64, source_kind, capability_epoch
            ) values ($1, $2, $3, 'linked_node', $4)
            on conflict (board_id) do update set
              board_tag = excluded.board_tag,
              board_key_base64 = excluded.board_key_base64,
              capability_epoch = excluded.capability_epoch,
              updated_at = now()
            "#,
        )
        .bind(board_id)
        .bind(material.board_tag)
        .bind(material.board_key)
        .bind(access_epoch)
        .execute(&mut **tx)
        .await?;
    }

    #[cfg(not(feature = "nostr-shadow"))]
    sqlx::query(
        r#"
        update roaming_board_capabilities rbc
        set capability_epoch = $2, updated_at = now()
        from boards b
        where rbc.board_id = b.id and b.workspace_id = $1
        "#,
    )
    .bind(workspace_id)
    .bind(access_epoch)
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into roaming_board_outbox (
          id, source_key, workspace_id, board_id, card_id
        )
        select
          gen_random_uuid(),
          'access-epoch:' || $2::text || ':card:' || c.id::text,
          b.workspace_id,
          b.id,
          c.id
        from boards b
        join cards c on c.board_id = b.id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
        on conflict (source_key) do nothing
        "#,
    )
    .bind(workspace_id)
    .bind(access_epoch)
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into roaming_board_settings_outbox (
          id, source_key, workspace_id, board_id
        )
        select
          gen_random_uuid(),
          'access-epoch:' || $2::text || ':appearance:' || b.id::text,
          b.workspace_id,
          b.id
        from boards b
        where b.workspace_id = $1 and b.deleted_at is null
        on conflict (source_key) do nothing
        "#,
    )
    .bind(workspace_id)
    .bind(access_epoch)
    .execute(&mut **tx)
    .await?;

    Ok(access_epoch)
}

async fn fetch_workspace(
    pool: &PgPool,
    workspace_id: Uuid,
    actor_user_id: Uuid,
) -> AppResult<WorkspaceResponse> {
    let row = sqlx::query(
        r#"
        select
          w.id,
          w.name,
          w.slug,
          w.description,
          w.visibility,
          w.owner_user_id,
          w.access_epoch,
          case
            when w.owner_user_id = $2 then 'owner'
            else (
              select wm.role
              from workspace_members wm
              where wm.workspace_id = w.id
                and wm.user_id = $2
                and wm.deactivated_at is null
                and wm.deleted_at is null
              limit 1
            )
          end as current_user_role,
          to_char(w.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(w.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when w.archived_at is null then null else to_char(w.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as archived_at,
          (
            select count(*)::bigint
            from workspace_members wm
            where wm.workspace_id = w.id
              and wm.deactivated_at is null
              and wm.deleted_at is null
          ) as member_count
        from workspaces w
        where w.id = $1
          and w.deleted_at is null
        "#,
    )
    .bind(workspace_id)
    .bind(actor_user_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Workspace not found"))?;

    map_workspace(&row)
}

pub async fn list_workspaces(
    pool: &PgPool,
    actor_user_id: Uuid,
    query: ListWorkspacesQuery,
) -> AppResult<WorkspaceListResponse> {
    ensure_user_exists(pool, actor_user_id).await?;

    let limit = normalize_limit(query.limit);
    let search = trim_to_option(query.q);
    let archived = query.archived.unwrap_or(false);
    let _cursor = query.cursor;

    let rows = sqlx::query(
        r#"
        select
          w.id,
          w.name,
          w.slug,
          w.description,
          w.visibility,
          w.owner_user_id,
          w.access_epoch,
          case
            when w.owner_user_id = $1 then 'owner'
            else (
              select wm3.role
              from workspace_members wm3
              where wm3.workspace_id = w.id
                and wm3.user_id = $1
                and wm3.deactivated_at is null
                and wm3.deleted_at is null
              limit 1
            )
          end as current_user_role,
          to_char(w.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(w.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when w.archived_at is null then null else to_char(w.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as archived_at,
          (
            select count(*)::bigint
            from workspace_members wm2
            where wm2.workspace_id = w.id
              and wm2.deactivated_at is null
              and wm2.deleted_at is null
          ) as member_count
        from workspaces w
        where w.deleted_at is null
          and (($2 = true and w.archived_at is not null) or ($2 = false and w.archived_at is null))
          and (
            w.owner_user_id = $1
            or exists (
              select 1
              from workspace_members wm
              where wm.workspace_id = w.id
                and wm.user_id = $1
                and wm.deactivated_at is null
                and wm.deleted_at is null
            )
          )
          and (
            $3::text is null
            or w.name ilike '%' || $3 || '%'
            or coalesce(w.slug, '') ilike '%' || $3 || '%'
            or coalesce(w.description, '') ilike '%' || $3 || '%'
          )
        order by w.updated_at desc, w.id desc
        limit $4
        "#,
    )
    .bind(actor_user_id)
    .bind(archived)
    .bind(search)
    .bind(limit)
    .fetch_all(pool)
    .await?;

    let items = rows
        .iter()
        .map(map_workspace)
        .collect::<AppResult<Vec<_>>>()?;

    Ok(WorkspaceListResponse {
        items,
        page_info: PageInfo {
            has_next_page: false,
            next_cursor: None,
        },
    })
}

pub async fn create_workspace(
    pool: &PgPool,
    actor_user_id: Uuid,
    payload: CreateWorkspaceRequest,
) -> AppResult<WorkspaceResponse> {
    ensure_user_exists(pool, actor_user_id).await?;

    let workspace_id = Uuid::now_v7();
    let member_id = Uuid::now_v7();
    let name = payload.name.trim().to_string();
    let slug = trim_to_option(payload.slug);
    let description = trim_to_option(payload.description);
    let visibility = payload.visibility.unwrap_or_else(|| "private".to_string());

    let mut tx = pool.begin().await?;

    let res = sqlx::query(
        r#"
        insert into workspaces (id, name, slug, description, owner_user_id, visibility)
        values ($1, $2, $3, $4, $5, $6)
        "#,
    )
    .bind(workspace_id)
    .bind(name)
    .bind(slug)
    .bind(description)
    .bind(actor_user_id)
    .bind(visibility)
    .execute(&mut *tx)
    .await;

    if let Err(err) = res {
        return Err(pg_err(err, "Workspace slug already exists"));
    }

    sqlx::query(
        r#"
        insert into workspace_members (id, workspace_id, user_id, role, invited_by_user_id)
        values ($1, $2, $3, 'owner', $3)
        "#,
    )
    .bind(member_id)
    .bind(workspace_id)
    .bind(actor_user_id)
    .execute(&mut *tx)
    .await?;

    tx.commit().await?;

    let workspace = fetch_workspace(pool, workspace_id, actor_user_id).await?;
    let _audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "workspace.created".to_string(),
            target_entity_type: Some("workspace".to_string()),
            target_entity_id: Some(workspace_id),
            request_id: None,
            metadata_jsonb: json!({
                "name": workspace.name.clone(),
                "visibility": workspace.visibility.clone(),
            }),
        },
    )
    .await?;

    Ok(workspace)
}

pub async fn get_workspace(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceWithMembersResponse> {
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    let workspace = fetch_workspace(pool, workspace_id, actor_user_id).await?;
    let members = fetch_members(pool, workspace_id).await?;

    Ok(WorkspaceWithMembersResponse {
        workspace,
        members,
    })
}

pub async fn update_workspace(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    payload: UpdateWorkspaceRequest,
) -> AppResult<WorkspaceResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;

    let name = payload.name.map(|value| value.trim().to_string());
    let slug_changed = payload.slug.is_some();
    let description_changed = payload.description.is_some();
    let slug = payload.slug.map(trim_to_option);
    let description = payload.description.map(trim_to_option);

    let res = sqlx::query(
        r#"
        update workspaces
        set
          name = coalesce($2, name),
          slug = case when $3 then $4 else slug end,
          description = case when $5 then $6 else description end,
          visibility = coalesce($7, visibility)
        where id = $1
          and deleted_at is null
        "#,
    )
    .bind(workspace_id)
    .bind(name)
    .bind(slug_changed)
    .bind(slug.flatten())
    .bind(description_changed)
    .bind(description.flatten())
    .bind(payload.visibility)
    .execute(pool)
    .await;

    match res {
        Ok(done) if done.rows_affected() == 0 => Err(AppError::not_found("Workspace not found")),
        Ok(_) => {
            let workspace = fetch_workspace(pool, workspace_id, actor_user_id).await?;
            let _audit_id = record_audit(
                pool,
                &NewAuditLogEntry {
                    workspace_id: Some(workspace_id),
                    actor_user_id: Some(actor_user_id),
                    actor_device_id: None,
                    actor_replica_id: None,
                    action_type: "workspace.updated".to_string(),
                    target_entity_type: Some("workspace".to_string()),
                    target_entity_id: Some(workspace_id),
                    request_id: None,
                    metadata_jsonb: json!({
                        "name": workspace.name.clone(),
                        "slug": workspace.slug.clone(),
                        "visibility": workspace.visibility.clone(),
                    }),
                },
            )
            .await?;
            Ok(workspace)
        }
        Err(err) => Err(pg_err(err, "Workspace slug already exists")),
    }
}

pub async fn archive_workspace(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;
    let before = fetch_workspace(pool, workspace_id, actor_user_id).await?;

    let res = sqlx::query(
        r#"
        update workspaces
        set archived_at = coalesce(archived_at, now()),
            updated_at = now()
        where id = $1
          and deleted_at is null
        "#,
    )
    .bind(workspace_id)
    .execute(pool)
    .await?;

    if res.rows_affected() == 0 {
        return Err(AppError::not_found("Workspace not found"));
    }

    let workspace = fetch_workspace(pool, workspace_id, actor_user_id).await?;
    let _audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "workspace.archived".to_string(),
            target_entity_type: Some("workspace".to_string()),
            target_entity_id: Some(workspace_id),
            request_id: None,
            metadata_jsonb: json!({
                "name": workspace.name.clone(),
                "visibility": workspace.visibility.clone(),
                "wasArchived": before.is_archived,
                "isArchived": workspace.is_archived,
            }),
        },
    )
    .await?;

    Ok(workspace)
}

pub async fn delete_workspace(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;
    let workspace = fetch_workspace(pool, workspace_id, actor_user_id).await?;

    let res = sqlx::query(
        r#"
        update workspaces
        set deleted_at = now(), updated_at = now()
        where id = $1
          and deleted_at is null
        "#,
    )
    .bind(workspace_id)
    .execute(pool)
    .await?;

    if res.rows_affected() == 0 {
        return Err(AppError::not_found("Workspace not found"));
    }

    sqlx::query(
        r#"
        update workspace_members
        set deactivated_at = coalesce(deactivated_at, now()),
            deleted_at = coalesce(deleted_at, now())
        where workspace_id = $1
          and deleted_at is null
        "#,
    )
    .bind(workspace_id)
    .execute(pool)
    .await?;

    let _audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "workspace.deleted".to_string(),
            target_entity_type: Some("workspace".to_string()),
            target_entity_id: Some(workspace_id),
            request_id: None,
            metadata_jsonb: json!({
                "name": workspace.name.clone(),
                "visibility": workspace.visibility.clone(),
            }),
        },
    )
    .await?;

    Ok(workspace)
}

async fn fetch_members(
    pool: &PgPool,
    workspace_id: Uuid,
) -> AppResult<Vec<WorkspaceMemberResponse>> {
    let rows = sqlx::query(
        r#"
        select
          wm.id,
          wm.workspace_id,
          wm.user_id,
          u.display_name,
          u.email,
          wm.role,
          wm.invited_by_user_id,
          to_char(wm.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(wm.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as updated_at,
          case when wm.deactivated_at is null then null else to_char(wm.deactivated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as removed_at
        from workspace_members wm
        join users u on u.id = wm.user_id
        where wm.workspace_id = $1
          and wm.deleted_at is null
        order by wm.created_at asc, wm.id asc
        "#,
    )
    .bind(workspace_id)
    .fetch_all(pool)
    .await?;

    rows.iter().map(map_workspace_member).collect()
}

pub async fn list_members(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceMembersListResponse> {
    require_workspace_access(pool, workspace_id, actor_user_id).await?;
    let items = fetch_members(pool, workspace_id).await?;
    Ok(WorkspaceMembersListResponse {
        items,
        page_info: PageInfo {
            has_next_page: false,
            next_cursor: None,
        },
    })
}

async fn fetch_member(pool: &PgPool, workspace_id: Uuid, member_id: Uuid) -> AppResult<WorkspaceMemberResponse> {
    fetch_members(pool, workspace_id)
        .await?
        .into_iter()
        .find(|item| item.id == member_id.to_string())
        .ok_or_else(|| AppError::not_found("Workspace member not found"))
}

pub async fn add_member(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    payload: AddWorkspaceMemberRequest,
) -> AppResult<WorkspaceMemberResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;

    let user_id = Uuid::parse_str(&payload.user_id)
        .map_err(|_| AppError::bad_request("userId must be a valid UUID"))?;
    ensure_user_exists(pool, user_id).await?;

    let member_id = Uuid::now_v7();
    let mut tx = pool.begin().await?;
    let inserted = sqlx::query(
        r#"
        insert into workspace_members (id, workspace_id, user_id, role, invited_by_user_id)
        values ($1, $2, $3, $4, $5)
        on conflict (workspace_id, user_id)
        where deactivated_at is null and deleted_at is null
        do nothing
        returning id
        "#,
    )
    .bind(member_id)
    .bind(workspace_id)
    .bind(user_id)
    .bind(payload.role)
    .bind(actor_user_id)
    .fetch_optional(&mut *tx)
    .await?;

    if inserted.is_none() {
        return Err(AppError::conflict(
            "Workspace member already exists or is still active",
        ));
    }
    let access_epoch = advance_workspace_access_epoch(&mut tx, workspace_id).await?;
    tx.commit().await?;
    let member = fetch_member(pool, workspace_id, member_id).await?;
    let _audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "workspace.member_added".to_string(),
            target_entity_type: Some("workspace_member".to_string()),
            target_entity_id: Some(Uuid::parse_str(&member.id).expect("valid member id")),
            request_id: None,
            metadata_jsonb: json!({
                "memberUserId": member.user_id.clone(),
                "role": member.role.clone(),
                "accessEpoch": access_epoch,
            }),
        },
    )
    .await?;

    Ok(member)
}

pub async fn update_member(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    member_id: Uuid,
    payload: UpdateWorkspaceMemberRequest,
) -> AppResult<WorkspaceMemberResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;

    let Some(role) = payload.role else {
        return fetch_member(pool, workspace_id, member_id).await;
    };

    let mut tx = pool.begin().await?;
    let changed = sqlx::query_scalar::<_, Uuid>(
        r#"
        update workspace_members
        set role = $3
        where id = $1
          and workspace_id = $2
          and deleted_at is null
          and deactivated_at is null
          and role <> 'owner'
          and role <> $3
        returning id
        "#,
    )
    .bind(member_id)
    .bind(workspace_id)
    .bind(&role)
    .fetch_optional(&mut *tx)
    .await?;
    if changed.is_none() {
        tx.rollback().await?;
        let member = fetch_member(pool, workspace_id, member_id).await?;
        if member.role == role && member.status == "active" && member.role != "owner" {
            return Ok(member);
        }
        return Err(AppError::not_found("Workspace member not found or cannot change owner"));
    }
    let access_epoch = advance_workspace_access_epoch(&mut tx, workspace_id).await?;
    tx.commit().await?;
    let member = fetch_member(pool, workspace_id, member_id).await?;
    let _audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "workspace.member_updated".to_string(),
            target_entity_type: Some("workspace_member".to_string()),
            target_entity_id: Some(Uuid::parse_str(&member.id).expect("valid member id")),
            request_id: None,
            metadata_jsonb: json!({
                "memberUserId": member.user_id.clone(),
                "role": member.role.clone(),
                "status": member.status.clone(),
                "accessEpoch": access_epoch,
            }),
        },
    )
    .await?;

    Ok(member)
}

pub async fn remove_member(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    member_id: Uuid,
) -> AppResult<WorkspaceMemberResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;

    let mut tx = pool.begin().await?;
    let changed = sqlx::query_scalar::<_, Uuid>(
        r#"
        update workspace_members
        set deactivated_at = coalesce(deactivated_at, now())
        where id = $1
          and workspace_id = $2
          and deleted_at is null
          and deactivated_at is null
          and role <> 'owner'
        returning id
        "#,
    )
    .bind(member_id)
    .bind(workspace_id)
    .fetch_optional(&mut *tx)
    .await?
    .ok_or_else(|| AppError::not_found("Workspace member not found or cannot remove owner"))?;
    let _ = changed;
    let access_epoch = advance_workspace_access_epoch(&mut tx, workspace_id).await?;
    tx.commit().await?;
    let member = fetch_member(pool, workspace_id, member_id).await?;
    let _audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "workspace.member_removed".to_string(),
            target_entity_type: Some("workspace_member".to_string()),
            target_entity_id: Some(Uuid::parse_str(&member.id).expect("valid member id")),
            request_id: None,
            metadata_jsonb: json!({
                "memberUserId": member.user_id.clone(),
                "role": member.role.clone(),
                "status": member.status.clone(),
                "accessEpoch": access_epoch,
            }),
        },
    )
    .await?;

    Ok(member)
}

pub async fn create_invitation(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    role: String,
    expires_in_hours: i64,
    token_hash: String,
    raw_token: String,
) -> AppResult<CreatedWorkspaceInvitationResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;
    let row = sqlx::query(
        r#"
        insert into workspace_invitations (
          id, workspace_id, token_hash, role, created_by_user_id, expires_at
        ) values ($1, $2, $3, $4, $5, now() + make_interval(hours => $6::int))
        returning
          id, workspace_id, role, created_by_user_id,
          'active'::text as status,
          to_char(expires_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as expires_at,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          null::text as revoked_at,
          null::text as accepted_at,
          accepted_by_user_id
        "#,
    )
    .bind(Uuid::now_v7())
    .bind(workspace_id)
    .bind(token_hash)
    .bind(role)
    .bind(actor_user_id)
    .bind(expires_in_hours)
    .fetch_one(pool)
    .await?;
    let invitation = map_workspace_invitation(&row)?;
    let _audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "workspace.invitation_created".to_string(),
            target_entity_type: Some("workspace_invitation".to_string()),
            target_entity_id: Some(Uuid::parse_str(&invitation.id).expect("valid invitation id")),
            request_id: None,
            metadata_jsonb: json!({
                "role": invitation.role.clone(),
                "expiresAt": invitation.expires_at.clone(),
            }),
        },
    )
    .await?;
    Ok(CreatedWorkspaceInvitationResponse { invitation, token: raw_token })
}

pub async fn list_invitations(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
) -> AppResult<WorkspaceInvitationsListResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;
    let rows = sqlx::query(
        r#"
        select
          id, workspace_id, role, created_by_user_id,
          case
            when revoked_at is not null then 'revoked'
            when accepted_at is not null then 'accepted'
            when expires_at <= now() then 'expired'
            else 'active'
          end as status,
          to_char(expires_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as expires_at,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          case when revoked_at is null then null else to_char(revoked_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as revoked_at,
          case when accepted_at is null then null else to_char(accepted_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end as accepted_at,
          accepted_by_user_id
        from workspace_invitations
        where workspace_id = $1
        order by created_at desc, id desc
        "#,
    )
    .bind(workspace_id)
    .fetch_all(pool)
    .await?;
    Ok(WorkspaceInvitationsListResponse {
        items: rows
            .iter()
            .map(map_workspace_invitation)
            .collect::<AppResult<Vec<_>>>()?,
        page_info: PageInfo { has_next_page: false, next_cursor: None },
    })
}

pub async fn preview_invitation(
    pool: &PgPool,
    token_hash: &str,
) -> AppResult<WorkspaceInvitationPreviewResponse> {
    let row = sqlx::query(
        r#"
        select
          wi.workspace_id,
          w.name as workspace_name,
          wi.role,
          case
            when wi.revoked_at is not null then 'revoked'
            when wi.accepted_at is not null then 'accepted'
            when wi.expires_at <= now() then 'expired'
            else 'active'
          end as status,
          to_char(wi.expires_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as expires_at
        from workspace_invitations wi
        join workspaces w on w.id = wi.workspace_id and w.deleted_at is null
        where wi.token_hash = $1
        "#,
    )
    .bind(token_hash)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::not_found("Invitation not found"))?;
    Ok(WorkspaceInvitationPreviewResponse {
        workspace_id: row.try_get::<Uuid, _>("workspace_id")?.to_string(),
        workspace_name: row.try_get("workspace_name")?,
        role: row.try_get("role")?,
        status: row.try_get("status")?,
        expires_at: row.try_get("expires_at")?,
    })
}

pub async fn revoke_invitation(
    pool: &PgPool,
    actor_user_id: Uuid,
    workspace_id: Uuid,
    invitation_id: Uuid,
) -> AppResult<WorkspaceInvitationResponse> {
    require_workspace_owner(pool, workspace_id, actor_user_id).await?;
    let row = sqlx::query(
        r#"
        update workspace_invitations
        set revoked_at = now(), revoked_by_user_id = $3
        where id = $1
          and workspace_id = $2
          and revoked_at is null
          and accepted_at is null
          and expires_at > now()
        returning
          id, workspace_id, role, created_by_user_id,
          'revoked'::text as status,
          to_char(expires_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as expires_at,
          to_char(created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as created_at,
          to_char(revoked_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as revoked_at,
          null::text as accepted_at,
          accepted_by_user_id
        "#,
    )
    .bind(invitation_id)
    .bind(workspace_id)
    .bind(actor_user_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| AppError::conflict("Invitation is no longer active"))?;
    map_workspace_invitation(&row)
}

pub async fn accept_invitation(
    pool: &PgPool,
    actor_user_id: Uuid,
    token_hash: &str,
) -> AppResult<WorkspaceResponse> {
    ensure_user_exists(pool, actor_user_id).await?;
    let mut tx = pool.begin().await?;
    let row = sqlx::query(
        r#"
        select
          id,
          workspace_id,
          role,
          expires_at > now() and revoked_at is null and accepted_at is null as is_active
        from workspace_invitations
        where token_hash = $1
        for update
        "#,
    )
    .bind(token_hash)
    .fetch_optional(&mut *tx)
    .await?
    .ok_or_else(|| AppError::not_found("Invitation not found"))?;
    let invitation_id: Uuid = row.try_get("id")?;
    let workspace_id: Uuid = row.try_get("workspace_id")?;
    let role: String = row.try_get("role")?;
    let active: bool = row.try_get("is_active")?;
    if !active {
        return Err(AppError::conflict("Invitation is expired, revoked or already used"));
    }

    let membership_id = Uuid::now_v7();
    let inserted = sqlx::query_scalar::<_, Uuid>(
        r#"
        insert into workspace_members (id, workspace_id, user_id, role, invited_by_user_id)
        select $1, $2, $3, $4, created_by_user_id
        from workspace_invitations where id = $5
        on conflict (workspace_id, user_id)
        where deactivated_at is null and deleted_at is null
        do nothing
        returning id
        "#,
    )
    .bind(membership_id)
    .bind(workspace_id)
    .bind(actor_user_id)
    .bind(&role)
    .bind(invitation_id)
    .fetch_optional(&mut *tx)
    .await?;
    if inserted.is_none() {
        return Err(AppError::conflict("User is already an active workspace member"));
    }
    sqlx::query(
        "update workspace_invitations set accepted_at = now(), accepted_by_user_id = $2 where id = $1",
    )
    .bind(invitation_id)
    .bind(actor_user_id)
    .execute(&mut *tx)
    .await?;
    let access_epoch = advance_workspace_access_epoch(&mut tx, workspace_id).await?;
    tx.commit().await?;

    let workspace = fetch_workspace(pool, workspace_id, actor_user_id).await?;
    let _audit_id = record_audit(
        pool,
        &NewAuditLogEntry {
            workspace_id: Some(workspace_id),
            actor_user_id: Some(actor_user_id),
            actor_device_id: None,
            actor_replica_id: None,
            action_type: "workspace.invitation_accepted".to_string(),
            target_entity_type: Some("workspace_member".to_string()),
            target_entity_id: Some(membership_id),
            request_id: None,
            metadata_jsonb: json!({ "role": role, "accessEpoch": access_epoch }),
        },
    )
    .await?;
    Ok(workspace)
}
