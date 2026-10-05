# A02d — Git-less UserTestSpace snapshot correction

**Status: implemented verifier/repository-view correction; application architecture remains at A02 pending A03.**

## FACT — evidence supplied from the next real UTS run

The post-A02c UserTestSpace run was created in a fresh project directory and the application path itself stayed green: frontend typecheck/build, Cargo lock/fetch/test/build, binary presence, and the Wayland runtime launch probe all passed.

Only A00 and A01 failed, both before and after the build. Their logs contain the same root cause from `tools/repository_contract.py`:

```text
fatal: не найден git репозиторий
```

The devctl **UserTestSpace snapshot intentionally does not contain Git metadata**. A02c incorrectly promoted `git ls-files` from an implementation detail of normal workspaces into a mandatory runtime dependency of deterministic checks. This was a verifier defect, not an application regression and not build-cache pollution.

## CORRECTION

`tools/repository_contract.py` now has two explicit evidence modes:

- **Git workspace** — when the project root itself is a Git worktree, `git ls-files` remains authoritative;
- **UserTestSpace snapshot** — when `.git` is absent, a deterministic file inventory is used and only known generated/cache trees (`node_modules`, `dist`, Cargo `target`, `.uts-reports`, etc.) are excluded.

The snapshot fallback deliberately keeps unexpected `.env`, key/database/runtime files visible so A00/A01 security/hygiene checks can still reject them. It does not parse `.gitignore` wholesale because that could hide secrets simply because they are ignored in developer worktrees.

A02d also removes the A02c checker's accidental assumption that `tools/uts_plan.json` must stay forever at stage A02c. Historical regression gates must remain valid as later Axx checks are appended.

## CACHE CLARIFICATION

Each devctl UTS path is a **fresh project-local** directory, so prior `node_modules`, `dist`, and `src-tauri/target` directories do not carry over automatically. Separately, **global package caches** such as npm's user cache and Cargo's `~/.cargo/registry` / `~/.cargo/git` live outside the UTS project and may persist between runs. Therefore a later fresh UTS can legitimately succeed with `--offline` after an earlier network-enabled cache fill.

No assumption about those global caches is required by the deterministic gates.

## NON-CLAIMS

This correction does not add new application behavior. It does not claim hostile-navigation runtime evidence or manual rendered health text. It only restores truthful deterministic verification in the actual devctl UTS topology.
