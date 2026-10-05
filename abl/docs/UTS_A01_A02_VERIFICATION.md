# Superseded UTS command list

This per-stage command list is **superseded** by the canonical `docs/UTS_VERIFICATION.md` and the machine-readable `tools/uts_plan.json`.

Use one command from the project root:

```bash
python3 -B tools/uts_verify.py
```

If the summary says that an npm/Cargo cache is incomplete and external network access is acceptable for build-time preparation, rerun with `--allow-network`. Do not maintain or copy a second manual command list here.
