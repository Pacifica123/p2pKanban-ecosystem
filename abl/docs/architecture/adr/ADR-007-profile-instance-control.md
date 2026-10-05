# ADR-007 — profile writer ownership and second-instance activation

**Status:** accepted / A06 implemented at source-test level; Arch host verification delegated to UTS.

## Context

The desktop profile is a local SQLite database under the user's XDG data tree. SQLite locking protects database transactions, but the product also needs one application-level writer owner per profile so that migrations, future sync workers, import/export coordination and UI lifecycle are not duplicated by two desktop processes.

`$XDG_RUNTIME_DIR` is useful for ephemeral IPC but cannot be assumed: minimal window-manager sessions, unusual login stacks and recovery shells may not provide it. A persistent PID lock file is also unsafe because crashes leave stale state and PID reuse makes naive recovery ambiguous.

## Decision

1. The primary process takes a non-blocking Linux `flock(LOCK_EX|LOCK_NB)` on the **profile directory inode** before Tauri starts. No persistent lock file is created. The kernel releases the lock when the owning process exits, including abnormal process death.
2. SQLite/WAL locking remains defense-in-depth. The application lock does not replace SQLite transaction semantics.
3. If a secure user-owned `$XDG_RUNTIME_DIR` is available, p2pKanban creates only `$XDG_RUNTIME_DIR/p2pkanban/instances/` and binds a mode-0600 Unix datagram socket for a fixed `activate-main-v1` message. A second process that cannot obtain writer ownership sends that message and exits without opening a second WebView/database writer.
4. The runtime directory is capability-detected. Missing, relative, symlinked, wrong-owner or group/other-accessible runtime roots are not trusted for IPC. Writer exclusion still works through the profile-directory kernel lock; only activation routing degrades.
5. The activation protocol carries no path, command line, deep-link or arbitrary payload. Rich deep-link/file-open routing remains a later validated capability.
6. No root, polkit, systemd user service, D-Bus service, network manager or localhost listener is required.

## Consequences

- Crash recovery does not depend on stale PID files: the lock is kernel-owned.
- A leftover Unix socket is removed only **after** the process has acquired profile writer ownership, so a contender cannot delete a live primary's socket.
- Without a usable XDG runtime directory, launching a second instance reports that writer ownership is protected but activation routing is unavailable and exits cleanly.
- The profile directory itself is persistent, but the lock is only an in-kernel advisory lock on its inode; no runtime lock artifact is stored in XDG data.

## Verification

- two processes cannot simultaneously become profile primary;
- second instance routes the fixed activation message when secure runtime IPC exists;
- missing runtime directory still prevents a second writer;
- stale Unix socket is replaced by a newly acquired primary;
- child process abort releases the kernel lock and allows reopen;
- all profile/runtime paths are exercised under temporary XDG roots;
- UTS host probe launches the real binary twice and verifies both routed and no-runtime degraded behavior.
