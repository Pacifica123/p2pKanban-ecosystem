create table if not exists boards (
  id uuid primary key,
  workspace_id uuid not null references workspaces(id) on delete restrict,
  name text not null,
  description text null,
  board_type text not null default 'kanban',
  created_by_user_id uuid null references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz null,
  deleted_at timestamptz null
);

create index if not exists idx_boards_workspace_created_active
  on boards (workspace_id, created_at desc)
  where deleted_at is null;

create index if not exists idx_boards_workspace_archived
  on boards (workspace_id, archived_at);

create trigger trg_boards_updated_at
before update on boards
for each row execute function set_row_updated_at();

create table if not exists board_columns (
  id uuid primary key,
  board_id uuid not null references boards(id) on delete restrict,
  name text not null,
  description text null,
  position numeric(20,10) not null,
  color_token text null,
  wip_limit integer null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz null,
  constraint chk_board_columns_wip_limit check (wip_limit is null or wip_limit >= 0)
);

create unique index if not exists uq_board_columns_name_active
  on board_columns (board_id, (lower(btrim(name))))
  where deleted_at is null;

create index if not exists idx_board_columns_position_active
  on board_columns (board_id, position, id)
  where deleted_at is null;

create unique index if not exists uq_board_columns_board_id_id
  on board_columns (board_id, id);

create trigger trg_board_columns_updated_at
before update on board_columns
for each row execute function set_row_updated_at();

create table if not exists cards (
  id uuid primary key,
  board_id uuid not null references boards(id) on delete restrict,
  column_id uuid not null,
  parent_card_id uuid null,
  title text not null,
  description text null,
  position numeric(20,10) not null,
  status text not null default 'active',
  priority text null,
  start_at timestamptz null,
  due_at timestamptz null,
  completed_at timestamptz null,
  created_by_user_id uuid null references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz null,
  constraint uq_cards_board_id_id unique (board_id, id),
  constraint chk_cards_status check (status in ('active', 'completed', 'cancelled')),
  constraint chk_cards_priority check (priority is null or priority in ('low', 'medium', 'high', 'urgent')),
  constraint chk_cards_completed_at check (completed_at is null or status = 'completed'),
  constraint chk_cards_dates check (due_at is null or start_at is null or due_at >= start_at),
  constraint fk_cards_board_column foreign key (board_id, column_id)
    references board_columns (board_id, id) on delete restrict,
  constraint fk_cards_board_parent foreign key (board_id, parent_card_id)
    references cards (board_id, id) on delete restrict
);

create index if not exists idx_cards_board_column_position_active
  on cards (board_id, column_id, position, id)
  where deleted_at is null;

create index if not exists idx_cards_board_updated_active
  on cards (board_id, updated_at desc)
  where deleted_at is null;

create index if not exists idx_cards_board_due_active
  on cards (board_id, due_at)
  where deleted_at is null;

create index if not exists idx_cards_board_completed_active
  on cards (board_id, completed_at)
  where deleted_at is null;

create trigger trg_cards_updated_at
before update on cards
for each row execute function set_row_updated_at();

create table if not exists board_labels (
  id uuid primary key,
  board_id uuid not null references boards(id) on delete restrict,
  name text not null,
  color text not null,
  description text null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz null
);

create unique index if not exists uq_board_labels_name_active
  on board_labels (board_id, (lower(btrim(name))))
  where deleted_at is null;

create unique index if not exists uq_board_labels_board_id_id
  on board_labels (board_id, id);

create trigger trg_board_labels_updated_at
before update on board_labels
for each row execute function set_row_updated_at();

create table if not exists card_labels (
  id uuid primary key,
  board_id uuid not null,
  card_id uuid not null,
  label_id uuid not null,
  created_at timestamptz not null default now(),
  deleted_at timestamptz null,
  constraint fk_card_labels_board_card foreign key (board_id, card_id)
    references cards (board_id, id) on delete cascade,
  constraint fk_card_labels_board_label foreign key (board_id, label_id)
    references board_labels (board_id, id) on delete cascade
);

create unique index if not exists uq_card_labels_active
  on card_labels (card_id, label_id)
  where deleted_at is null;

create index if not exists idx_card_labels_board_card_active
  on card_labels (board_id, card_id)
  where deleted_at is null;

create index if not exists idx_card_labels_board_label_active
  on card_labels (board_id, label_id)
  where deleted_at is null;

create table if not exists checklists (
  id uuid primary key,
  card_id uuid not null references cards(id) on delete cascade,
  title text not null,
  position numeric(20,10) not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz null
);

create index if not exists idx_checklists_card_position_active
  on checklists (card_id, position, id)
  where deleted_at is null;

create trigger trg_checklists_updated_at
before update on checklists
for each row execute function set_row_updated_at();

create table if not exists checklist_items (
  id uuid primary key,
  checklist_id uuid not null references checklists(id) on delete cascade,
  title text not null,
  is_done boolean not null default false,
  position numeric(20,10) not null,
  due_at timestamptz null,
  completed_at timestamptz null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz null,
  constraint chk_checklist_items_done_state check (
    (is_done = false and completed_at is null)
    or
    (is_done = true and completed_at is not null)
  )
);

create index if not exists idx_checklist_items_position_active
  on checklist_items (checklist_id, position, id)
  where deleted_at is null;

create index if not exists idx_checklist_items_done_active
  on checklist_items (checklist_id, is_done)
  where deleted_at is null;

create trigger trg_checklist_items_updated_at
before update on checklist_items
for each row execute function set_row_updated_at();

create table if not exists comments (
  id uuid primary key,
  card_id uuid not null references cards(id) on delete cascade,
  author_user_id uuid null references users(id) on delete set null,
  body text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz null
);

create index if not exists idx_comments_card_created_active
  on comments (card_id, created_at, id)
  where deleted_at is null;

create index if not exists idx_comments_author_created
  on comments (author_user_id, created_at desc);

create trigger trg_comments_updated_at
before update on comments
for each row execute function set_row_updated_at();