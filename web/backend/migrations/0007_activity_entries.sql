create table if not exists activity_entries (
  id uuid primary key,
  workspace_id uuid not null references workspaces(id) on delete restrict,
  board_id uuid not null references boards(id) on delete restrict,
  card_id uuid null references cards(id) on delete restrict,
  actor_user_id uuid null references users(id) on delete set null,
  kind text not null,
  entity_type text not null,
  entity_id uuid not null,
  field_mask text[] not null default '{}',
  payload_jsonb jsonb not null default '{}'::jsonb,
  request_id uuid null,
  source_change_event_id uuid null references change_events(id) on delete set null,
  source_audit_log_id uuid null references audit_log(id) on delete set null,
  created_at timestamptz not null default now(),
  constraint chk_activity_entries_entity_type check (entity_type in (
    'workspace',
    'workspace_member',
    'board',
    'column',
    'card',
    'comment',
    'checklist',
    'checklist_item'
  ))
);

create index if not exists idx_activity_entries_workspace_created
  on activity_entries (workspace_id, created_at desc, id desc);

create index if not exists idx_activity_entries_board_created
  on activity_entries (board_id, created_at desc, id desc);

create index if not exists idx_activity_entries_card_created
  on activity_entries (card_id, created_at desc, id desc)
  where card_id is not null;

create index if not exists idx_activity_entries_actor_created
  on activity_entries (actor_user_id, created_at desc, id desc)
  where actor_user_id is not null;

create index if not exists idx_activity_entries_kind_created
  on activity_entries (kind, created_at desc, id desc);
