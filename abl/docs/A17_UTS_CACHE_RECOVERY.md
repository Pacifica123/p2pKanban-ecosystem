# A17b: native build prerequisites and repeatable Cargo graph

The supplied 20261001T094836Z UTS report has one root failure: offline Cargo resolution cannot find `k256`. It was run with `allowNetwork=false`. Native Rust tests, build, A06–A16 host probes and GUI launch were not executed; their BLOCKED status is a consequence, not evidence of those features failing.

This patch supplies a real Cargo.lock resolved for the declared Rust 1.90 minimum against the unchanged direct dependency pins, not a placeholder. UTS uses this exact graph with locked fetch/test/build. A lockfile does not contain crate archives, GTK/WebKit headers or toolchains.

On the target Arch host, from the devctl-applied project root:

```bash
python3 -B tools/uts_verify.py --allow-network
python3 -B tools/uts_verify.py
```

The first invocation may populate npm/Cargo caches. Rust acceptance commands remain offline and locked. The second invocation must pass without registry access. Do not erase Cargo caches or the profile, change pins at random, or interpret deterministic-only PASS as native acceptance.

If the first invocation fails, retain its summary and the earliest failed network-prepare/fetch/test/build log. A TLS/registry error, missing build package and Rust compiler error require different fixes. UTS explicitly displays the preparation command and distinguishes a missing lock cache prerequisite from a test failure. It continues returning nonzero for blocked verification.

Native AppImage/GUI, Secret Service and host compatibility require the existing real-host gates; this patch does not claim that adding Cargo.lock proves them.
