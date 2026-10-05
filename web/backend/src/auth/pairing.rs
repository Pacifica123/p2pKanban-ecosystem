use std::{
    collections::{HashMap, HashSet},
    net::IpAddr,
    time::Duration,
};

use axum::http::HeaderMap;
use serde::Deserialize;
use serde_json::Value;
use sqlx::{Postgres, Row, Transaction};
use uuid::Uuid;

#[cfg(feature = "nostr-shadow")]
use p2p_kanban_nostr_transport::{NostrCodec, ROAMING_EVENT_KIND_OFFSET};

use crate::{
    error::{AppError, AppResult},
    modules::integrations::{dto::PortableBundle, service::build_portable_bundle},
    state::AppState,
};

use super::{
    dto::{
        NodeLinkBoardCapabilitySnapshot, NodeLinkCardTombstoneSnapshot, NodeLinkExportRequest,
        NodeLinkExportResponse, NodeLinkImportRequest, NodeLinkTransportSnapshot,
        NodeLinkUserAppearanceSnapshot, NodeLinkUserSnapshot, NodeLinkWorkspaceSnapshot,
    },
    repo,
    service::{
        authenticate_user_with_password, create_authenticated_session, hash_password,
        normalize_email, validate_password, AuthSuccessEnvelope,
    },
};

const NODE_LINK_FORMAT: &str = "p2p-kanban-web-node-link";
const NODE_LINK_FORMAT_VERSION: i32 = 1;
const MAX_NODE_LINK_RESPONSE_BYTES: usize = 32 * 1024 * 1024;

#[derive(Debug, Deserialize)]
struct RemoteEnvelope<T> {
    data: T,
}

