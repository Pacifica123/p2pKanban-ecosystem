-- Card deletion has two deliberately different scopes:
--   * local_card_hides is node-local presentation state and never enters roaming;
--   * tombstones are durable, sync-visible facts and always win over stale card.put.

insert into replicas (
  id, replica_kind, display_name, platform, protocol_version, app_version
)
select
  replica_id,
  'server',
  'Local web node',
  'backend',
  'p2p-kanban-roaming/1',
  '1.0.0-beta.8'
from local_node_identity
on conflict (id) do update set
  replica_kind = 'server',
  protocol_version = excluded.protocol_version,
  app_version = excluded.app_version;

create table if not exists local_card_hides (
  node_replica_id uuid not null references local_node_identity(replica_id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  card_id uuid not null references cards(id) on delete cascade,
  hidden_at timestamptz not null default now(),
  primary key (node_replica_id, user_id, card_id)
);

create index if not exists idx_local_card_hides_user_hidden
  on local_card_hides (user_id, hidden_at desc);

-- Repair deletions made by older builds. They had deleted_at but no protocol
-- tombstone, which allowed another replica to retain or resurrect the card.
insert into tombstones (
  id,
  workspace_id,
  entity_type,
  entity_id,
  deleted_by_user_id,
  deleted_by_replica_id,
  deleted_at,
  metadata_jsonb
)
select
  gen_random_uuid(),
  b.workspace_id,
  'card',
  c.id,
  null,
  n.replica_id,
  c.deleted_at,
  jsonb_build_object(
    'boardId', c.board_id,
    'cardTitle', c.title,
    'scope', 'all_devices',
    'source', 'migration_0014'
  )
from cards c
join boards b on b.id = c.board_id
cross join local_node_identity n
where c.deleted_at is not null
on conflict (entity_type, entity_id) do update set
  deleted_at = greatest(tombstones.deleted_at, excluded.deleted_at),
  metadata_jsonb = tombstones.metadata_jsonb || excluded.metadata_jsonb;

insert into roaming_board_outbox (
  id,
  source_key,
  workspace_id,
  board_id,
  card_id
)
select
  gen_random_uuid(),
  'tombstone-backfill:' || t.entity_id::text || ':'
    || floor(extract(epoch from t.deleted_at) * 1000)::bigint::text,
  t.workspace_id,
  c.board_id,
  c.id
from tombstones t
join cards c on c.id = t.entity_id
where t.entity_type = 'card'
  and t.workspace_id is not null
on conflict (source_key) do nothing;
