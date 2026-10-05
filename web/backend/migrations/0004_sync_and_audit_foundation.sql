create table if not exists replicas (
  id uuid primary key,
  user_id uuid null references users(id) on delete set null,
  device_id uuid null references devices(id) on delete set null,
  replica_kind text not null default 'client',
  client_instance_key text null,
  display_name text null,
  platform text null,
  protocol_version text null,
  app_version text null,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz null,
  revoked_at timestamptz null,
  constraint chk_replicas_kind check (replica_kind in ('client', 'server', 'import'))
);

create unique index if not exists uq_replicas_device_client_key
  on replicas (device_id, client_instance_key)
  where device_id is not null and client_instance_key is not null;

create index if not exists idx_replicas_user_created
  on replicas (user_id, created_at desc);

create index if not exists idx_replicas_last_seen
  on replicas (last_seen_at desc nulls last);

create table if not exists change_events (
  id uuid primary key,
  server_order bigint generated always as identity,
  workspace_id uuid null references workspaces(id) on delete set null,
  replica_id uuid not null references replicas(id) on delete restrict,
  device_id uuid null references devices(id) on delete set null,
  actor_user_id uuid null references users(id) on delete set null,
  entity_type text not null,
  entity_id uuid not null,
  operation text not null,
  field_mask text[] not null default '{}',
  payload_jsonb jsonb not null default '{}'::jsonb,
  metadata_jsonb jsonb not null default '{}'::jsonb,
  lamport bigint not null,
  replica_seq bigint not null,
  base_server_order bigint null,
  occurred_at timestamptz null,
  received_at timestamptz not null default now(),
  applied_at timestamptz null,
  status text not null default 'applied',
  rejection_code text null,
  correlation_id uuid null,
  causation_id uuid null,
  constraint uq_change_events_server_order unique (server_order),
  constraint uq_change_events_replica_seq unique (replica_id, replica_seq),
  constraint chk_change_events_operation check (operation in ('create', 'update', 'delete', 'restore', 'reorder', 'add', 'remove', 'archive', 'unarchive')),
  constraint chk_change_events_status check (status in ('accepted', 'applied', 'duplicate', 'rejected', 'conflict')),
  constraint chk_change_events_lamport check (lamport > 0),
  constraint chk_change_events_replica_seq_positive check (replica_seq > 0)
);

create index if not exists idx_change_events_workspace_server_order
  on change_events (workspace_id, server_order);

create index if not exists idx_change_events_entity_server_order
  on change_events (entity_type, entity_id, server_order desc);

create index if not exists idx_change_events_status_received
  on change_events (status, received_at desc);

create index if not exists idx_change_events_payload_gin
  on change_events using gin (payload_jsonb);

create table if not exists sync_cursors (
  id uuid primary key,
  replica_id uuid not null references replicas(id) on delete cascade,
  cursor_scope text not null,
  scope_id uuid null,
  last_server_order bigint not null default 0,
  last_event_received_at timestamptz null,
  updated_at timestamptz not null default now(),
  constraint chk_sync_cursors_scope check (cursor_scope in ('global', 'workspace')),
  constraint chk_sync_cursors_scope_shape check (
    (cursor_scope = 'global' and scope_id is null)
    or
    (cursor_scope = 'workspace' and scope_id is not null)
  ),
  constraint chk_sync_cursors_last_server_order check (last_server_order >= 0)
);

create unique index if not exists uq_sync_cursors_global
  on sync_cursors (replica_id, cursor_scope)
  where cursor_scope = 'global' and scope_id is null;

create unique index if not exists uq_sync_cursors_workspace
  on sync_cursors (replica_id, cursor_scope, scope_id)
  where cursor_scope = 'workspace' and scope_id is not null;

create index if not exists idx_sync_cursors_replica_updated
  on sync_cursors (replica_id, updated_at desc);

create index if not exists idx_sync_cursors_scope
  on sync_cursors (cursor_scope, scope_id);

create table if not exists tombstones (
  id uuid primary key,
  workspace_id uuid null references workspaces(id) on delete set null,
  entity_type text not null,
  entity_id uuid not null,
  delete_event_id uuid null references change_events(id) on delete set null,
  deleted_by_user_id uuid null references users(id) on delete set null,
  deleted_by_replica_id uuid null references replicas(id) on delete set null,
  deleted_at timestamptz not null,
  purge_after_at timestamptz null,
  metadata_jsonb jsonb not null default '{}'::jsonb,
  constraint uq_tombstones_entity unique (entity_type, entity_id)
);

create index if not exists idx_tombstones_workspace_deleted
  on tombstones (workspace_id, deleted_at desc);

create index if not exists idx_tombstones_purge_after
  on tombstones (purge_after_at)
  where purge_after_at is not null;

create table if not exists audit_log (
  id uuid primary key,
  workspace_id uuid null references workspaces(id) on delete set null,
  actor_user_id uuid null references users(id) on delete set null,
  actor_device_id uuid null references devices(id) on delete set null,
  actor_replica_id uuid null references replicas(id) on delete set null,
  action_type text not null,
  target_entity_type text null,
  target_entity_id uuid null,
  request_id uuid null,
  metadata_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_audit_log_workspace_created
  on audit_log (workspace_id, created_at desc);

create index if not exists idx_audit_log_target_created
  on audit_log (target_entity_type, target_entity_id, created_at desc);

create index if not exists idx_audit_log_actor_created
  on audit_log (actor_user_id, created_at desc);