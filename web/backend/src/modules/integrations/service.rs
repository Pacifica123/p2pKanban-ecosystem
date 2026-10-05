use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::common::{board_workspace_id, ensure_user_exists, require_workspace_access},
    state::AppState,
};

use super::dto::{
    CreateExportJobRequest, CreateImportExecutionRequest, CreateImportJobRequest,
    CreateImportPreviewRequest, CreatePortableExportRequest, ImportExecutionResponse,
    ImportExportCapabilitiesResponse, ImportPreviewResponse, IntegrationOperationStubResponse,
    IntegrationProviderCatalogResponse, IntegrationProviderDetailResponse, PortableBundle,
    PortableBundleIncludes, PortableBundleManifest, PortableBundleOrigin, PortableBundlePayload,
    PortableBundleRestoreHints, PortableBundleScope, PortableBundleSummary, PortableEntityCounts,
    PortableExportResponse, WebhookReceiptResponse,
};

const IMPORT_EXPORT_PROVIDER_KEY: &str = "import_export";
const PORTABLE_BUNDLE_FORMAT: &str = "p2p_planner_bundle";
const PORTABLE_BUNDLE_FORMAT_VERSION: i32 = 1;

fn ensure_provider_exists(provider_key: &str) -> AppResult<IntegrationProviderDetailResponse> {
    super::provider::find_provider(provider_key).ok_or_else(|| {
        AppError::not_found(format!("Integration provider '{provider_key}' not found"))
    })
}

pub async fn list_providers(
    state: &AppState,
    actor_user_id: Uuid,
) -> AppResult<IntegrationProviderCatalogResponse> {
    ensure_user_exists(&state.db, actor_user_id).await?;

    let items = super::provider::builtin_providers()
        .into_iter()
        .map(|provider| provider.manifest().provider)
        .collect();

    Ok(IntegrationProviderCatalogResponse { items })
}

pub async fn get_provider_detail(
    state: &AppState,
    actor_user_id: Uuid,
    provider_key: &str,
) -> AppResult<IntegrationProviderDetailResponse> {
    ensure_user_exists(&state.db, actor_user_id).await?;
    ensure_provider_exists(provider_key)
}

pub async fn create_import_job(
    state: &AppState,
    actor_user_id: Uuid,
    payload: CreateImportJobRequest,
) -> AppResult<IntegrationOperationStubResponse> {
    ensure_user_exists(&state.db, actor_user_id).await?;
    let provider = ensure_provider_exists(&payload.provider_key)?;

    validate_json_object(&payload.options, "options")?;

    Ok(IntegrationOperationStubResponse {
        operation: "import_job.create".to_string(),
        provider_key: provider.provider.key,
        status: "stub_only".to_string(),
        message: "Import orchestration contract is reserved, but concrete provider execution is not implemented yet.".to_string(),
    })
}

pub async fn create_export_job(
    state: &AppState,
    actor_user_id: Uuid,
    payload: CreateExportJobRequest,
) -> AppResult<IntegrationOperationStubResponse> {
    ensure_user_exists(&state.db, actor_user_id).await?;
    let provider = ensure_provider_exists(&payload.provider_key)?;

    validate_json_object(&payload.options, "options")?;

    Ok(IntegrationOperationStubResponse {
        operation: "export_job.create".to_string(),
        provider_key: provider.provider.key,
        status: "stub_only".to_string(),
        message: "Generic provider export jobs are still reserved. Use /integrations/import-export/exports for the real v1 JSON bundle safety net.".to_string(),
    })
}

