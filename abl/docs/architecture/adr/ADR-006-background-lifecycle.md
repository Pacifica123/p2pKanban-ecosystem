# ADR-006 — Arch background lifecycle and systemd

**Status:** proposed  
**Decision:** v1 GA has no required systemd user service and never enables linger automatically. Sync lifecycle follows the interactive/tray process. A future user service requires separate product evidence and ADR.

## Grounds
- [FACT] Local-first pending operations remain durable while no process is running.
- [FACT] Linux graphical session D-Bus, Secret Service and notification availability can differ from a headless/lingering user manager.
- [INFERENCE] An always-on service would add idle CPU/memory/wakeup and upgrade/DB ownership complexity without being necessary for basic correctness.

## Rejected alternatives
- mandatory user unit enabled at install;
- system/root daemon;
- automatic `loginctl enable-linger`;
- hidden background process after window close when no tray host exists.

## Costs
No synchronization while the application is fully closed; product must communicate this behavior.

## Failure modes
User assumes background sync; tray absent causing hidden-process confusion; future daemon races interactive process for DB; service cannot unlock session keyring.

## Verification
Close/reopen queue resume; no user/system unit required after install; desktop environments with/without tray host; idle process absence; future background prototype must prove single-writer ownership, authenticated UI IPC and secure key availability before adoption.
