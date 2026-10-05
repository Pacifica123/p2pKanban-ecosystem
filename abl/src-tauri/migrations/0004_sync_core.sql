CREATE TABLE sync_outbox (
    event_id TEXT PRIMARY KEY,
    source_change_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    protocol_version TEXT NOT NULL,
    capability_epoch TEXT NOT NULL CHECK (length(capability_epoch) > 0),
    replica_id TEXT NOT NULL CHECK (length(replica_id) > 0),
    replica_seq TEXT NOT NULL CHECK (length(replica_seq) > 0),
    logical_clock TEXT NOT NULL CHECK (length(logical_clock) > 0),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    field_mask_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'relay_pending', 'failed')),
    created_at_unix_ms INTEGER NOT NULL CHECK (created_at_unix_ms >= 0)
);
CREATE INDEX sync_outbox_board_state_idx ON sync_outbox(board_id, state, created_at_unix_ms, event_id);
CREATE INDEX sync_outbox_source_idx ON sync_outbox(source_change_id, event_id);

CREATE TABLE sync_seen_events (
    event_id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    event_digest TEXT NOT NULL CHECK (length(event_digest) = 64),
    logical_clock TEXT NOT NULL CHECK (length(logical_clock) > 0),
    replica_id TEXT NOT NULL CHECK (length(replica_id) > 0),
    applied_at_unix_ms INTEGER NOT NULL CHECK (applied_at_unix_ms >= 0)
);
CREATE INDEX sync_seen_events_board_idx ON sync_seen_events(board_id, applied_at_unix_ms, event_id);

CREATE TABLE sync_field_versions (
    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    logical_clock TEXT NOT NULL CHECK (length(logical_clock) > 0),
    replica_id TEXT NOT NULL CHECK (length(replica_id) > 0),
    event_id TEXT NOT NULL CHECK (length(event_id) > 0),
    PRIMARY KEY (board_id, entity_id, field_name)
);

CREATE TABLE sync_entity_extensions (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

UPDATE profile_meta
SET schema_version = 4,
    min_reader = 4,
    min_writer = 4
WHERE singleton = 1;

PRAGMA user_version = 4;
