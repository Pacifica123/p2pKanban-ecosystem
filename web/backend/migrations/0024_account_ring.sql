-- R2 of the device ring: contracts/account-ring/1 and contracts/keyring/1.
-- One ring per local user; the node key (TRANSPORTS__NOSTR__SECRET_KEY) is the
-- node's device key in every ring it belongs to.

create table if not exists account_rings (
  user_id uuid primary key references users(id) on delete cascade,
  account_id text not null unique,
  created_at timestamptz not null default now(),
  last_sync_at timestamptz null,
  last_sync_json jsonb null,
  constraint chk_account_rings_account_id check (account_id ~ '^[0-9a-f]{64}$')
);

-- Signed ring entries (kind 27790) as received; the state is always re-folded.
create table if not exists account_ring_entries (
  account_id text not null references account_rings(account_id) on delete cascade,
  id text not null,
  event_json jsonb not null,
  source text not null default 'local',
  received_at timestamptz not null default now(),
  primary key (account_id, id),
  constraint chk_account_ring_entries_source check (source in ('local', 'relay'))
);

-- This node's own keyring copy: what it publishes, with per-item rev.
create table if not exists account_keyring_items (
  account_id text not null references account_rings(account_id) on delete cascade,
  kind text not null,
  id text not null,
  rev bigint not null,
  item_json jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (account_id, kind, id)
);

-- Latest keyring copy from every other ring member.
create table if not exists account_keyring_copies (
  account_id text not null references account_rings(account_id) on delete cascade,
  author_public_key text not null,
  created_at bigint not null,
  keyring_json jsonb not null,
  received_at timestamptz not null default now(),
  primary key (account_id, author_public_key)
);

-- Latest presence of every other ring member (versions, heads, relays).
create table if not exists account_ring_presences (
  account_id text not null references account_rings(account_id) on delete cascade,
  public_key text not null,
  seen_at bigint not null,
  presence_json jsonb not null,
  received_at timestamptz not null default now(),
  primary key (account_id, public_key)
);
