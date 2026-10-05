ALTER TABLE columns ADD COLUMN title TEXT NOT NULL DEFAULT '';
ALTER TABLE columns ADD COLUMN position REAL NOT NULL DEFAULT 0;
CREATE INDEX columns_board_order_idx ON columns(board_id, position, id);

CREATE TABLE checklists (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position REAL NOT NULL
);
CREATE INDEX checklists_card_order_idx ON checklists(card_id, position, id);

CREATE TABLE checklist_items (
    id TEXT PRIMARY KEY,
    checklist_id TEXT NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position REAL NOT NULL,
    is_done INTEGER NOT NULL DEFAULT 0 CHECK (is_done IN (0, 1))
);
CREATE INDEX checklist_items_order_idx ON checklist_items(checklist_id, position, id);
CREATE INDEX checklist_items_done_idx ON checklist_items(checklist_id, is_done);

CREATE TABLE checklist_tombstones (
    checklist_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    card_id TEXT NOT NULL,
    logical_clock TEXT NOT NULL CHECK (length(logical_clock) > 0),
    replica_id TEXT NOT NULL CHECK (length(replica_id) > 0),
    event_id TEXT NOT NULL CHECK (length(event_id) > 0)
);

CREATE TABLE checklist_item_tombstones (
    item_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    card_id TEXT NOT NULL,
    checklist_id TEXT NOT NULL,
    logical_clock TEXT NOT NULL CHECK (length(logical_clock) > 0),
    replica_id TEXT NOT NULL CHECK (length(replica_id) > 0),
    event_id TEXT NOT NULL CHECK (length(event_id) > 0)
);

CREATE TABLE local_mutation_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    logical_clock TEXT NOT NULL CHECK (length(logical_clock) > 0),
    origin_id TEXT NOT NULL
);
INSERT INTO local_mutation_state(singleton, logical_clock, origin_id) VALUES (1, '0', '');

CREATE TABLE pending_local_changes (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    sequence TEXT NOT NULL CHECK (length(sequence) > 0),
    kind TEXT NOT NULL CHECK (length(kind) > 0),
    entity_id TEXT NOT NULL CHECK (length(entity_id) > 0),
    created_at_unix_ms INTEGER NOT NULL CHECK (created_at_unix_ms >= 0)
);
CREATE INDEX pending_local_changes_board_idx ON pending_local_changes(board_id, created_at_unix_ms, id);

UPDATE profile_meta
SET schema_version = 3,
    min_reader = 3,
    min_writer = 3
WHERE singleton = 1;

PRAGMA user_version = 3;
