create table if not exists sync_transport_outbox (
  id uuid primary key,
  change_event_id uuid not null references change_events(id) on delete cascade,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  transport text not null,
  status text not null default 'pending',
  attempt_count integer not null default 0,
  next_attempt_at timestamptz not null default now(),
  lease_until timestamptz null,
  remote_event_id text null,
  last_error text null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  delivered_at timestamptz null,
  constraint uq_sync_transport_outbox_event_transport unique (change_event_id, transport),
  constraint chk_sync_transport_outbox_transport check (transport in ('nostr')),
  constraint chk_sync_transport_outbox_status check (
    status in ('pending', 'processing', 'retry', 'delivered', 'dead_letter')
  ),
  constraint chk_sync_transport_outbox_attempt_count check (attempt_count >= 0)
);

create index if not exists idx_sync_transport_outbox_ready
  on sync_transport_outbox (transport, next_attempt_at, created_at)
  where status in ('pending', 'retry');

create index if not exists idx_sync_transport_outbox_workspace_status
  on sync_transport_outbox (workspace_id, transport, status);

create index if not exists idx_sync_transport_outbox_lease
  on sync_transport_outbox (lease_until)
  where status = 'processing';

-- Enqueue in the same transaction that accepts the canonical change event.
-- When the worker is disabled, pending rows form a safe future backfill.
create or replace function enqueue_sync_event_for_nostr()
returns trigger
language plpgsql
as $$
begin
  if new.workspace_id is not null then
    insert into sync_transport_outbox (
      id, change_event_id, workspace_id, transport, status
    )
    values (
      gen_random_uuid(), new.id, new.workspace_id, 'nostr', 'pending'
    )
    on conflict (change_event_id, transport) do nothing;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_change_events_nostr_outbox on change_events;

create trigger trg_change_events_nostr_outbox
after insert on change_events
for each row execute function enqueue_sync_event_for_nostr();