pub async fn export_node_link(
    state: &AppState,
    payload: NodeLinkExportRequest,
) -> AppResult<NodeLinkExportResponse> {
    let user=authenticate_user_with_password(state,&payload.email,&payload.password).await?;
    export_for_user(state,user).await
}
pub(super) async fn export_for_user(state:&AppState,user:repo::AuthUserRecord)->AppResult<NodeLinkExportResponse>{
 #[cfg(not(feature="nostr-shadow"))]{let _=(state,user);return Err(AppError::conflict("Nostr support is required"));}
 #[cfg(feature="nostr-shadow")]{
        let nostr = &state.settings.transports.nostr;
        if !nostr.enabled {
            return Err(AppError::conflict(
                "Independent board sync is not enabled on the source node",
            ));
        }

        let workspace_ids = sqlx::query_scalar::<_, Uuid>(
            r#"
            select w.id
            from workspaces w
            join workspace_members wm
              on wm.workspace_id = w.id
             and wm.user_id = $1
             and wm.role = 'owner'
             and wm.deactivated_at is null
             and wm.deleted_at is null
            where w.owner_user_id = $1
              and w.deleted_at is null
            order by w.created_at, w.id
            "#,
        )
        .bind(user.id)
        .fetch_all(&state.db)
        .await?;

        let omitted_shared_workspaces = sqlx::query_scalar::<_, i64>(
            r#"
            select count(*)::bigint
            from workspace_members wm
            join workspaces w on w.id = wm.workspace_id
            where wm.user_id = $1
              and wm.role <> 'owner'
              and wm.deactivated_at is null
              and wm.deleted_at is null
              and w.deleted_at is null
            "#,
        )
        .bind(user.id)
        .fetch_one(&state.db)
        .await?;

        let mut workspaces = Vec::with_capacity(workspace_ids.len());
        for workspace_id in &workspace_ids {
            let bundle = build_portable_bundle(
                &state.db,
                user.id,
                "workspace",
                *workspace_id,
                None,
                "portable_export",
                true,
                false,
                true,
                false,
            )
            .await?;
            workspaces.push(NodeLinkWorkspaceSnapshot {
                membership_role: "owner".to_string(),
                bundle,
            });
        }

        let board_rows = sqlx::query(
            r#"
            select b.id, w.access_epoch, rbc.board_tag, rbc.board_key_base64
            from boards b
            join workspaces w on w.id = b.workspace_id
            left join roaming_board_capabilities rbc on rbc.board_id = b.id
            where w.owner_user_id = $1
              and w.deleted_at is null
              and b.deleted_at is null
            order by b.created_at, b.id
            "#,
        )
        .bind(user.id)
        .fetch_all(&state.db)
        .await?;

        let codec = NostrCodec::new(nostr.master_key().map_err(|_| AppError::internal())?)
            .map_err(|_| AppError::internal())?;
        let mut board_capabilities = Vec::with_capacity(board_rows.len());
        for row in board_rows {
            let board_id: Uuid = row.try_get("id")?;
            let imported_key: Option<String> = row.try_get("board_key_base64")?;
            let imported_tag: Option<String> = row.try_get("board_tag")?;
            let material = if let Some(board_key) = imported_key {
                let material = NostrCodec::roaming_capability_from_board_key(
                    &board_id.to_string(),
                    &board_key,
                )
                .map_err(|_| AppError::internal())?;
                if imported_tag.as_deref() != Some(material.board_tag.as_str()) {
                    return Err(AppError::internal());
                }
                material
            } else {
                codec
                    .roaming_capability(&board_id.to_string())
                    .map_err(|_| AppError::internal())?
            };
            // Pin exported keys so later capability provisioning reuses them.
            let stored = sqlx::query_as::<_, (String, String)>(
                "insert into roaming_board_capabilities (board_id,board_tag,board_key_base64,source_kind,capability_epoch) values ($1,$2,$3,'linked_node',$4) on conflict (board_id) do update set board_id=excluded.board_id returning board_tag,board_key_base64"
            ).bind(board_id).bind(&material.board_tag).bind(&material.board_key)
                .bind(row.try_get::<i64,_>("access_epoch")?).fetch_one(&state.db).await?;
            board_capabilities.push(NodeLinkBoardCapabilitySnapshot {
                board_id, board_tag: stored.0, board_key: stored.1,
            });
        }

        let user_appearance = sqlx::query(
            r#"
            select
              app_theme,
              density,
              reduce_motion,
              checklist_item_submit_mode,
              card_details_mode
            from user_appearance_preferences
            where user_id = $1
            "#,
        )
        .bind(user.id)
        .fetch_optional(&state.db)
        .await?
        .map(
            |row| -> Result<NodeLinkUserAppearanceSnapshot, sqlx::Error> {
                Ok(NodeLinkUserAppearanceSnapshot {
                    app_theme: row.try_get("app_theme")?,
                    density: row.try_get("density")?,
                    reduce_motion: row.try_get("reduce_motion")?,
                    checklist_item_submit_mode: row.try_get("checklist_item_submit_mode")?,
                    card_details_mode: row.try_get("card_details_mode")?,
                })
            },
        )
        .transpose()?;

        let card_tombstones = sqlx::query(
            r#"
            select
              t.workspace_id,
              b.id as board_id,
              t.entity_id as card_id,
              to_char(t.deleted_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as deleted_at
            from tombstones t
            join cards c on c.id = t.entity_id
            join boards b on b.id = c.board_id
            join workspaces w on w.id = t.workspace_id
            where t.entity_type = 'card'
              and w.owner_user_id = $1
              and w.deleted_at is null
              and b.deleted_at is null
            order by t.deleted_at, t.entity_id
            "#,
        )
        .bind(user.id)
        .fetch_all(&state.db)
        .await?
        .into_iter()
        .map(|row| -> Result<NodeLinkCardTombstoneSnapshot, sqlx::Error> {
            Ok(NodeLinkCardTombstoneSnapshot {
                workspace_id: row.try_get("workspace_id")?,
                board_id: row.try_get("board_id")?,
                card_id: row.try_get("card_id")?,
                deleted_at: row.try_get("deleted_at")?,
            })
        })
        .collect::<Result<Vec<_>, _>>()?;

        let exported_at = sqlx::query_scalar::<_, String>(
            r#"select to_char(now() at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')"#,
        )
        .fetch_one(&state.db)
        .await?;

        let mut warnings = Vec::new();
        if omitted_shared_workspaces > 0 {
            warnings.push(format!(
                "{omitted_shared_workspaces} shared workspace(s) were omitted because linked-node v1 transfers only workspaces owned by this account"
            ));
        }

        Ok(NodeLinkExportResponse {
            format: NODE_LINK_FORMAT.to_string(),
            format_version: NODE_LINK_FORMAT_VERSION,
            user: NodeLinkUserSnapshot {
                id: user.id,
                email: user.email,
                display_name: user.display_name,
            },
            user_appearance,
            workspaces,
            board_capabilities,
            card_tombstones,
            transport: NodeLinkTransportSnapshot {
                relays: nostr.relays.clone(),
                event_kind: nostr.event_kind.saturating_add(ROAMING_EVENT_KIND_OFFSET),
                minimum_relay_acks: nostr.min_relay_acks,
            },
            exported_at,
            warnings,
        })
    }
}

