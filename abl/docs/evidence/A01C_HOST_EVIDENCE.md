# A01c — MSRV correction and Linux host runtime evidence contract

**Status: partially implemented.** A01c corrects a source-level compatibility error and adds the runtime evidence collector that A01b did not contain. It does not fabricate the still-missing Cargo lock, compile, or real WebView navigation evidence.

## FACT

- The selected `tauri = 2.11.5` upstream workspace currently declares `rust-version = "1.90"`; A01a incorrectly recorded `1.77.2` as the Tauri floor.
- The repository therefore now declares `rust-version = "1.90"` in `src-tauri/Cargo.toml`. This is a minimum compatibility declaration, not a claim that Rust 1.90 has been used successfully on this project yet.
- The A01c construction environment is Debian-based, has no Cargo/rustc/WebKitGTK development stack, cannot resolve the external package mirrors, and is not an Arch graphical user session. It cannot provide honest Arch build/launch evidence.
- A01b already fails closed when Cargo, WebKitGTK metadata, or `src-tauri/Cargo.lock` is missing.

Upstream evidence consulted for the correction on 2026-09-12:

- `https://github.com/tauri-apps/tauri/blob/dev/Cargo.toml` — workspace package `rust-version = "1.90"`, Tauri 2.11.5, tauri-build 2.6.3.
- `https://github.com/tauri-apps/tauri/blob/dev/crates/tauri/Cargo.toml` — package version 2.11.5 inherits the workspace Rust version.

## INFERENCE

Leaving `1.77.2` in the project would turn an old evidence error into an implementation contract and could make host preparation/debugging misleading. Correcting the MSRV before generating the lock is safer than baking the wrong compatibility statement into build provenance.

A single “process stayed alive” check is also insufficient runtime evidence. The normal-use shell must demonstrate, from its actual process tree, that it did not create a TCP listener or spawn Node/PostgreSQL/Docker/systemd as a hidden runtime dependency and that it launches as an ordinary user with isolated XDG paths.

## PROPOSAL implemented by A01c

`python3 -B tools/a01c_host_runtime_probe.py doctor` records user-session/toolchain/library facts without mutating the host.

After the strict A01b offline build succeeds, `python3 -B tools/a01c_host_runtime_probe.py launch-probe --report <path>`:

- refuses root execution for normal-use evidence;
- requires a real Wayland or X11 session instead of treating headless execution as GUI success;
- launches the compiled binary with temporary XDG config/data/cache/state/runtime roots;
- inspects `/proc` descendants and their socket inodes and fails if the app tree owns a TCP listening socket;
- rejects Node, PostgreSQL, Docker/Podman or systemd as descendant/runtime process dependencies;
- checks dynamic links for `libpq`/`libnode` leakage;
- plants a secret canary and fails if it appears in stdout/stderr; evidence persists only log sizes/hashes, never raw log text or full process arguments;
- records `systemctl` command and D-Bus session presence as capabilities without requiring either one.

The generated report is **test evidence**, not repository runtime state. It should be attached to release/validation records, not committed as a machine-specific generated artifact.

## UNRESOLVED EXPERIMENT / current UTS exit evidence

The historical **A01d** label meant “materialize lock/build/real-WebView evidence before progressing”. DELIVERY-A01-003 later changed that blocking policy: host-only evidence may remain verification-pending while unrelated source stages proceed, and A02 has now been implemented. A02b replaces the growing manual A01d command list with the canonical `tools/uts_verify.py` pipeline.

A01 is still not fully runtime-verified. The current UTS evidence must eventually demonstrate:

1. a resolver-generated/reviewed `src-tauri/Cargo.lock` for the exact manifest;
2. the exact successfully tested Rust toolchain and Arch-family system-library versions;
3. offline npm/Cargo acceptance after any explicit cache preparation;
4. non-root graphical launch with XDG isolation and no hidden listener/process dependencies;
5. WebView→Rust IPC observation for the current allowlisted route;
6. hostile HTTP/HTTPS/file/data/javascript navigation, `window.open`, and download denial before those properties are promoted to release-verified.

The first real UTS attempt reached Tauri context generation and found a missing application icon. That concrete source defect is recorded and fixed by A02b; post-fix verification remains pending.
