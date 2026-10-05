create table if not exists users (
  id uuid primary key,
  email text not null,
  username text null,
  display_name text not null,
  password_hash text null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz null
);

create unique index if not exists uq_users_email_active
  on users ((lower(email)))
  where deleted_at is null;

create unique index if not exists uq_users_username_active
  on users ((lower(username)))
  where username is not null and deleted_at is null;

create trigger trg_users_updated_at
before update on users
for each row execute function set_row_updated_at();

create table if not exists devices (
  id uuid primary key,
  user_id uuid not null references users(id) on delete restrict,
  display_name text not null,
  platform text not null,
  public_key text null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_seen_at timestamptz null,
  revoked_at timestamptz null,
  deleted_at timestamptz null
);

create index if not exists idx_devices_user_active
  on devices (user_id)
  where deleted_at is null;

create index if not exists idx_devices_user_last_seen
  on devices (user_id, last_seen_at desc nulls last);

create trigger trg_devices_updated_at
before update on devices
for each row execute function set_row_updated_at();

create table if not exists user_sessions (
  id uuid primary key,
  user_id uuid not null references users(id) on delete restrict,
  device_id uuid null references devices(id) on delete set null,
  refresh_token_hash text not null,
  user_agent text null,
  ip_address inet null,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz null,
  expires_at timestamptz not null,
  revoked_at timestamptz null,
  constraint chk_user_sessions_expiry check (expires_at > created_at)
);

create unique index if not exists uq_user_sessions_refresh_hash_active
  on user_sessions (refresh_token_hash)
  where revoked_at is null;

create index if not exists idx_user_sessions_user_expires
  on user_sessions (user_id, expires_at);

create table if not exists workspaces (
  id uuid primary key,
  name text not null,
  slug text null,
  description text null,
  owner_user_id uuid not null references users(id) on delete restrict,
  visibility text not null default 'private',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz null,
  deleted_at timestamptz null,
  constraint chk_workspaces_visibility check (visibility in ('private', 'shared', 'public_readonly'))
);

create unique index if not exists uq_workspaces_slug_active
  on workspaces ((lower(slug)))
  where slug is not null and deleted_at is null;

create index if not exists idx_workspaces_owner_created
  on workspaces (owner_user_id, created_at desc);

create trigger trg_workspaces_updated_at
before update on workspaces
for each row execute function set_row_updated_at();

create table if not exists workspace_members (
  id uuid primary key,
  workspace_id uuid not null references workspaces(id) on delete restrict,
  user_id uuid not null references users(id) on delete restrict,
  role text not null,
  invited_by_user_id uuid null references users(id) on delete set null,
  joined_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deactivated_at timestamptz null,
  deleted_at timestamptz null,
  constraint chk_workspace_members_role check (role in ('owner', 'admin', 'member', 'viewer'))
);

create unique index if not exists uq_workspace_members_active
  on workspace_members (workspace_id, user_id)
  where deactivated_at is null and deleted_at is null;

create unique index if not exists uq_workspace_members_single_owner_active
  on workspace_members (workspace_id)
  where role = 'owner' and deactivated_at is null and deleted_at is null;

create index if not exists idx_workspace_members_user_joined
  on workspace_members (user_id, joined_at desc);

create index if not exists idx_workspace_members_workspace_role_active
  on workspace_members (workspace_id, role)
  where deactivated_at is null and deleted_at is null;

create trigger trg_workspace_members_updated_at
before update on workspace_members
for each row execute function set_row_updated_at();
