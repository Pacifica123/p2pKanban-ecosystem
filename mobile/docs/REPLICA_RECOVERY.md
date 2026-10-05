# Replica recovery on Android

The boards screen merges three catalogs: saved HTTP metadata, local board
snapshots and encrypted direct catalog events from trusted relay publishers.
On mobile Internet a private LAN URL is not awaited before those replicas can
be shown. Opening a known board hydrates local state first and then pulls its
encrypted baseline and journal.

The device key and catalog channel are kept in SecureStore. Session expiry does
not define the lifetime of the local replica or relay capability. Catalog
capabilities with delegation chains can also be included when Android approves
a new peer, so the phone remains an authorizer rather than a permanent proxy.

Relay delivery is asynchronous. The node that creates/imports a board must
publish its catalog and baseline at least once, and at least one configured
relay must retain them. Cards, checklists, deletions and board appearance roam
today. Comments, labels and later column mutations are not yet complete
multi-writer roaming entities.