pub async fn import_node_link(
    state: &AppState,
    headers: &HeaderMap,
    payload: NodeLinkImportRequest,
) -> AppResult<AuthSuccessEnvelope> {
    #[cfg(not(feature = "nostr-shadow"))]
    {
        let _ = (state, headers, payload);
        return Err(AppError::conflict(
            "This backend build does not include linked web-node sync",
        ));
    }

    #[cfg(feature = "nostr-shadow")]
    {
        let email = normalize_email(&payload.email)?;
        validate_password(&payload.password)?;
        ensure_empty_destination(state).await?;

        let source_endpoint = source_export_endpoint(&payload.source_url)?;
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| AppError::internal())?;
        let request_body = serde_json::to_vec(&NodeLinkExportRequest {
            email: email.clone(),
            password: payload.password.clone(),
        })
        .map_err(|_| AppError::internal())?;
        let response = client
            .post(source_endpoint)
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .body(request_body)
            .send()
            .await
            .map_err(|error| {
                AppError::bad_request(format!(
                    "Не удалось связаться с исходным web-узлом: {error}"
                ))
            })?;

        let status = response.status();
        if response
            .content_length()
            .is_some_and(|length| length > MAX_NODE_LINK_RESPONSE_BYTES as u64)
        {
            return Err(AppError::bad_request(
                "Ответ исходного узла превышает безопасный размер 32 MiB",
            ));
        }
        let bytes = response.bytes().await.map_err(|error| {
            AppError::bad_request(format!(
                "Не удалось прочитать ответ исходного узла: {error}"
            ))
        })?;
        if bytes.len() > MAX_NODE_LINK_RESPONSE_BYTES {
            return Err(AppError::bad_request(
                "Ответ исходного узла превышает безопасный размер 32 MiB",
            ));
        }
        if !status.is_success() {
            let message = serde_json::from_slice::<Value>(&bytes)
                .ok()
                .and_then(|value| {
                    value
                        .get("error")
                        .and_then(|error| error.get("message"))
                        .and_then(Value::as_str)
                        .map(ToOwned::to_owned)
                })
                .unwrap_or_else(|| format!("исходный узел вернул HTTP {}", status.as_u16()));
            if status.as_u16() == 401 {
                return Err(AppError::unauthorized(message));
            }
            return Err(AppError::bad_request(message));
        }

        let remote = serde_json::from_slice::<RemoteEnvelope<NodeLinkExportResponse>>(&bytes)
            .map_err(|_| AppError::bad_request("Исходный узел вернул несовместимый ответ"))?
            .data;
        validate_remote_snapshot(state, &remote, &email)?;

        let password_hash = hash_password(&payload.password)?;
        let mut tx = state.db.begin().await?;
        import_user(&mut tx, &remote, &password_hash).await?;
        for workspace in &remote.workspaces {
            import_workspace_bundle(&mut tx, remote.user.id, &workspace.bundle).await?;
        }
        import_user_appearance(&mut tx, remote.user.id, remote.user_appearance.as_ref()).await?;
        import_board_capabilities(&mut tx, &remote.board_capabilities).await?;
        import_card_tombstones(&mut tx, &remote.card_tombstones).await?;
        tx.commit().await?;

        let user = repo::find_active_user_by_id(&state.db, remote.user.id)
            .await?
            .ok_or_else(AppError::internal)?;
        create_authenticated_session(state, &user, headers).await
    }
}