pub async fn get_import_export_capabilities(
    state: &AppState,
    actor_user_id: Uuid,
) -> AppResult<ImportExportCapabilitiesResponse> {
    ensure_user_exists(&state.db, actor_user_id).await?;
    ensure_provider_exists(IMPORT_EXPORT_PROVIDER_KEY)?;

    Ok(ImportExportCapabilitiesResponse {
        provider_key: IMPORT_EXPORT_PROVIDER_KEY.to_string(),
        format: PORTABLE_BUNDLE_FORMAT.to_string(),
        format_version: PORTABLE_BUNDLE_FORMAT_VERSION,
        supported_export_modes: vec![
            "portable_export".to_string(),
            "backup_snapshot".to_string(),
        ],
        client_only_backup_modes: vec!["local_backup_snapshot".to_string()],
        supported_import_modes: vec![
            "portable_import".to_string(),
            "restore_backup".to_string(),
        ],
        supported_scope_kinds: vec!["workspace".to_string(), "board".to_string()],
        supported_restore_strategies: vec!["create_copy".to_string(), "merge_review".to_string()],
        max_bundle_size_bytes: None,
        notes: vec![
            "Portable export and coordinated backup now return a real versioned JSON bundle for workspace or board scope.".to_string(),
            "The bundle is an application-level snapshot, not a raw database dump and not a sync event replay.".to_string(),
            "Restore/import execution remains non-destructive by default; use preview before any future apply flow.".to_string(),
            "Local backup snapshot is a client-owned offline flow and may include unsynced local-first state.".to_string(),
        ],
    })
}

pub async fn create_portable_export(
    state: &AppState,
    actor_user_id: Uuid,
    payload: CreatePortableExportRequest,
) -> AppResult<PortableExportResponse> {
    ensure_user_exists(&state.db, actor_user_id).await?;
    ensure_provider_exists(IMPORT_EXPORT_PROVIDER_KEY)?;

    validate_export_mode(&payload.export_mode)?;
    validate_scope_kind(&payload.scope_kind)?;

    let (workspace_id, board_id) = resolve_export_scope_access(
        state,
        actor_user_id,
        &payload.scope_kind,
        payload.workspace_id,
        payload.board_id,
    )
    .await?;

    let workspace_id =
        workspace_id.ok_or_else(|| AppError::bad_request("Resolved workspaceId is required"))?;
    let bundle = build_portable_bundle(
        &state.db,
        actor_user_id,
        &payload.scope_kind,
        workspace_id,
        board_id,
        &payload.export_mode,
        payload.include_archived,
        payload.include_activity_history,
        payload.include_appearance,
        payload.include_attachments,
    )
    .await?;

    let manifest = bundle.manifest_json.clone();
    let job_id = Uuid::now_v7();
    let scope_suffix = if let Some(board_id) = board_id {
        format!("board-{board_id}")
    } else {
        format!("workspace-{workspace_id}")
    };
    let suggested_file_name = format!(
        "p2p-planner-{}-{}-{}.bundle.json",
        payload.export_mode.replace('_', "-"),
        scope_suffix,
        job_id
    );

    let mut warnings = Vec::new();
    if payload.include_attachments {
        warnings.push(
            "Attachments are reserved in the bundle manifest, but blob export is not implemented yet; attachment count is always 0.".to_string(),
        );
    }
    if !payload.include_archived {
        warnings.push("Archived cards are excluded unless includeArchived=true.".to_string());
    }

    Ok(PortableExportResponse {
        job_id,
        provider_key: IMPORT_EXPORT_PROVIDER_KEY.to_string(),
        status: "ready".to_string(),
        export_mode: payload.export_mode,
        suggested_file_name,
        target_ref: payload.target_ref,
        bundle_manifest: manifest,
        bundle,
        message: "Portable export bundle is ready. Save the bundle JSON as the backup/export artifact; it is safe to preview repeatedly and does not contain sessions or secrets.".to_string(),
        warnings,
    })
}

