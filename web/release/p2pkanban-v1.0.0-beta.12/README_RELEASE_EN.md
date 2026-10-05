# p2pKanban v1.0.0-beta.12

Corrective release for the beta.11 production build and update discovery.

- Fixes the TypeScript and Rust compile blockers.
- Web detects a new commit even when the host control plane is not running.
- The running revision is no longer inferred from the checkout Git HEAD.
- Bootstrap state records the source revision that was actually built.
- Devctl wakes the local UI installer after a successful push.

Full notes: `docs/product/v1.0.0-beta.12-release-notes.md`.
