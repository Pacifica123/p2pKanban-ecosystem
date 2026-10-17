# A15 Arch release procedure

This procedure is for a project-controlled Arch x86_64 release. It never requires the application itself to gain package-manager privileges.

## 0. The A15 release receipt

Steps 1–4 below are what A15 acceptance needs. On the release/test Arch host they are run by one command, which writes a receipt the host issues for itself:

```bash
python3 -B tools/a15_issue_receipt.py --signing-key YOUR_VERIFIED_FINGERPRINT
```

- It runs as your user in a terminal and asks for sudo; before the first privileged command it prints all of them and asks once (`--dry-run` prints them and exits, `--yes` skips the question).
- Steps, in order: release inputs from this tree → `makechrootpkg -c -u -n` in a clean chroot (`--chroot`, default `/var/lib/archbuild/p2pkanban`, created with `mkarchroot` if missing) → `namcap` on the built package → package file list → package and repository DB signed with the external key (`tools/a15_stage_signed_repo.py`) → release public key added and locally signed in the pacman keyring → install from that local signed repository (pacman reports `Validated By: Signature`) → `pacman -Qkk p2pkanban` → `pacman -R p2pkanban` with marker files in all four XDG roots and a marker SecretVault item, comparing the existing profile files and `vault-root-v1` items before and after → install again and `pacman -Qkk`.
- Installation uses a generated pacman config that contains only the receipt repository, so no system repository is refreshed and no partial upgrade is possible. A sync DB `p2pkanban-receipt.db` stays in pacman's sync directory.
- `--no-build` (or `P2PKANBAN_A15_NO_BUILD=1`) skips the chroot build and takes the package from an earlier receipt with the same release inputs; every other step still runs.
- Output: `.uts-reports/a15-receipts/<UTC time>/` with `receipt.json` (every command, exit code and sha256 of its full log; package, binary and source hashes; the sha256 of its own canonical JSON), `receipt.json.asc` (detached signature by the release key), `receipt.md` (human-readable) and `logs/`. `latest.json` points the UTS at the newest one.

The canonical UTS never builds, signs or calls sudo. Its step `host.a15-release-receipt` (`tools/a15_host_receipt_probe.py`) reads `latest.json` and reports:

- **PASS** — the receipt is intact (canonical hash, log hashes, release-key signature), every step passed, its release inputs equal what this tree produces now, the installed package is the one from the receipt, validated by signature, and `pacman -Qkk` is clean. The receipt is copied into the UTS report.
- **SKIP** (exit 77) — nothing to judge yet: not an Arch host, no receipt, a receipt for other sources, or a different build installed. The message names the command to run.
- **FAIL** — the receipt was edited, its signature or a log does not verify, it records a failed step, or the receipt package fails `pacman -Qkk`.

Launching the installed package under Wayland/X11 and `p2pkanban://activate` routing stay a manual check; publishing to project mirrors is a release step outside the receipt.

## 1. Produce immutable release inputs

Run canonical UTS first so `src-tauri/Cargo.lock` is the graph that already passed offline test/build acceptance. Then stage release inputs outside the source tree (or under ignored `.uts-reports/`):

```bash
python3 -B tools/a15_prepare_release.py \
  --cargo-lock src-tauri/Cargo.lock \
  --stage /tmp/p2pkanban-release
```

The stage contains the deterministic source tarball, desktop entry, packaging notice, an exact-checksum `PKGBUILD` and `release-inputs.json`. Do not publish the bootstrap `packaging/arch/PKGBUILD` directly; its checksum marker is intentionally unresolved.

## 2. Clean-chroot build and lint

On a fully updated Arch build host with `devtools`, `namcap` and `desktop-file-utils` installed, use a clean chroot. One supported flow is:

```bash
export CHROOT=/var/lib/archbuild/p2pkanban
sudo mkarchroot "$CHROOT/root" base-devel
cd /tmp/p2pkanban-release
makechrootpkg -c -r "$CHROOT" -n -- --check
namcap PKGBUILD
namcap p2pkanban-0.1.0-1-x86_64.pkg.tar.zst
```

A release operator may use the current `pkgctl build` equivalent instead. Do not build against a deliberately partial-upgrade system and do not work around dependency transitions with private copied system libraries.

## 3. Sign package and repository

Keep the release private key outside this repository. With the key already available to GPG/gpg-agent:

```bash
python3 -B tools/a15_stage_signed_repo.py \
  --package /tmp/p2pkanban-release/p2pkanban-0.1.0-1-x86_64.pkg.tar.zst \
  --signing-key YOUR_VERIFIED_FINGERPRINT \
  --output /tmp/p2pkanban-repo
```

The output includes the package/signature, signed pacman database and `release-manifest.json`. Publish identical repository bytes to at least two project-controlled origins when available. Mirrors are distribution endpoints, not separate trust roots.

## 4. Client trust and package lifecycle evidence

Import/locally verify the public release key using the normal pacman trust procedure, configure the repository with signature checking enabled, then on a disposable coherent test system record:

```bash
sudo pacman -Syu p2pkanban
pacman -Qkk p2pkanban
```

Launch once, create/reopen representative local data, upgrade with pacman, then remove only the package:

```bash
sudo pacman -R p2pkanban
```

Confirm package-owned `/usr` files are gone while the user's `$XDG_DATA_HOME`, `$XDG_CONFIG_HOME`, `$XDG_STATE_HOME`, `$XDG_CACHE_HOME` and existing secret-provider entries remain. Data purge is an explicit application/user operation, never a package-remove hook.

## 5. Rollback warning

A package downgrade and a profile/database rollback are different operations. Do not advertise `pacman -U` of an old package as a safe data rollback unless that reader/writer schema combination is separately proven. A16 owns backup/doctor/safe-mode recovery.
