CREATE TABLE profile_principal (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    user_id TEXT NOT NULL CHECK (length(user_id) > 0),
    replica_id TEXT NOT NULL CHECK (length(replica_id) > 0),
    device_public_key TEXT NOT NULL CHECK (length(device_public_key) > 0),
    provisioned_by TEXT NOT NULL CHECK (provisioned_by IN ('device-link-v2', 'web-node-link-v1')),
    created_at_unix_ms INTEGER NOT NULL CHECK (created_at_unix_ms >= 0)
);

CREATE TABLE import_receipts (
    source_digest TEXT PRIMARY KEY CHECK (length(source_digest) = 64),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('portable-bundle-v1', 'device-link-v2', 'web-node-link-v1')),
    format_version TEXT NOT NULL CHECK (length(format_version) > 0),
    user_id TEXT,
    workspace_id TEXT,
    board_id TEXT,
    omissions_json TEXT NOT NULL,
    imported_at_unix_ms INTEGER NOT NULL CHECK (imported_at_unix_ms >= 0)
);
CREATE INDEX import_receipts_scope_idx ON import_receipts(workspace_id, board_id, imported_at_unix_ms);

CREATE TABLE imported_capability_metadata (
    board_id TEXT PRIMARY KEY REFERENCES boards(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL CHECK (length(user_id) > 0),
    capability_epoch TEXT NOT NULL CHECK (length(capability_epoch) > 0),
    subject TEXT NOT NULL CHECK (length(subject) > 0),
    can_delegate INTEGER NOT NULL CHECK (can_delegate IN (0, 1)),
    parent_id TEXT,
    expires_at_unix INTEGER,
    source_digest TEXT NOT NULL REFERENCES import_receipts(source_digest) ON DELETE RESTRICT
);
CREATE INDEX imported_capability_workspace_idx ON imported_capability_metadata(workspace_id, capability_epoch, board_id);

CREATE TABLE import_opaque_sections (
    source_digest TEXT NOT NULL REFERENCES import_receipts(source_digest) ON DELETE CASCADE,
    section_name TEXT NOT NULL CHECK (length(section_name) > 0),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (source_digest, section_name)
);

UPDATE profile_meta
SET schema_version = 5,
    min_reader = 5,
    min_writer = 5
WHERE singleton = 1;

PRAGMA user_version = 5;
