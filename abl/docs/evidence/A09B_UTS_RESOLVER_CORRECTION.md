# A09b — UTS Cargo resolver correction

Status: **implemented at source/deterministic-check level; canonical UTS rerun required**.

## Fact from canonical A09 UTS

The A09 run passed A00→A09 deterministic gates and frontend checks. Cargo lock preparation failed only at the mandatory offline recheck after network preparation. The logs showed:

- initial offline resolver: local index/cache had no `argon2 = 0.6.0` candidate;
- network `cargo generate-lockfile`: succeeded;
- offline re-resolution: rejected `chacha20 = 0.10.1` because that release is yanked, reached through `chacha20poly1305 = 0.11.0`.

This is a dependency-graph/offline-acceptance defect, not a reason to weaken the verifier.

## Correction

A09b pins `chacha20poly1305 = 0.10.1`. The application-facing XChaCha20Poly1305/Aead/KeyInit API used by `infrastructure/linux/secrets.rs` remains the same for this usage. The 0.10.1 line uses the older stable `chacha20 0.9.x` dependency and zeroizes its internal AEAD key on drop.

`argon2 = 0.6.0` remains unchanged: the first miss was expected cache/index preparation and the explicit network resolver successfully found it. Changing unrelated crypto dependencies would add needless churn.

## Non-claims

- A09b does not claim UTS Cargo test/build green until the user reruns `tools/uts_verify.py --allow-network`.
- A09b does not weaken `--offline` acceptance or bypass yanked-package handling.
- `Cargo.lock` is not fabricated from prose/logs; a real resolver remains authoritative.
- A10 sync work does not begin in this hotfix.
