# A09 — Linux secret persistence matrix

## Scope

A09 implements the production storage boundary for refresh tokens, board capabilities and device private keys without turning SQLite, configuration files or WebView storage into secret stores.

## FACT

- `SecretVault` remains an application-layer interface; Linux provider code lives under `infrastructure/linux/secrets.rs`.
- When an unlocked freedesktop Secret Service default collection is usable, p2pKanban stores only a random 32-byte vault root there. Typed application secrets remain in the profile `secrets.vault`, encrypted with XChaCha20-Poly1305 and authenticated AAD.
- A passphrase provider wraps the same class of random vault root with Argon2id-derived key material. The wrapper stores a versioned format, salt and bounded KDF parameters so future parameter changes do not silently invalidate old vaults.
- Provider locked, absent or corrupt states fail closed to an explicit session-only status. No plaintext SQLite/config/localStorage fallback is introduced.
- Existing passphrase ownership prevents automatic rebinding to a newly available Secret Service provider. Provider migration is therefore explicit work rather than silent key replacement.
- Secret file writes use profile directory mode 0700, file mode 0600, unpredictable `create_new` temporary files with `O_NOFOLLOW`, fsync, and atomic rename.
- The WebView receives only provider status/capability. There is no generic IPC for put/get/delete raw secret values or for arbitrary filesystem/keyring access.

## INFERENCE

- GNOME Keyring and KWallet installations that expose the freedesktop Secret Service API can satisfy the same primary provider contract, but one UTS machine cannot prove the full desktop-environment matrix.
- Protecting the small vault root in Secret Service limits keyring object churn while preserving a typed application vault that can be migrated/versioned independently.

## PROPOSAL / next boundary

- Credential/device-link onboarding may add a narrowly scoped passphrase activation flow when there is an actual secret-provisioning use case. It must not become a generic secret read/write bridge.
- A10 may persist sync credentials only through `SecretVault`; it must not add token/key columns to SQLite.

## UNRESOLVED / experiment-needed

- Multi-host evidence: unlocked/locked GNOME Secret Service, KWallet Secret Service compatibility, and minimal session with no provider.
- Explicit migration UX between Secret Service and passphrase ownership.
- Rotation/recovery UX after loss of the provider entry or passphrase.
- Same-user malware is outside the guarantee of this at-rest boundary; full planner-content encryption is not claimed.

## Verification

`tools/check_a09.py` is deterministic and network-free. Canonical UTS adds filtered `a09_` Rust crypto tests, a read-only Secret Service presence probe, and a generated secret canary that must not appear in verifier logs. Wrong-passphrase and ciphertext-corruption tests must fail closed.