pub(super) async fn ensure_empty_destination(state: &AppState) -> AppResult<()> {
    let occupied = sqlx::query_scalar::<_, bool>(
        r#"
        select exists(select 1 from users)
            or exists(select 1 from workspaces)
            or exists(select 1 from boards)
        "#,
    )
    .fetch_one(&state.db)
    .await?;
    if occupied {
        return Err(AppError::conflict(
            "На этом узле уже есть локальный аккаунт или данные. Web-node link v1 работает только с чистым узлом; сохраните нужные локальные данные и выполните bootstrap reset перед подключением.",
        ));
    }
    Ok(())
}

fn source_export_endpoint(source_url: &str) -> AppResult<reqwest::Url> {
    let mut url = reqwest::Url::parse(source_url.trim())
        .map_err(|_| AppError::bad_request("Адрес исходного узла некорректен"))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(AppError::bad_request(
            "Адрес исходного узла должен использовать http:// или https://",
        ));
    }
    if !url.username().is_empty() || url.password().is_some() || url.query().is_some() {
        return Err(AppError::bad_request(
            "В адресе исходного узла не должно быть логина, пароля или query-параметров",
        ));
    }
    if !matches!(url.path(), "" | "/") {
        return Err(AppError::bad_request(
            "Укажите корневой адрес web-узла без /api и других путей",
        ));
    }

    let host = url
        .host_str()
        .ok_or_else(|| AppError::bad_request("В адресе исходного узла отсутствует host"))?;
    if host != "localhost" {
        let address = host.parse::<IpAddr>().map_err(|_| {
            AppError::bad_request(
                "Для первого web-node link укажите localhost или прямой IP-адрес доверенной локальной сети",
            )
        })?;
        let private = match address {
            IpAddr::V4(value) => value.is_private() || value.is_loopback() || value.is_link_local(),
            IpAddr::V6(value) => {
                value.is_loopback() || value.is_unique_local() || value.is_unicast_link_local()
            }
        };
        if !private {
            return Err(AppError::bad_request(
                "Web-node link v1 разрешает только адреса доверенной локальной сети",
            ));
        }
    }

    url.set_path("/api/v1/auth/node-link/export");
    url.set_fragment(None);
    Ok(url)
}

