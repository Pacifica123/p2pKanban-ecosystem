# p2pKanban v1.0.0-beta.9

This release replaces destructive full-card checklist roaming snapshots with
per-checklist and per-item deltas. A delayed legacy snapshot can no longer
delete or overwrite newer checklist items. Activity entries are emitted only
for fields that actually changed, preventing false card-moved records.

Use Android `1.5.0-mobile.7` with this web/backend release.

```bash
python bootstrap.py update --source-dir .
python bootstrap.py start --listen lan
```

Migration `0015` removes unmistakably false legacy `card.moved` entries.
Prepared Android boards use encrypted relays immediately on cellular networks
when the configured node address is LAN-only.
