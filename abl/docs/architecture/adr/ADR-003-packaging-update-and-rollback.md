# ADR-003 — Arch packaging, update and rollback

**Status:** accepted; A15 implementation in progress
**Decision:** signed pacman package/repository + reviewable PKGBUILD is the primary distribution path. Pacman owns `/usr` and performs updates. AppImage is a signed fallback. Database rollback is coordinated separately from package downgrade.

## Grounds
- [FACT] Arch is rolling-release and partial upgrades are unsupported.
- [FACT] Tauri/Linux depends on system libraries including WebKitGTK; package manager ownership exposes those dependencies coherently.
- [INFERENCE] A self-updater mutating `/usr` behind pacman creates file/dependency ownership ambiguity.
- [PROPOSAL] Keep system package lifecycle native to Arch while retaining application-owned pre-migration snapshots for data rollback.

## Rejected alternatives
- self-extracting installer writing `/usr`;
- app invoking `sudo pacman` or `pacman -Sy`;
- AppImage-only delivery;
- mandatory Flatpak before portal/keyring/network behavior is separately validated.

## Costs
Signed repository/key management; PKGBUILD maintenance; prompt rebuilds during soname transitions; separate AppImage release QA.

## Failure modes
Stale mirror/signing key; partial-upgrade user state; package downgrade against incompatible newer DB; WebKitGTK ABI/runtime transition; AppImage from untrusted source.

## Verification
Clean-chroot build; `namcap`; package file ownership and `pacman -Qkk`; signed repo tamper/replay tests; coherent system upgrade tests; failed migration + package/data rollback drill; uninstall leaves XDG data untouched.
