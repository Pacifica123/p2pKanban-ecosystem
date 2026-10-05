-- Workspace collaboration v2 has three roles and a coordinator-owned access
-- generation. Any membership mutation advances the generation so stale
-- offline/relay writes and previously issued board capabilities can be rejected.

alter table workspace_members drop constraint if exists chk_workspace_members_role;

update workspace_members
set role = case
  when role = 'owner' then 'owner'
  when role in ('admin', 'member') then 'member'
  else 'guest'
end;

alter table workspace_members
  add constraint chk_workspace_members_role
  check (role in ('owner', 'member', 'guest'));

alter table workspaces
  add column if not exists access_epoch bigint not null default 1;

alter table workspaces
  add constraint chk_workspaces_access_epoch check (access_epoch > 0);

create table if not exists workspace_invitations (
  id uuid primary key,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  token_hash text not null unique,
  role text not null,
  created_by_user_id uuid not null references users(id) on delete restrict,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz null,
  revoked_by_user_id uuid null references users(id) on delete set null,
  accepted_at timestamptz null,
  accepted_by_user_id uuid null references users(id) on delete set null,
  constraint chk_workspace_invitations_role check (role in ('member', 'guest')),
  constraint chk_workspace_invitations_expiry check (expires_at > created_at),
  constraint chk_workspace_invitations_terminal_state check (
    not (revoked_at is not null and accepted_at is not null)
  )
);

create index if not exists idx_workspace_invitations_workspace_created
  on workspace_invitations (workspace_id, created_at desc);

create index if not exists idx_workspace_invitations_active_expiry
  on workspace_invitations (workspace_id, expires_at)
  where revoked_at is null and accepted_at is null;

alter table roaming_board_capabilities
  add column if not exists capability_epoch bigint not null default 1;

alter table roaming_board_capabilities
  add constraint chk_roaming_board_capabilities_epoch check (capability_epoch > 0);

update roaming_board_capabilities rbc
set capability_epoch = w.access_epoch
from boards b
join workspaces w on w.id = b.workspace_id
where rbc.board_id = b.id;

create table if not exists roaming_board_authorizations (
  id uuid primary key,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  board_id uuid not null references boards(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  device_id uuid null references devices(id) on delete cascade,
  author_public_key text not null,
  role text not null,
  capability_epoch bigint not null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz null,
  constraint chk_roaming_board_authorizations_role check (role in ('owner', 'member', 'guest')),
  constraint chk_roaming_board_authorizations_epoch check (capability_epoch > 0),
  constraint chk_roaming_board_authorizations_key check (btrim(author_public_key) <> '')
);

create unique index if not exists uq_roaming_board_authorizations_active_key
  on roaming_board_authorizations (board_id, author_public_key)
  where revoked_at is null;

create index if not exists idx_roaming_board_authorizations_workspace_epoch
  on roaming_board_authorizations (workspace_id, capability_epoch)
  where revoked_at is null;

alter table roaming_board_events
  add column if not exists capability_epoch bigint not null default 1;

alter table roaming_board_events
  add column if not exists actor_user_id uuid null references users(id) on delete set null;

alter table roaming_board_events
  add constraint chk_roaming_board_events_capability_epoch check (capability_epoch > 0);

update replicas
set app_version = '1.0.0'
where id in (select replica_id from local_node_identity)
  and replica_kind = 'server';