#[cfg(feature = "nostr-shadow")]
pub(super) fn validate_remote_snapshot(
    state: &AppState,
    remote: &NodeLinkExportResponse,
    expected_email: &str,
) -> AppResult<()> {
    if remote.format != NODE_LINK_FORMAT || remote.format_version != NODE_LINK_FORMAT_VERSION {
        return Err(AppError::bad_request(
            "Исходный узел использует несовместимый формат web-node link",
        ));
    }
    if normalize_email(&remote.user.email)? != expected_email {
        return Err(AppError::bad_request(
            "Исходный узел вернул другую идентичность аккаунта",
        ));
    }

    let nostr = &state.settings.transports.nostr;
    if !nostr.enabled {
        return Err(AppError::conflict(
            "Independent board sync is not enabled on the destination node",
        ));
    }
    let expected_kind = nostr.event_kind.saturating_add(ROAMING_EVENT_KIND_OFFSET);
    if remote.transport.event_kind != expected_kind {
        return Err(AppError::conflict(
            "Исходный и целевой узлы используют разные Nostr event kinds",
        ));
    }
    if !remote
        .transport
        .relays
        .iter()
        .any(|relay| nostr.relays.contains(relay))
    {
        return Err(AppError::conflict(
            "У исходного и целевого узлов нет общего Nostr relay",
        ));
    }

    let mut workspace_ids = HashSet::new();
    let mut board_ids = HashSet::new();
    let mut board_workspaces = HashMap::new();
    for workspace in &remote.workspaces {
        if workspace.membership_role != "owner" {
            return Err(AppError::bad_request(
                "Web-node link v1 принимает только workspace владельца",
            ));
        }
        validate_bundle(
            &workspace.bundle,
            remote.user.id,
            &mut workspace_ids,
            &mut board_ids,
            &mut board_workspaces,
        )?;
    }

    let capability_ids = remote
        .board_capabilities
        .iter()
        .map(|capability| capability.board_id)
        .collect::<HashSet<_>>();
    if capability_ids != board_ids {
        return Err(AppError::bad_request(
            "Набор ключей досок не совпадает со снимком данных",
        ));
    }
    for capability in &remote.board_capabilities {
        let material = NostrCodec::roaming_capability_from_board_key(
            &capability.board_id.to_string(),
            &capability.board_key,
        )
        .map_err(|_| AppError::bad_request("Исходный узел передал некорректный ключ доски"))?;
        if material.board_tag != capability.board_tag {
            return Err(AppError::bad_request(
                "Тег доски не соответствует переданному ключу",
            ));
        }
    }
    let mut tombstone_ids = HashSet::new();
    for tombstone in &remote.card_tombstones {
        if !workspace_ids.contains(&tombstone.workspace_id)
            || !board_ids.contains(&tombstone.board_id)
            || board_workspaces.get(&tombstone.board_id) != Some(&tombstone.workspace_id)
            || !tombstone_ids.insert(tombstone.card_id)
        {
            return Err(AppError::bad_request(
                "Tombstone карточки имеет неверный scope или повторяющийся ID",
            ));
        }
    }

    if let Some(appearance) = &remote.user_appearance {
        if !matches!(appearance.app_theme.as_str(), "system" | "light" | "dark")
            || !matches!(appearance.density.as_str(), "comfortable" | "compact")
            || !matches!(
                appearance.checklist_item_submit_mode.as_str(),
                "ctrl_enter" | "enter" | "button"
            )
            || !matches!(appearance.card_details_mode.as_str(), "drawer" | "modal")
        {
            return Err(AppError::bad_request(
                "Исходный узел передал некорректные настройки аккаунта",
            ));
        }
    }
    Ok(())
}

fn validate_bundle(
    bundle: &PortableBundle,
    user_id: Uuid,
    workspace_ids: &mut HashSet<Uuid>,
    board_ids: &mut HashSet<Uuid>,
    board_workspaces: &mut HashMap<Uuid, Uuid>,
) -> AppResult<()> {
    if bundle.manifest_json.format != "p2p_planner_bundle"
        || bundle.manifest_json.format_version != 1
        || bundle.manifest_json.scope_kind != "workspace"
        || bundle.origin.exported_by_user_id != user_id
    {
        return Err(AppError::bad_request(
            "Снимок workspace имеет несовместимый формат или владельца",
        ));
    }
    let workspace_id = bundle
        .manifest_json
        .workspace_id
        .ok_or_else(|| AppError::bad_request("В снимке отсутствует workspaceId"))?;
    if !workspace_ids.insert(workspace_id) {
        return Err(AppError::bad_request("Workspace повторяется в снимке"));
    }

    for (name, value) in [
        ("workspaces", &bundle.payload.workspaces),
        ("boards", &bundle.payload.boards),
        ("columns", &bundle.payload.columns),
        ("cards", &bundle.payload.cards),
        ("labels", &bundle.payload.labels),
        ("cardLabels", &bundle.payload.card_labels),
        ("checklists", &bundle.payload.checklists),
        ("checklistItems", &bundle.payload.checklist_items),
        ("comments", &bundle.payload.comments),
        (
            "boardAppearanceSettings",
            &bundle.payload.board_appearance_settings,
        ),
    ] {
        if !value.is_array() {
            return Err(AppError::bad_request(format!(
                "Поле {name} в снимке должно быть массивом"
            )));
        }
    }

    let workspaces = bundle.payload.workspaces.as_array().unwrap();
    if workspaces.len() != 1
        || value_uuid(&workspaces[0], "id")? != workspace_id
        || value_uuid(&workspaces[0], "ownerUserId")? != user_id
    {
        return Err(AppError::bad_request(
            "Workspace в payload не совпадает с manifest",
        ));
    }
    for board in bundle.payload.boards.as_array().unwrap() {
        let board_id = value_uuid(board, "id")?;
        if value_uuid(board, "workspaceId")? != workspace_id
            || !board_ids.insert(board_id)
            || board_workspaces.insert(board_id, workspace_id).is_some()
        {
            return Err(AppError::bad_request(
                "Доска имеет неверный scope или повторяющийся ID",
            ));
        }
    }
    Ok(())
}

