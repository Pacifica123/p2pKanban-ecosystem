-- Per-device catalog receipts let an enrolled peer discover boards and recover
-- capabilities without contacting the HTTP address that first enrolled it.
create table roaming_device_catalog_receipts (
  device_public_key text not null,
  board_id uuid not null references boards(id) on delete cascade,
  fingerprint text not null,
  payload_json jsonb not null,
  delivered boolean not null default false,
  nostr_event_id text null,
  last_error text null,
  updated_at timestamptz not null default now(),
  primary key(device_public_key,board_id)
);