pub async fn preview_import_bundle(
    state: &AppState,
    actor_user_id: Uuid,
    payload: CreateImportPreviewRequest,
) -> AppResult<ImportPreviewResponse> {
    ensure_user_exists(&state.db, actor_user_id).await?;
    ensure_provider_exists(IMPORT_EXPORT_PROVIDER_KEY)?;

    validate_import_mode(&payload.import_mode)?;
    validate_restore_strategy(&payload.restore_strategy)?;
    validate_json_object(&payload.bundle_manifest, "bundleManifest")?;
    validate_json_object(&payload.options, "options")?;

    if !payload.bundle.is_null() && !payload.bundle.is_object() {
        return Err(AppError::bad_request("bundle must be a JSON object"));
    }

    if let Some(target_workspace_id) = payload.target_workspace_id {
        require_workspace_access(&state.db, target_workspace_id, actor_user_id).await?;
    }

    let manifest = manifest_from_preview_payload(&payload)?;
    let requires_manual_review = payload.restore_strategy == "merge_review";
    let mut warnings = Vec::new();
    let (status, detected_format, detected_format_version, summary) = if let Some(manifest) =
        manifest
    {
        if manifest.format != PORTABLE_BUNDLE_FORMAT {
            return Err(AppError::bad_request(
                "bundle manifest format is not supported",
            ));
        }
        if manifest.format_version != PORTABLE_BUNDLE_FORMAT_VERSION {
            return Err(AppError::bad_request(
                "bundle manifest formatVersion is not supported",
            ));
        }
        if manifest.includes_local_metadata {
            warnings.push(
                "Bundle contains local metadata; v1 backend preview ignores local-only sections."
                    .to_string(),
            );
        }
        if manifest.summary.includes_attachments {
            warnings.push("Attachment payloads are not restored in v1.".to_string());
        }
        (
            "preview_ready".to_string(),
            manifest.format,
            manifest.format_version,
            manifest.summary,
        )
    } else {
        warnings.push(
            "No bundle manifest was supplied; preview can only return the generic non-destructive plan.".to_string(),
        );
        (
            "preview_needs_bundle".to_string(),
            PORTABLE_BUNDLE_FORMAT.to_string(),
            PORTABLE_BUNDLE_FORMAT_VERSION,
            build_summary("workspace", true, true, true, false),
        )
    };

    if payload.target_workspace_id.is_some() {
        warnings.push(
            "Targeting an existing workspace implies collision review for names, lifecycle state and future field-level conflicts.".to_string(),
        );
    }
    if payload.restore_strategy == "create_copy" {
        warnings.push("create_copy is non-destructive and does not overwrite existing workspace or board state.".to_string());
    }

    Ok(ImportPreviewResponse {
        preview_id: Uuid::now_v7(),
        provider_key: IMPORT_EXPORT_PROVIDER_KEY.to_string(),
        status,
        detected_format,
        detected_format_version,
        import_mode: payload.import_mode,
        restore_strategy: payload.restore_strategy,
        requires_manual_review,
        warnings,
        steps: vec![
            "Read bundle manifest and compatibility metadata".to_string(),
            "Show create-copy or merge-review plan before any apply step".to_string(),
            "Apply validated domain commands instead of raw table writes in a future restore implementation".to_string(),
        ],
        summary,
    })
}

pub async fn create_import_execution(
    state: &AppState,
    actor_user_id: Uuid,
    payload: CreateImportExecutionRequest,
) -> AppResult<ImportExecutionResponse> {
    ensure_user_exists(&state.db, actor_user_id).await?;
    ensure_provider_exists(IMPORT_EXPORT_PROVIDER_KEY)?;

    validate_import_mode(&payload.import_mode)?;
    validate_restore_strategy(&payload.restore_strategy)?;
    validate_json_object(&payload.bundle_manifest, "bundleManifest")?;
    validate_json_object(&payload.options, "options")?;

    if let Some(target_workspace_id) = payload.target_workspace_id {
        require_workspace_access(&state.db, target_workspace_id, actor_user_id).await?;
    }

    Ok(ImportExecutionResponse {
        job_id: Uuid::now_v7(),
        provider_key: IMPORT_EXPORT_PROVIDER_KEY.to_string(),
        status: "preview_required".to_string(),
        import_mode: payload.import_mode,
        restore_strategy: payload.restore_strategy,
        preview_id: payload.preview_id,
        target_workspace_id: payload.target_workspace_id,
        message: "Destructive restore is intentionally not implemented in v1. Use import preview for a non-destructive create-copy plan; future apply must go through validated domain commands.".to_string(),
        warnings: vec![
            "This endpoint does not mutate domain state in the v1 safety-net baseline.".to_string(),
            "No sessions, tokens, provider secrets or device identities are restored from bundles.".to_string(),
        ],
    })
}

