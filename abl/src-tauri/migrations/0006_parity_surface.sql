CREATE TABLE labels (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT,
    position REAL NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX labels_board_order_idx ON labels(board_id, position, id);

CREATE TABLE card_labels (
    card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    label_id TEXT NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY (card_id, label_id)
);
CREATE INDEX card_labels_label_idx ON card_labels(label_id, card_id);

CREATE TABLE comments (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    author_user_id TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX comments_card_time_idx ON comments(card_id, created_at, id);

CREATE TABLE board_appearance_settings (
    board_id TEXT PRIMARY KEY REFERENCES boards(id) ON DELETE CASCADE,
    settings_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE activity_entries (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    card_id TEXT,
    actor_user_id TEXT,
    kind TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE INDEX activity_board_time_idx ON activity_entries(board_id, occurred_at, id);
CREATE INDEX activity_card_time_idx ON activity_entries(card_id, occurred_at, id);

CREATE TABLE parity_local_changes (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason = 'roaming-v1-unsupported'),
    created_at_unix_ms INTEGER NOT NULL CHECK (created_at_unix_ms >= 0)
);
CREATE INDEX parity_local_changes_board_idx ON parity_local_changes(board_id, created_at_unix_ms, id);

UPDATE profile_meta
SET schema_version = 6,
    min_reader = 6,
    min_writer = 6
WHERE singleton = 1;

PRAGMA user_version = 6;
