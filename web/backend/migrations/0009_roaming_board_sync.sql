create table if not exists roaming_board_outbox (
  id uuid primary key,
  source_key text not null unique,
  source_activity_id uuid null references activity_entries(id) on delete set null,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  board_id uuid not null references boards(id) on delete cascade,
  card_id uuid not null references cards(id) on delete cascade,
  event_seq bigint generated always as identity,
  status text not null default 'pending',
  attempt_count integer not null default 0,
  next_attempt_at timestamptz not null default now(),
  nostr_event_id text null,
  last_error text null,
  created_at timestamptz not null default now(),
  delivered_at timestamptz null,
  constraint uq_roaming_board_outbox_seq unique (event_seq),
  constraint chk_roaming_board_outbox_status check (
    status in ('pending', 'processing', 'retry', 'delivered', 'dead_letter')
  )
);

create index if not exists idx_roaming_board_outbox_ready
  on roaming_board_outbox (status, next_attempt_at, event_seq)
  where status in ('pending', 'retry');

create table if not exists roaming_board_events (
  event_id uuid primary key,
  nostr_event_id text not null,
  author_public_key text not null,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  board_id uuid not null references boards(id) on delete cascade,
  replica_id uuid not null,
  replica_seq bigint not null,
  logical_clock bigint not null,
  entity_id uuid not null,
  operation text not null,
  status text not null,
  error text null,
  received_at timestamptz not null default now(),
  applied_at timestamptz null,
  constraint uq_roaming_board_events_nostr unique (nostr_event_id),
  constraint uq_roaming_board_events_replica_seq unique (replica_id, replica_seq),
  constraint chk_roaming_board_events_status check (
    status in ('applied', 'duplicate', 'rejected')
  )
);

create index if not exists idx_roaming_board_events_scope_clock
  on roaming_board_events (workspace_id, board_id, logical_clock);

create table if not exists roaming_field_versions (
  workspace_id uuid not null references workspaces(id) on delete cascade,
  entity_id uuid not null,
  field_name text not null,
  logical_clock bigint not null,
  replica_id uuid not null,
  event_id uuid not null references roaming_board_events(event_id) on delete cascade,
  updated_at timestamptz not null default now(),
  primary key (workspace_id, entity_id, field_name)
);

create or replace function enqueue_roaming_card_activity()
returns trigger language plpgsql as $$
begin
  if new.entity_type = 'card' and new.card_id is not null then
    insert into roaming_board_outbox (
      id,
      source_key,
      source_activity_id,
      workspace_id,
      board_id,
      card_id
    ) values (
      gen_random_uuid(),
      'activity:' || new.id::text,
      new.id,
      new.workspace_id,
      new.board_id,
      new.card_id
    )
    on conflict (source_key) do nothing;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_activity_roaming_outbox on activity_entries;
create trigger trg_activity_roaming_outbox
after insert on activity_entries
for each row execute function enqueue_roaming_card_activity();
