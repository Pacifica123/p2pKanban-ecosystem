alter table if exists cards
  add column if not exists archived_at timestamptz null;

create index if not exists idx_cards_board_archived
  on cards (board_id, archived_at)
  where deleted_at is null;
