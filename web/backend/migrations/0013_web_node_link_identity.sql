create table if not exists local_node_identity (
  singleton boolean primary key default true,
  replica_id uuid not null unique,
  created_at timestamptz not null default now(),
  constraint chk_local_node_identity_singleton check (singleton = true)
);

insert into local_node_identity (singleton, replica_id)
values (true, gen_random_uuid())
on conflict (singleton) do nothing;

create table if not exists roaming_board_capabilities (
  board_id uuid primary key references boards(id) on delete cascade,
  board_tag text not null,
  board_key_base64 text not null,
  source_kind text not null default 'linked_node',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_roaming_board_capabilities_tag check (btrim(board_tag) <> ''),
  constraint chk_roaming_board_capabilities_key check (btrim(board_key_base64) <> ''),
  constraint chk_roaming_board_capabilities_source check (
    source_kind in ('linked_node', 'imported_capability')
  )
);

create trigger trg_roaming_board_capabilities_updated_at
before update on roaming_board_capabilities
for each row execute function set_row_updated_at();