pub async fn receive_webhook(provider_key: &str) -> AppResult<WebhookReceiptResponse> {
    let provider = ensure_provider_exists(provider_key)?;

    let accepted_event_types = provider
        .inbound_webhook
        .as_ref()
        .map(|contract| contract.event_types.clone())
        .unwrap_or_default();

    Ok(WebhookReceiptResponse {
        provider_key: provider.provider.key,
        status: "stub_only".to_string(),
        message: "Webhook boundary is reserved, but signature verification and command translation are not implemented yet.".to_string(),
        accepted_event_types,
    })
}

pub(crate) async fn build_portable_bundle(
    pool: &PgPool,
    actor_user_id: Uuid,
    scope_kind: &str,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    export_mode: &str,
    include_archived: bool,
    include_activity_history: bool,
    include_appearance: bool,
    include_attachments: bool,
) -> AppResult<PortableBundle> {
    let summary = count_export_entities(
        pool,
        scope_kind,
        workspace_id,
        board_id,
        include_archived,
        include_activity_history,
        include_appearance,
        include_attachments,
    )
    .await?;

    let manifest = PortableBundleManifest {
        format: PORTABLE_BUNDLE_FORMAT.to_string(),
        format_version: PORTABLE_BUNDLE_FORMAT_VERSION,
        bundle_kind: export_mode.to_string(),
        scope_kind: scope_kind.to_string(),
        workspace_id: Some(workspace_id),
        board_id,
        includes_local_metadata: false,
        summary: summary.clone(),
    };

    let generated_at = utc_now_string(pool).await?;
    let payload = PortableBundlePayload {
        workspaces: export_workspaces(pool, workspace_id).await?,
        boards: export_boards(pool, workspace_id, board_id, include_archived).await?,
        columns: export_columns(pool, workspace_id, board_id, include_archived).await?,
        cards: export_cards(pool, workspace_id, board_id, include_archived).await?,
        labels: export_labels(pool, workspace_id, board_id, include_archived).await?,
        card_labels: export_card_labels(pool, workspace_id, board_id, include_archived).await?,
        checklists: export_checklists(pool, workspace_id, board_id, include_archived).await?,
        checklist_items: export_checklist_items(pool, workspace_id, board_id, include_archived)
            .await?,
        comments: export_comments(pool, workspace_id, board_id, include_archived).await?,
        board_appearance_settings: if include_appearance {
            export_board_appearance(pool, workspace_id, board_id, include_archived).await?
        } else {
            json!([])
        },
        activity_entries: if include_activity_history {
            export_activity_entries(pool, workspace_id, board_id, include_archived).await?
        } else {
            json!([])
        },
    };

    Ok(PortableBundle {
        manifest_json: manifest,
        scope: PortableBundleScope {
            scope_kind: scope_kind.to_string(),
            workspace_id: Some(workspace_id),
            board_id,
        },
        origin: PortableBundleOrigin {
            exported_by_user_id: actor_user_id,
            generated_at,
            backend_visible_state: true,
        },
        includes: PortableBundleIncludes {
            appearance: include_appearance,
            activity_history: include_activity_history,
            archived: include_archived,
            attachments: include_attachments,
            local_metadata: false,
        },
        payload,
        restore_hints: PortableBundleRestoreHints {
            recommended_strategy: "create_copy".to_string(),
            requires_manual_review: false,
            destructive_restore_allowed: false,
            notes: vec![
                "Preview this bundle before restore/import.".to_string(),
                "v1 restore must create a copy or require explicit merge review; it must not overwrite existing data silently.".to_string(),
            ],
        },
    })
}

