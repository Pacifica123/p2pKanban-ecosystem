# A07b — UTS compile/build correction

**Status: implemented at source/check level; authoritative post-fix Cargo/frontend/runtime verification is delegated to `tools/uts_verify.py`.**

## UTS fact

The first A07 UserTestSpace run (`20260912T155832Z`) kept every deterministic gate green but exposed two independent source compile defects:

1. TypeScript `TS2367` in `src/App.tsx`: `VaultStatus.durable` was declared as the single literal type `'false'`, while the UI intentionally retained the future-capability branch `vault.durable === 'true'`.
2. Rust `invalid format string` in `infrastructure/sqlite/migration.rs`: the migration-journal JSON body used literal `{` / `}` directly inside `format!` instead of escaped `{{` / `}}`.

The Tauri `frontendDist` error in the same Cargo run was downstream evidence, not a third root cause: because TypeScript compilation failed, Vite never produced `dist/index.html`; `tauri::generate_context!()` then correctly rejected the missing packaged frontend asset.

## Correction

- the frontend wire type is now `'true' | 'false'`, matching the string-valued Tauri capability payload while remaining forward-compatible with the A09 durable-vault provider;
- the migration journal keeps its existing JSON shape but escapes literal format braces correctly;
- `tools/check_a07b.py` guards both regressions and requires the packaged `dist/index.html` acceptance contract to remain explicit;
- the canonical UTS plan advances to A07b without changing runtime architecture or introducing new dependencies.

## Non-change / boundary

A07b does **not** change SQLite schema v2, migration IDs/checksums, workspace/board persistence semantics, vault security policy, IPC allowlist, XDG layout or instance ownership. It is an atomic build-correctness hotfix only.

After applying, run:

```text
python3 -B tools/uts_verify.py
```

A07 is considered host-verified only after frontend typecheck/build, Cargo test/build and runtime probes are green again. The next architecture patch remains **A08 — cards/order/archive/delete/checklists durable planner slice**.
