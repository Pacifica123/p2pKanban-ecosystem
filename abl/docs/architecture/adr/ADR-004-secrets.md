# ADR-004 — Arch secret storage and at-rest claims

**Status:** implemented through A09 provider/storage boundary; multi-host provider matrix evidence remains experiment-needed  
**Decision:** protect a random application vault root through freedesktop Secret Service when usable; otherwise require an explicit Argon2id-derived passphrase vault or session-only credentials. Encrypt typed secret records with authenticated encryption. Do not claim full planner DB encryption in v1.

## Grounds
- [FACT] Android already separates memory-only access token from securely persisted refresh/capability secrets.
- [FACT] Linux desktop environments vary and may have Secret Service provider present, locked or absent.
- [INFERENCE] A provider abstraction plus explicit secure fallback preserves usability without silently downgrading secrecy.

## Rejected alternatives
- plaintext config/SQLite/localStorage;
- hard dependency on one GNOME/KDE keyring implementation;
- automatically configuring PAM/keyring daemons;
- storing every application object directly in Secret Service;
- promising SQLCipher/full-database encryption without a separate threat/performance decision.

## Costs
Multiple unlock/recovery UX paths; provider matrix testing; passphrase KDF/version/rotation handling.

## Failure modes
Provider locked/disappears; lost passphrase; corrupted vault root record; same-user malware; secret leakage in diagnostics.

## Verification
GNOME/KDE/minimal session matrix; wrong-passphrase/corruption fail-closed tests; provider migration/restart; secret canary scan across DB/config/log/crash bundle; explicit at-rest security wording review.


## A07 implementation note

A07 established the `SecretVault` application interface and a session-only provider. No secret put/get/delete IPC or secret-bearing SQLite columns were introduced.

## A09 implementation note

A09 implements the Linux provider/storage boundary: an unlocked freedesktop Secret Service protects a random vault root; typed secrets live in an authenticated XChaCha20-Poly1305 profile vault; a versioned Argon2id passphrase provider is available as the explicit durable fallback; locked/absent/corrupt providers degrade fail-closed to session-only status. The passphrase provider is exercised from Rust and intentionally has no generic WebView secret bridge before a real credential-provisioning flow exists. Full planner database encryption is still not claimed.