async fn count_export_entities(
    pool: &PgPool,
    scope_kind: &str,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
    include_activity_history: bool,
    include_appearance: bool,
    include_attachments: bool,
) -> AppResult<PortableBundleSummary> {
    let board_count = count_for_scope(
        pool,
        r#"
        select count(*)::bigint
        from boards b
        where b.workspace_id = $1
          and b.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
        workspace_id,
        board_id,
        include_archived,
    )
    .await?;
    let column_count = count_for_scope(
        pool,
        r#"
        select count(*)::bigint
        from board_columns c
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
        workspace_id,
        board_id,
        include_archived,
    )
    .await?;
    let card_count = count_for_scope(
        pool,
        r#"
        select count(*)::bigint
        from cards c
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or c.archived_at is null)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
        workspace_id,
        board_id,
        include_archived,
    )
    .await?;
    let checklist_count = count_for_scope(
        pool,
        r#"
        select count(*)::bigint
        from checklists ch
        join cards c on c.id = ch.card_id
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and ch.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or c.archived_at is null)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
        workspace_id,
        board_id,
        include_archived,
    )
    .await?;
    let comment_count = count_for_scope(
        pool,
        r#"
        select count(*)::bigint
        from comments cm
        join cards c on c.id = cm.card_id
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and cm.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or c.archived_at is null)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
        workspace_id,
        board_id,
        include_archived,
    )
    .await?;

    Ok(PortableBundleSummary {
        scope_kind: scope_kind.to_string(),
        entity_counts: PortableEntityCounts {
            workspaces: 1,
            boards: to_count_i32(board_count),
            columns: to_count_i32(column_count),
            cards: to_count_i32(card_count),
            comments: to_count_i32(comment_count),
            checklists: to_count_i32(checklist_count),
            attachments: 0,
        },
        includes_activity_history: include_activity_history,
        includes_appearance: include_appearance,
        includes_archived: include_archived,
        includes_attachments: include_attachments,
    })
}

async fn count_for_scope(
    pool: &PgPool,
    sql: &str,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<i64> {
    Ok(sqlx::query_scalar::<_, i64>(sql)
        .bind(workspace_id)
        .bind(board_id)
        .bind(include_archived)
        .fetch_one(pool)
        .await?)
}

fn to_count_i32(value: i64) -> i32 {
    value.clamp(0, i32::MAX as i64) as i32
}

async fn utc_now_string(pool: &PgPool) -> AppResult<String> {
    Ok(sqlx::query_scalar::<_, String>(
        r#"select to_char(now() at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')"#,
    )
    .fetch_one(pool)
    .await?)
}

async fn export_workspaces(pool: &PgPool, workspace_id: Uuid) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', w.id,
          'name', w.name,
          'slug', w.slug,
          'description', w.description,
          'visibility', w.visibility,
          'ownerUserId', w.owner_user_id,
          'createdAt', to_char(w.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(w.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'archivedAt', case when w.archived_at is null then null else to_char(w.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end
        ) order by w.created_at, w.id), '[]'::jsonb)
        from workspaces w
        where w.id = $1 and w.deleted_at is null
        "#,
    )
    .bind(workspace_id)
    .fetch_one(pool)
    .await?)
}

