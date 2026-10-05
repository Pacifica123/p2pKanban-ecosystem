# Arch-native architecture SSOT

This directory is the living, implementation-driving copy of the reviewed `p2pkanban-archlinux-native-architecture` package.

The external ZIP is provenance only after A00. Changes to architecture decisions must be made here and reflected in `../IMPLEMENTATION_STATUS.md`; contradictory implementation must not silently diverge. When executable source proves a baseline decision stale, add/supersede an ADR and update the status ledger in the same bounded patch.

Classification used throughout the baseline:

- **FACT** — directly evidenced by supplied executable code, migrations, tests or platform specification.
- **INFERENCE** — conclusion derived from facts but not itself directly executed/proven.
- **PROPOSAL** — chosen implementation direction for the native client.
- **EXPERIMENT-NEEDED** — unresolved behavior requiring measured/manual/environment evidence.

A00 found no substantive source drift against the architecture input snapshots. Only archive filename suffixes differed; SHA-256 identities matched exactly and are recorded in `20-sources-and-evidence.md`.
