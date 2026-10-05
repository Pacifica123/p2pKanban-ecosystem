# A17b: real locked Cargo graph and explicit UTS cache recovery

Base: supplied snapshot `df2bd70`.

Adds a genuine Cargo.lock resolved against unchanged direct pins with Rust 1.90-compatible fallback. UTS reports an incomplete offline Cargo cache as a blocked prerequisite while retaining nonzero verification and original logs; summary gives the exact one-time --allow-network preparation and offline rerun commands. Actual manifest/compiler defects retain FAIL. Adds a deterministic lock/cache regression and updates mutable evidence hashes only for modified repository documents/tools. Frozen external source anchors remain intact.

Input UTS root error: no matching k256 package in the offline cache; allowNetwork=false. Rust build and downstream host probes were not executed in that report. A lockfile does not provide crate archives or GTK/WebKit build dependencies. Local locked network fetch and offline fetch pass; native test attempt is blocked by missing pkg-config/system development dependencies here. Real target-host native tests/build/runtime and AppImage acceptance remain mandatory. This is an A17 correction, not A18 implementation.

After devctl start, run python3 -B tools/uts_verify.py --allow-network once in the project, then python3 -B tools/uts_verify.py. No profile reset/cache deletion/dependency-pin changes. Source rollback uses devctl; runtime profile/package recovery retains the A16 rules.