async fn export_boards(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', b.id,
          'workspaceId', b.workspace_id,
          'name', b.name,
          'description', b.description,
          'boardType', b.board_type,
          'createdByUserId', b.created_by_user_id,
          'createdAt', to_char(b.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(b.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'archivedAt', case when b.archived_at is null then null else to_char(b.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end
        ) order by b.created_at, b.id), '[]'::jsonb)
        from boards b
        where b.workspace_id = $1
          and b.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_columns(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', c.id,
          'boardId', c.board_id,
          'name', c.name,
          'description', c.description,
          'position', c.position::double precision,
          'colorToken', c.color_token,
          'wipLimit', c.wip_limit,
          'createdAt', to_char(c.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(c.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        ) order by c.board_id, c.position, c.id), '[]'::jsonb)
        from board_columns c
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_cards(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', c.id,
          'boardId', c.board_id,
          'columnId', c.column_id,
          'parentCardId', c.parent_card_id,
          'title', c.title,
          'description', c.description,
          'position', c.position::double precision,
          'priority', c.priority,
          'startAt', case when c.start_at is null then null else to_char(c.start_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end,
          'dueAt', case when c.due_at is null then null else to_char(c.due_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end,
          'createdByUserId', c.created_by_user_id,
          'createdAt', to_char(c.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(c.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'archivedAt', case when c.archived_at is null then null else to_char(c.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end
        ) order by c.board_id, c.column_id, c.position, c.id), '[]'::jsonb)
        from cards c
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or c.archived_at is null)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_labels(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', l.id,
          'boardId', l.board_id,
          'name', l.name,
          'color', l.color,
          'description', l.description,
          'createdAt', to_char(l.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(l.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        ) order by l.board_id, l.name, l.id), '[]'::jsonb)
        from board_labels l
        join boards b on b.id = l.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and l.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_card_labels(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', cl.id,
          'boardId', cl.board_id,
          'cardId', cl.card_id,
          'labelId', cl.label_id,
          'createdAt', to_char(cl.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        ) order by cl.board_id, cl.card_id, cl.label_id), '[]'::jsonb)
        from card_labels cl
        join cards c on c.id = cl.card_id
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and cl.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or c.archived_at is null)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_checklists(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', ch.id,
          'cardId', ch.card_id,
          'title', ch.title,
          'position', ch.position::double precision,
          'createdAt', to_char(ch.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(ch.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        ) order by c.board_id, ch.card_id, ch.position, ch.id), '[]'::jsonb)
        from checklists ch
        join cards c on c.id = ch.card_id
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and ch.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or c.archived_at is null)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_checklist_items(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', ci.id,
          'checklistId', ci.checklist_id,
          'title', ci.title,
          'isDone', ci.is_done,
          'position', ci.position::double precision,
          'dueAt', case when ci.due_at is null then null else to_char(ci.due_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end,
          'completedAt', case when ci.completed_at is null then null else to_char(ci.completed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end,
          'createdAt', to_char(ci.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(ci.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        ) order by c.board_id, ci.checklist_id, ci.position, ci.id), '[]'::jsonb)
        from checklist_items ci
        join checklists ch on ch.id = ci.checklist_id
        join cards c on c.id = ch.card_id
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and ch.deleted_at is null
          and ci.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or c.archived_at is null)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_comments(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', cm.id,
          'cardId', cm.card_id,
          'authorUserId', cm.author_user_id,
          'body', cm.body,
          'createdAt', to_char(cm.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(cm.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        ) order by c.board_id, cm.card_id, cm.created_at, cm.id), '[]'::jsonb)
        from comments cm
        join cards c on c.id = cm.card_id
        join boards b on b.id = c.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and c.deleted_at is null
          and cm.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or c.archived_at is null)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_board_appearance(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'boardId', a.board_id,
          'themePreset', a.theme_preset,
          'wallpaperKind', a.wallpaper_kind,
          'wallpaperValue', a.wallpaper_value,
          'columnDensity', a.column_density,
          'cardPreviewMode', a.card_preview_mode,
          'showCardDescription', a.show_card_description,
          'showCardDates', a.show_card_dates,
          'showChecklistProgress', a.show_checklist_progress,
          'customProperties', a.custom_properties_jsonb,
          'createdAt', to_char(a.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
          'updatedAt', to_char(a.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        ) order by a.board_id), '[]'::jsonb)
        from board_appearance_settings a
        join boards b on b.id = a.board_id
        where b.workspace_id = $1
          and b.deleted_at is null
          and ($2::uuid is null or b.id = $2)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

