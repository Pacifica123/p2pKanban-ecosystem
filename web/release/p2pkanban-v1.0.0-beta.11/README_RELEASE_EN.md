# p2pKanban v1.0.0-beta.11

Compatible Android client: `1.5.0-mobile.9`.

## Start

```bash
python bootstrap.py
```

A running beta.10 loopback UI can offer this commit. UI updates and
`python bootstrap.py update` share the same backup/rollback pipeline, while the
stable gateway keeps the node URL and port.

## Highlights

- the card column is its only workflow state; the fixed status enum is gone;
- Android card details show the column, a flat 0–4 star priority, and lighter checklists;
- board appearance travels between web and Android through coordinator/relay;
- tombstone-aware merging protects fresh checklist items from stale snapshots;
- backend relay recovery fetches boards concurrently instead of summing timeouts;
- web coalesces access-token refresh and avoids a 401 request storm;
- card details in both clients inherit the board palette.

APK source self-update remains deferred: Android requires a prebuilt package
signed by the same key plus installer consent, or a compatible OTA runtime.

Full notes: `docs/product/v1.0.0-beta.11-release-notes.md`.