fn value_uuid(value: &Value, field: &str) -> AppResult<Uuid> {
    let raw = value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| AppError::bad_request(format!("В снимке отсутствует {field}")))?;
    Uuid::parse_str(raw)
        .map_err(|_| AppError::bad_request(format!("В снимке некорректный {field}")))
}

pub(super) async fn import_user(
    tx: &mut Transaction<'_, Postgres>,
    remote: &NodeLinkExportResponse,
    password_hash: &str,
) -> AppResult<()> {
    sqlx::query(
        r#"
        insert into users (id, email, display_name, password_hash)
        values ($1, $2, $3, $4)
        "#,
    )
    .bind(remote.user.id)
    .bind(&remote.user.email)
    .bind(&remote.user.display_name)
    .bind(password_hash)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

pub(super) async fn import_workspace_bundle(
    tx: &mut Transaction<'_, Postgres>,
    user_id: Uuid,
    bundle: &PortableBundle,
) -> AppResult<()> {
    import_workspace_bundle_parts(tx, user_id, bundle, true).await
}
pub(super) async fn import_workspace_bundle_parts(
    tx: &mut Transaction<'_, Postgres>, user_id: Uuid, bundle: &PortableBundle, include_workspace: bool,
) -> AppResult<()> {
    let payload = &bundle.payload;
    if include_workspace {
    sqlx::query(
        r#"
        insert into workspaces (
          id, name, slug, description, owner_user_id, visibility,
          created_at, updated_at, archived_at
        )
        select
          x.id, x.name, x.slug, x.description, $2, x.visibility,
          x."createdAt", x."updatedAt", x."archivedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, name text, slug text, description text, visibility text,
          "ownerUserId" uuid, "createdAt" timestamptz,
          "updatedAt" timestamptz, "archivedAt" timestamptz
        )
        "#,
    )
    .bind(payload.workspaces.clone())
    .bind(user_id)
    .execute(&mut **tx)
    .await?;

    let workspace_id = bundle.manifest_json.workspace_id.unwrap();
    sqlx::query(
        r#"
        insert into workspace_members (id, workspace_id, user_id, role, invited_by_user_id)
        values ($1, $2, $3, 'owner', null)
        "#,
    )
    .bind(Uuid::now_v7())
    .bind(workspace_id)
    .bind(user_id)
    .execute(&mut **tx)
    .await?;

    }
    sqlx::query(
        r#"
        insert into boards (
          id, workspace_id, name, description, board_type, created_by_user_id,
          created_at, updated_at, archived_at
        )
        select
          x.id, x."workspaceId", x.name, x.description, x."boardType",
          case when x."createdByUserId" = $2 then $2 else null end,
          x."createdAt", x."updatedAt", x."archivedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, "workspaceId" uuid, name text, description text,
          "boardType" text, "createdByUserId" uuid,
          "createdAt" timestamptz, "updatedAt" timestamptz, "archivedAt" timestamptz
        )
        "#,
    )
    .bind(payload.boards.clone())
    .bind(user_id)
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into board_columns (
          id, board_id, name, description, position, color_token, wip_limit,
          created_at, updated_at
        )
        select
          x.id, x."boardId", x.name, x.description, x.position,
          x."colorToken", x."wipLimit", x."createdAt", x."updatedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, "boardId" uuid, name text, description text,
          position double precision, "colorToken" text, "wipLimit" integer,
          "createdAt" timestamptz, "updatedAt" timestamptz
        )
        "#,
    )
    .bind(payload.columns.clone())
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into cards (
          id, board_id, column_id, parent_card_id, title, description, position,
          priority, start_at, due_at, created_by_user_id,
          created_at, updated_at, archived_at
        )
        select
          x.id, x."boardId", x."columnId", null, x.title, x.description, x.position,
          x.priority, x."startAt", x."dueAt",
          case when x."createdByUserId" = $2 then $2 else null end,
          x."createdAt", x."updatedAt", x."archivedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, "boardId" uuid, "columnId" uuid, "parentCardId" uuid,
          title text, description text, position double precision,
          priority text, "startAt" timestamptz, "dueAt" timestamptz,
          "createdByUserId" uuid,
          "createdAt" timestamptz, "updatedAt" timestamptz, "archivedAt" timestamptz
        )
        "#,
    )
    .bind(payload.cards.clone())
    .bind(user_id)
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        update cards c
        set parent_card_id = x."parentCardId"
        from jsonb_to_recordset($1::jsonb) as x(id uuid, "parentCardId" uuid)
        where c.id = x.id and x."parentCardId" is not null
        "#,
    )
    .bind(payload.cards.clone())
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into board_labels (
          id, board_id, name, color, description, created_at, updated_at
        )
        select
          x.id, x."boardId", x.name, x.color, x.description, x."createdAt", x."updatedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, "boardId" uuid, name text, color text, description text,
          "createdAt" timestamptz, "updatedAt" timestamptz
        )
        "#,
    )
    .bind(payload.labels.clone())
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into card_labels (id, board_id, card_id, label_id, created_at)
        select x.id, x."boardId", x."cardId", x."labelId", x."createdAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, "boardId" uuid, "cardId" uuid, "labelId" uuid,
          "createdAt" timestamptz
        )
        "#,
    )
    .bind(payload.card_labels.clone())
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into checklists (id, card_id, title, position, created_at, updated_at)
        select x.id, x."cardId", x.title, x.position, x."createdAt", x."updatedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, "cardId" uuid, title text, position double precision,
          "createdAt" timestamptz, "updatedAt" timestamptz
        )
        "#,
    )
    .bind(payload.checklists.clone())
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into checklist_items (
          id, checklist_id, title, is_done, position, due_at, completed_at,
          created_at, updated_at
        )
        select
          x.id, x."checklistId", x.title, x."isDone", x.position,
          x."dueAt", x."completedAt", x."createdAt", x."updatedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, "checklistId" uuid, title text, "isDone" boolean,
          position double precision, "dueAt" timestamptz, "completedAt" timestamptz,
          "createdAt" timestamptz, "updatedAt" timestamptz
        )
        "#,
    )
    .bind(payload.checklist_items.clone())
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into comments (id, card_id, author_user_id, body, created_at, updated_at)
        select
          x.id, x."cardId",
          case when x."authorUserId" = $2 then $2 else null end,
          x.body, x."createdAt", x."updatedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          id uuid, "cardId" uuid, "authorUserId" uuid, body text,
          "createdAt" timestamptz, "updatedAt" timestamptz
        )
        "#,
    )
    .bind(payload.comments.clone())
    .bind(user_id)
    .execute(&mut **tx)
    .await?;

    sqlx::query(
        r#"
        insert into board_appearance_settings (
          board_id, theme_preset, wallpaper_kind, wallpaper_value,
          column_density, card_preview_mode, show_card_description,
          show_card_dates, show_checklist_progress, custom_properties_jsonb,
          created_at, updated_at
        )
        select
          x."boardId", x."themePreset", x."wallpaperKind", x."wallpaperValue",
          x."columnDensity", x."cardPreviewMode", x."showCardDescription",
          x."showCardDates", x."showChecklistProgress", x."customProperties",
          x."createdAt", x."updatedAt"
        from jsonb_to_recordset($1::jsonb) as x(
          "boardId" uuid, "themePreset" text, "wallpaperKind" text,
          "wallpaperValue" text, "columnDensity" text, "cardPreviewMode" text,
          "showCardDescription" boolean, "showCardDates" boolean,
          "showChecklistProgress" boolean, "customProperties" jsonb,
          "createdAt" timestamptz, "updatedAt" timestamptz
        )
        "#,
    )
    .bind(payload.board_appearance_settings.clone())
    .execute(&mut **tx)
    .await?;

    Ok(())
}