async fn export_activity_entries(
    pool: &PgPool,
    workspace_id: Uuid,
    board_id: Option<Uuid>,
    include_archived: bool,
) -> AppResult<Value> {
    Ok(sqlx::query_scalar::<_, Value>(
        r#"
        select coalesce(jsonb_agg(jsonb_build_object(
          'id', ae.id,
          'workspaceId', ae.workspace_id,
          'boardId', ae.board_id,
          'cardId', ae.card_id,
          'actorUserId', ae.actor_user_id,
          'kind', ae.kind,
          'entityType', ae.entity_type,
          'entityId', ae.entity_id,
          'fieldMask', ae.field_mask,
          'payload', ae.payload_jsonb,
          'createdAt', to_char(ae.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
        ) order by ae.created_at, ae.id), '[]'::jsonb)
        from activity_entries ae
        join boards b on b.id = ae.board_id
        where ae.workspace_id = $1
          and b.deleted_at is null
          and ($2::uuid is null or ae.board_id = $2)
          and ($3::bool = true or $2::uuid is not null or b.archived_at is null)
        "#,
    )
    .bind(workspace_id)
    .bind(board_id)
    .bind(include_archived)
    .fetch_one(pool)
    .await?)
}

fn manifest_from_preview_payload(
    payload: &CreateImportPreviewRequest,
) -> AppResult<Option<PortableBundleManifest>> {
    let manifest_value = if is_non_empty_object(&payload.bundle_manifest) {
        Some(payload.bundle_manifest.clone())
    } else if let Some(value) = payload.bundle.get("manifest.json") {
        Some(value.clone())
    } else {
        payload.bundle.get("manifestJson").cloned()
    };

    match manifest_value {
        Some(value) => serde_json::from_value::<PortableBundleManifest>(value)
            .map(Some)
            .map_err(|_| AppError::bad_request("bundle manifest has invalid shape")),
        None => Ok(None),
    }
}

fn is_non_empty_object(value: &Value) -> bool {
    value
        .as_object()
        .map(|object| !object.is_empty())
        .unwrap_or(false)
}

fn validate_json_object(value: &Value, field_name: &str) -> AppResult<()> {
    if value.is_null() || value.is_object() {
        Ok(())
    } else {
        Err(AppError::bad_request(format!(
            "{field_name} must be a JSON object"
        )))
    }
}

fn validate_export_mode(value: &str) -> AppResult<()> {
    match value {
        "portable_export" | "backup_snapshot" => Ok(()),
        _ => Err(AppError::bad_request(
            "exportMode has unsupported value; expected portable_export or backup_snapshot",
        )),
    }
}

fn validate_import_mode(value: &str) -> AppResult<()> {
    match value {
        "portable_import" | "restore_backup" => Ok(()),
        _ => Err(AppError::bad_request(
            "importMode has unsupported value; expected portable_import or restore_backup",
        )),
    }
}

fn validate_restore_strategy(value: &str) -> AppResult<()> {
    match value {
        "create_copy" | "merge_review" => Ok(()),
        _ => Err(AppError::bad_request(
            "restoreStrategy has unsupported value; expected create_copy or merge_review",
        )),
    }
}

fn validate_scope_kind(value: &str) -> AppResult<()> {
    match value {
        "workspace" | "board" => Ok(()),
        _ => Err(AppError::bad_request(
            "scopeKind has unsupported value; expected workspace or board",
        )),
    }
}

async fn resolve_export_scope_access(
    state: &AppState,
    actor_user_id: Uuid,
    scope_kind: &str,
    workspace_id: Option<Uuid>,
    board_id: Option<Uuid>,
) -> AppResult<(Option<Uuid>, Option<Uuid>)> {
    match scope_kind {
        "workspace" => {
            let workspace_id = workspace_id.ok_or_else(|| {
                AppError::bad_request("workspaceId is required when scopeKind=workspace")
            })?;
            require_workspace_access(&state.db, workspace_id, actor_user_id).await?;
            Ok((Some(workspace_id), None))
        }
        "board" => {
            let board_id = board_id
                .ok_or_else(|| AppError::bad_request("boardId is required when scopeKind=board"))?;
            let workspace_id = board_workspace_id(&state.db, board_id).await?;
            require_workspace_access(&state.db, workspace_id, actor_user_id).await?;
            Ok((Some(workspace_id), Some(board_id)))
        }
        _ => Err(AppError::bad_request(
            "scopeKind has unsupported value; expected workspace or board",
        )),
    }
}

fn build_summary(
    scope_kind: &str,
    includes_activity_history: bool,
    includes_appearance: bool,
    includes_archived: bool,
    includes_attachments: bool,
) -> PortableBundleSummary {
    PortableBundleSummary {
        scope_kind: scope_kind.to_string(),
        entity_counts: PortableEntityCounts {
            workspaces: 0,
            boards: 0,
            columns: 0,
            cards: 0,
            comments: 0,
            checklists: 0,
            attachments: 0,
        },
        includes_activity_history,
        includes_appearance,
        includes_archived,
        includes_attachments,
    }
}
