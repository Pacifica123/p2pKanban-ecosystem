create table if not exists roaming_board_settings_outbox (
  id uuid primary key,
  source_key text not null unique,
  source_activity_id uuid null references activity_entries(id) on delete set null,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  board_id uuid not null references boards(id) on delete cascade,
  event_seq bigint generated always as identity,
  status text not null default 'pending',
  attempt_count integer not null default 0,
  next_attempt_at timestamptz not null default now(),
  nostr_event_id text null,
  last_error text null,
  created_at timestamptz not null default now(),
  delivered_at timestamptz null,
  constraint uq_roaming_board_settings_outbox_seq unique (event_seq),
  constraint chk_roaming_board_settings_outbox_status check (
    status in ('pending', 'processing', 'retry', 'delivered', 'dead_letter')
  )
);

create index if not exists idx_roaming_board_settings_outbox_ready
  on roaming_board_settings_outbox (status, next_attempt_at, event_seq)
  where status in ('pending', 'retry');

create or replace function enqueue_roaming_board_settings_activity()
returns trigger language plpgsql as $$
begin
  if coalesce(new.payload_jsonb ->> 'source', '') = 'roaming' then
    return new;
  end if;

  if new.entity_type = 'board' and new.kind = 'board.appearance.updated' then
    insert into roaming_board_settings_outbox (
      id, source_key, source_activity_id, workspace_id, board_id
    ) values (
      gen_random_uuid(),
      'appearance-activity:' || new.id::text,
      new.id,
      new.workspace_id,
      new.board_id
    )
    on conflict (source_key) do nothing;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_activity_roaming_board_settings_outbox on activity_entries;
create trigger trg_activity_roaming_board_settings_outbox
after insert on activity_entries
for each row execute function enqueue_roaming_board_settings_activity();

-- Publish existing customized board settings once after upgrade so a mobile
-- client does not depend on reaching the coordinator to catch up.
insert into roaming_board_settings_outbox (
  id, source_key, workspace_id, board_id
)
select
  gen_random_uuid(),
  'appearance-backfill:' || a.board_id::text || ':' || extract(epoch from a.updated_at)::bigint::text,
  b.workspace_id,
  a.board_id
from board_appearance_settings a
join boards b on b.id = a.board_id
where b.deleted_at is null
on conflict (source_key) do nothing;
