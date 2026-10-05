ALTER TABLE workspaces ADD COLUMN title TEXT NOT NULL DEFAULT '';
ALTER TABLE boards ADD COLUMN title TEXT NOT NULL DEFAULT '';

CREATE INDEX boards_workspace_title_idx ON boards(workspace_id, title, id);

UPDATE profile_meta
SET schema_version = 2,
    min_reader = 2,
    min_writer = 2
WHERE singleton = 1;

PRAGMA user_version = 2;
