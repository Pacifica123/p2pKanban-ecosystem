# p2pKanban v1.0.0-beta.8

This release separates reversible node-local card hiding from global card
deletion. Global deletion creates a durable tombstone and publishes an
encrypted `card.delete` roaming event. A known tombstone always wins over a
stale `card.put` or board snapshot.

Update every web node to beta.8 and Android to `1.5.0-mobile.6` before testing
cross-device deletion.

```bash
python bootstrap.py update --source-dir .
python bootstrap.py start --listen lan
```

Migration `0014` backfills tombstones for cards deleted by older releases.
