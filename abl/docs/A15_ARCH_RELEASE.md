# A15 Arch release procedure

This procedure is for a project-controlled Arch x86_64 release. It never requires the application itself to gain package-manager privileges.

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
