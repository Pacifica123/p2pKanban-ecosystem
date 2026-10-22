-- R4 of the device ring: contracts/rendezvous/1. The node only shows QR codes:
-- as sponsor ("invite": a phone enters this node's ring) or as joiner ("join":
-- a phone of a ring adds this node). The secret lives until the meeting ends
-- and is erased after it; the session row stays as a short history.

create table if not exists ring_rendezvous_sessions (
  session_id text primary key,
  user_id uuid not null references users(id) on delete cascade,
  mode text not null,
  qr_json jsonb not null,
  secret_b64 text null,
  expires_at bigint not null,
  status text not null default 'waiting',
  peer_json jsonb null,
  outcome_json jsonb null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_ring_rendezvous_mode check (mode in ('invite', 'join')),
  constraint chk_ring_rendezvous_status check (status in ('waiting', 'confirm', 'welcomed', 'done', 'refused', 'expired', 'canceled'))
);

create index if not exists idx_ring_rendezvous_user_created
  on ring_rendezvous_sessions (user_id, created_at desc);
