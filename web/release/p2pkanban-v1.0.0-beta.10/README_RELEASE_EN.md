# p2pKanban v1.0.0-beta.10

Compatible Android client: `1.5.0-mobile.8`.

## Start

```bash
python bootstrap.py
```

The loopback web UI now offers the next `main` commit. UI updates and
`python bootstrap.py update` share the same backup/rollback pipeline. A stable
gateway keeps the node URL while versioned backend/web containers are replaced.

## Highlights

- one device-local reminder per card on web and Android;
- Android consumes web-compatible palette, accent, wallpaper and display settings;
- immutable commit SHA after explicit acceptance;
- `pg_dump`, versioned images, core entity counts and rollback;
- no Docker socket inside web/backend containers;
- the pinned node port never shifts without an explicit `--port`.

APK source self-update is intentionally deferred: Android needs a prebuilt APK
signed by the same key plus installer consent, or a compatible OTA runtime.

Full notes: `docs/product/v1.0.0-beta.10-release-notes.md`.