pub(super) async fn import_user_appearance(
    tx: &mut Transaction<'_, Postgres>,
    user_id: Uuid,
    appearance: Option<&NodeLinkUserAppearanceSnapshot>,
) -> AppResult<()> {
    let Some(appearance) = appearance else {
        return Ok(());
    };
    sqlx::query(
        r#"
        insert into user_appearance_preferences (
          user_id, app_theme, density, reduce_motion,
          checklist_item_submit_mode, card_details_mode
        )
        values ($1, $2, $3, $4, $5, $6)
        "#,
    )
    .bind(user_id)
    .bind(&appearance.app_theme)
    .bind(&appearance.density)
    .bind(appearance.reduce_motion)
    .bind(&appearance.checklist_item_submit_mode)
    .bind(&appearance.card_details_mode)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

pub(super) async fn import_board_capabilities(
    tx: &mut Transaction<'_, Postgres>,
    capabilities: &[NodeLinkBoardCapabilitySnapshot],
) -> AppResult<()> {
    for capability in capabilities {
        sqlx::query(
            r#"
            insert into roaming_board_capabilities (
              board_id, board_tag, board_key_base64, source_kind
            )
            values ($1, $2, $3, 'linked_node')
            "#,
        )
        .bind(capability.board_id)
        .bind(&capability.board_tag)
        .bind(&capability.board_key)
        .execute(&mut **tx)
        .await?;
    }
    Ok(())
}

pub(super) async fn import_card_tombstones(
    tx: &mut Transaction<'_, Postgres>,
    tombstones: &[NodeLinkCardTombstoneSnapshot],
) -> AppResult<()> {
    for tombstone in tombstones {
        sqlx::query(
            r#"
            insert into tombstones (
              id, workspace_id, entity_type, entity_id, deleted_at, metadata_jsonb
            ) values (
              gen_random_uuid(), $1, 'card', $2, $3::timestamptz,
              jsonb_build_object(
                'boardId', $4,
                'scope', 'all_devices',
                'source', 'web_node_link'
              )
            )
            on conflict (entity_type, entity_id) do update set
              deleted_at = greatest(tombstones.deleted_at, excluded.deleted_at),
              metadata_jsonb = tombstones.metadata_jsonb || excluded.metadata_jsonb
            "#,
        )
        .bind(tombstone.workspace_id)
        .bind(tombstone.card_id)
        .bind(&tombstone.deleted_at)
        .bind(tombstone.board_id)
        .execute(&mut **tx)
        .await?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_private_lan_source() {
        let url = source_export_endpoint("http://192.168.1.42:8080").unwrap();
        assert_eq!(
            url.as_str(),
            "http://192.168.1.42:8080/api/v1/auth/node-link/export"
        );
    }

    #[test]
    fn rejects_public_or_nested_source() {
        assert!(source_export_endpoint("https://8.8.8.8").is_err());
        assert!(source_export_endpoint("http://192.168.1.42:8080/api/v1").is_err());
    }

    #[test]
    fn rejects_dns_and_embedded_credentials() {
        assert!(source_export_endpoint("https://kanban.example.org").is_err());
        assert!(source_export_endpoint("http://user:secret@192.168.1.42:8080").is_err());
    }
}
