# A04b — UTS compile correction

## Fact

The first real Manjaro UserTestSpace `cargo test --manifest-path src-tauri/Cargo.toml --locked --offline` for A04 failed with Rust `E0308`. `assert_repository_contract<R: PlannerRepository>` is intentionally adapter-generic, but its helper `create()` was accidentally declared as `fn create(repo: &mut InMemoryPlannerRepository, ...)`. The same run also reported an unused `CardLifecycle` import in `application/repository.rs`. `cargo build` and the runtime launch probe could still pass because the failing contract module is `#[cfg(test)]`.

## Correction

A04b makes `create()` generic over `R: PlannerRepository`, removes the unused production-module import, and strengthens the deterministic A04/A04b gates so a reusable repository contract helper cannot silently couple itself to the in-memory reference adapter again.

The correction does not alter repository semantics, wire contracts, domain values or persistence choices. No SQLite/PostgreSQL dependency is introduced.

## Verification boundary

Deterministic source gates can prove the type-shape regression is removed, but the authoritative compile evidence is the unchanged UTS command:

```bash
python3 -B tools/uts_verify.py
```

A04 is considered compile-verified only when the Cargo test step is green in UTS. After that, the next architecture stage remains **A05 — SQLite profile schema + atomic migration engine**.
