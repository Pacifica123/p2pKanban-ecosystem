CREATE TABLE profile_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    min_reader INTEGER NOT NULL CHECK (min_reader > 0),
    min_writer INTEGER NOT NULL CHECK (min_writer > 0),
    created_at_unix_ms INTEGER NOT NULL CHECK (created_at_unix_ms >= 0)
);

CREATE TABLE schema_migrations (
    id TEXT PRIMARY KEY,
    checksum TEXT NOT NULL CHECK (length(checksum) = 64),
    applied_at_unix_ms INTEGER NOT NULL CHECK (applied_at_unix_ms >= 0)
);

CREATE TABLE workspaces (
    id TEXT PRIMARY KEY,
    access_epoch TEXT NOT NULL CHECK (length(access_epoch) > 0)
);

CREATE TABLE boards (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE columns (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE
);

CREATE TABLE cards (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    column_id TEXT NOT NULL REFERENCES columns(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    position REAL NOT NULL,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('active', 'archived'))
);

CREATE INDEX cards_column_order_idx ON cards(column_id, position, id);
CREATE INDEX cards_board_idx ON cards(board_id);

CREATE TABLE card_tombstones (
    card_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    logical_clock TEXT NOT NULL CHECK (length(logical_clock) > 0),
    replica_id TEXT NOT NULL CHECK (length(replica_id) > 0),
    event_id TEXT NOT NULL CHECK (length(event_id) > 0)
);

INSERT INTO profile_meta(singleton, schema_version, min_reader, min_writer, created_at_unix_ms)
VALUES (1, 1, 1, 1, 0);
PRAGMA user_version = 1;
