#!/usr/bin/env python3
"""Issue the A15 release receipt on an Arch host: build, sign, install, check, remove.

This is the operator side of A15 acceptance. It runs in a terminal because the
clean chroot, pacman trust and package install/remove need sudo, and sudo asks
for a password. Every command, its exit code and a hash of its full log go into
.uts-reports/a15-receipts/<UTC time>/receipt.json; the receipt carries the
sha256 of its own canonical JSON and is detached-signed with the release key.
The canonical UTS (tools/a15_host_receipt_probe.py) never runs any of this: it
only reads the receipt, checks it still matches this tree and the installed
package, and reports PASS/SKIP/FAIL.

Before any sudo the tool prints every privileged command it is about to run and
asks once. --dry-run prints that list and exits. --no-build (or
P2PKANBAN_A15_NO_BUILD=1) skips the chroot build and reuses the package from an
earlier receipt of the same release inputs; everything else still runs.

What it changes on the host, all through pacman itself:
- creates the clean chroot (default /var/lib/archbuild/p2pkanban) if missing;
- adds the release public key to the pacman keyring and locally signs it;
- installs p2pkanban from a local signed repository, removes it, installs it again
  (a sync DB p2pkanban-receipt.db stays in pacman's sync dir; no system repo is
  configured or refreshed, so this cannot cause a partial upgrade).
It never touches the user's existing profile data: the removal check adds marker
files and one marker SecretVault item, compares everything before and after,
and deletes only its own markers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import a15_receipt as receipt_format

ROOT = receipt_format.ROOT
MONOREPO = ROOT.parent
KEY_RE = re.compile(r"^[A-Fa-f0-9]{16,64}$")
REQUIRED = ("sudo", "makechrootpkg", "mkarchroot", "makepkg", "namcap", "gpg", "gpgconf", "repo-add",
            "pacman", "pacman-key", "bsdtar", "secret-tool", "pgrep")
MARKER_ATTRS = ["application", "p2pkanban", "profile", "a15-receipt", "purpose", "a15-receipt-marker-v1"]
VAULT_ATTRS = ["application", "p2pkanban", "purpose", "vault-root-v1"]


class StepFailed(Exception):
    pass


class Session:
    """Runs commands with live output, one full log file per command."""

    def __init__(self, work: Path):
        self.work = work
        self.logs = work / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self.commands: list[dict[str, Any]] = []

    def run(self, argv: list[str], *, cwd: Path | None = None, stdin: bytes | None = None,
            hide_output: bool = False, live: bool = True) -> tuple[int, str]:
        self.count += 1
        name = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(argv[1] if argv[0] == "sudo" else argv[0]).name)
        log = self.logs / f"{self.count:02d}-{name}.log"
        print(f"\n$ {' '.join(argv)}", flush=True)
        process = subprocess.Popen(argv, cwd=cwd or ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.PIPE if stdin is not None else None)
        if stdin is not None:
            process.stdin.write(stdin)
            process.stdin.close()
        chunks: list[bytes] = []
        for line in iter(process.stdout.readline, b""):
            chunks.append(line)
            if live and not hide_output:
                sys.stdout.write(line.decode("utf-8", errors="replace"))
                sys.stdout.flush()
        code = process.wait()
        output = b"".join(chunks).decode("utf-8", errors="replace")
        logged = "<вывод скрыт: в нём секреты связки ключей>\n" if hide_output else output
        log.write_text(f"$ {' '.join(argv)}\n{logged}\n[exit {code}]\n", encoding="utf-8")
        self.commands.append({"argv": " ".join(argv), "exitCode": code, "log": str(log.relative_to(self.work)),
                              "logSha256": receipt_format.sha256_file(log)})
        return code, output

    def must(self, argv: list[str], what: str, **kwargs) -> str:
        code, output = self.run(argv, **kwargs)
        if code != 0:
            raise StepFailed(f"{what}: код {code}")
        return output

    def capture_bytes(self, argv: list[str]) -> bytes:
        p = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise StepFailed(" ".join(argv) + ": " + p.stderr.decode("utf-8", errors="replace").strip())
        return p.stdout


def fail(message: str) -> None:
    raise SystemExit("A15 RECEIPT NOT ISSUED: " + message)


def xdg_roots() -> dict[str, Path]:
    home = Path.home()
    defaults = {"XDG_DATA_HOME": home / ".local/share", "XDG_CONFIG_HOME": home / ".config",
                "XDG_STATE_HOME": home / ".local/state", "XDG_CACHE_HOME": home / ".cache"}
    return {key: Path(os.environ.get(key) or default) / "p2pkanban" for key, default in defaults.items()}


def snapshot(roots: dict[str, Path], skip: set[Path]) -> dict[str, list[int]]:
    files: dict[str, list[int]] = {}
    for key, root in roots.items():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink() and path not in skip:
                st = path.stat()
                files[f"{key}/{path.relative_to(root)}"] = [st.st_size, st.st_mtime_ns]
    return files


def count_items(session: Session, attrs: list[str]) -> int:
    # secret-tool prints secrets with --all; the log keeps only the count.
    code, output = session.run(["secret-tool", "search", "--all", *attrs], hide_output=True)
    if code not in (0, 1):
        raise StepFailed(f"secret-tool search: код {code} (связка ключей заперта или недоступна)")
    return sum(1 for line in output.splitlines() if line.startswith("[/"))


def validated_by(session: Session) -> dict[str, str]:
    info = session.must(["pacman", "-Qi", "p2pkanban"], "pacman -Qi", live=False)
    fields = dict(re.findall(r"^([A-Za-z ]+?)\s*:\s*(.*)$", info, re.M))
    return {"version": fields.get("Version", ""), "validatedBy": fields.get("Validated By", "")}


class Issuer:
    def __init__(self, args: argparse.Namespace, fingerprint: str, work: Path):
        self.args = args
        self.fpr = fingerprint
        self.work = work
        self.stage = work / "stage"
        self.repo = work / "repo"
        self.conf = work / "pacman-receipt.conf"
        self.session = Session(work)
        self.tree: dict[str, Any] = {}
        self.package: dict[str, Any] = {}
        self.pkg: Path | None = None

    # ---------------------------------------------------------------- steps
    def release_inputs(self) -> dict[str, Any]:
        self.session.must([sys.executable, "-B", str(ROOT / "tools/a15_prepare_release.py"),
                           "--cargo-lock", str(ROOT / "src-tauri/Cargo.lock"), "--stage", str(self.stage)],
                          "подготовка входов выпуска")
        manifest = json.loads((self.stage / "release-inputs.json").read_text(encoding="utf-8"))
        pkgbuild = (self.stage / "PKGBUILD").read_text(encoding="utf-8")
        version = "{}-{}".format(*[re.search(rf"^{k}=(\S+)", pkgbuild, re.M).group(1) for k in ("pkgver", "pkgrel")])
        self.package["version"] = version
        self.package["file"] = f"p2pkanban-{version}-x86_64.pkg.tar.zst"
        self.tree.update({
            "sourceArchiveSha256": manifest["sourceArchive"]["sha256"],
            "pkgbuildSha256": receipt_format.sha256_file(self.stage / "PKGBUILD"),
            "cargoLockSha256": manifest["cargoLock"]["sha256"],
        })
        return {"версия пакета": version, "архив исходников": manifest["sourceArchive"]["sha256"]}

    def clean_chroot_build(self) -> dict[str, Any]:
        target = self.stage / self.package["file"]
        if self.args.no_build:
            previous = self.previous_package()
            if previous is None:
                raise StepFailed("--no-build: нет прошлого чека с собранным пакетом этих же входов выпуска; запустите без --no-build")
            shutil.copy2(previous, target)
            self.pkg = target
            return {"пакет": f"взят из {previous.parent.parent.name} (те же входы выпуска), сборка не запускалась"}
        chroot = self.args.chroot
        if not (chroot / "root").is_dir():
            self.session.must(["sudo", "mkdir", "-p", str(chroot)], "каталог chroot")
            self.session.must(["sudo", "mkarchroot", str(chroot / "root"), "base-devel"], "создание чистого chroot")
        self.session.must(["makechrootpkg", "-c", "-u", "-n", "-r", str(chroot)], "makechrootpkg", cwd=self.stage)
        # makepkg --packagelist honours PKGDEST from the operator's makepkg.conf.
        built = [Path(line) for line in self.session.must(["makepkg", "--packagelist"], "makepkg --packagelist",
                                                           cwd=self.stage, live=False).split()]
        found = next((p for p in built if p.name == target.name and p.is_file()), None)
        if found is None:
            raise StepFailed(f"после makechrootpkg нет {target.name}")
        if found != target:
            shutil.copy2(found, target)
        self.pkg = target
        debug = sorted(p.name for p in built if p.name.startswith("p2pkanban-debug-") and p.is_file())
        return {"chroot": str(chroot), "отладочный пакет": ", ".join(debug) or "нет"}

    def package_namcap(self) -> dict[str, Any]:
        _, output = self.session.run(["namcap", str(self.pkg)], cwd=self.stage)
        errors = [line for line in output.splitlines() if " E: " in f" {line} "]
        if errors:
            raise StepFailed("namcap: " + "; ".join(errors[:5]))
        warnings = [line for line in output.splitlines() if " W: " in f" {line} "]
        return {"ошибок namcap": 0, "предупреждений namcap": len(warnings)}

    def package_file_list(self) -> dict[str, Any]:
        names = self.session.must(["bsdtar", "-tf", str(self.pkg)], "список файлов пакета", live=False).split()
        meta = {".PKGINFO", ".BUILDINFO", ".MTREE"}
        files = {"/" + n for n in names if not n.endswith("/") and n not in meta}
        if ".INSTALL" in names:
            raise StepFailed("в пакете есть скриптлет .INSTALL")
        if files != set(receipt_format.PACKAGE_FILES):
            extra = sorted(files - set(receipt_format.PACKAGE_FILES))
            missing = sorted(set(receipt_format.PACKAGE_FILES) - files)
            raise StepFailed(f"состав пакета: лишние {extra}, нет {missing}")
        binary = self.session.capture_bytes(["bsdtar", "-xOf", str(self.pkg), "usr/bin/p2pkanban"])
        self.package["sha256"] = receipt_format.sha256_file(self.pkg)
        self.package["bytes"] = self.pkg.stat().st_size
        self.package["binarySha256"] = receipt_format.sha256_bytes(binary)
        return {"файлов в пакете": len(files), "sha256 пакета": self.package["sha256"]}

    def sign_repo(self) -> dict[str, Any]:
        self.session.must([sys.executable, "-B", str(ROOT / "tools/a15_stage_signed_repo.py"), "--package", str(self.pkg),
                           "--signing-key", self.fpr, "--output", str(self.repo), "--repo-name", receipt_format.REPO_NAME],
                          "подпись пакета и репозитория")
        manifest = json.loads((self.repo / "release-manifest.json").read_text(encoding="utf-8"))
        if manifest["package"]["sha256"] != self.package["sha256"]:
            raise StepFailed("в репозиторий попал не тот пакет")
        return {"ключ": manifest["signingKeyFingerprint"], "база": manifest["database"]["file"]}

    def pacman_trust(self) -> dict[str, Any]:
        public = self.session.capture_bytes(["gpg", "--batch", "--armor", "--export", self.fpr])
        if b"BEGIN PGP PUBLIC KEY BLOCK" not in public:
            raise StepFailed("gpg не выдал публичный ключ выпуска")
        asc = self.repo / "release-key.asc"
        asc.write_bytes(public)
        known, _ = self.session.run(["sudo", "pacman-key", "--list-keys", self.fpr], live=False)
        self.session.must(["sudo", "pacman-key", "--add", str(asc)], "pacman-key --add")
        self.session.must(["sudo", "pacman-key", "--lsign-key", self.fpr], "pacman-key --lsign-key")
        return {"ключ уже был в связке pacman": "да" if known == 0 else "нет, добавлен сейчас"}

    def install_signed_repo(self) -> dict[str, Any]:
        self.conf.write_text(
            "# Generated by tools/a15_issue_receipt.py: only the local signed receipt repository.\n"
            "[options]\nArchitecture = auto\nSigLevel = Required DatabaseOptional\nLocalFileSigLevel = Optional\n\n"
            f"[{receipt_format.REPO_NAME}]\nSigLevel = Required TrustedOnly\nServer = file://{self.repo}\n",
            encoding="utf-8")
        self.session.must(["sudo", "pacman", "--config", str(self.conf), "-Sy", "--noconfirm"], "синхронизация репозитория чека")
        return self.install_and_verify()

    def pacman_qkk(self) -> dict[str, Any]:
        output = self.session.must(["pacman", "-Qkk", "p2pkanban"], "pacman -Qkk")
        if not re.search(r"\b0 altered files\b", output):
            raise StepFailed("pacman -Qkk нашёл изменённые файлы")
        return {"pacman -Qkk": output.strip().splitlines()[-1]}

    def remove_preserves_data(self) -> dict[str, Any]:
        code, _ = self.session.run(["pgrep", "-x", "p2pkanban"], live=False)
        if code == 0:
            raise StepFailed("p2pkanban запущен: закройте окно и повторите")
        roots = xdg_roots()
        nonce = secrets.token_hex(16)
        created = [root for root in roots.values() if not root.exists()]
        markers = {key: root / f".a15-receipt-marker-{nonce[:8]}" for key, root in roots.items()}
        for key, path in markers.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(nonce + "\n", encoding="utf-8")
        before = snapshot(roots, set(markers.values()))
        vault_before = count_items(self.session, VAULT_ATTRS)
        self.session.must(["secret-tool", "store", "--label=p2pKanban A15 receipt marker", *MARKER_ATTRS],
                          "запись метки в SecretVault", stdin=nonce.encode())
        try:
            self.session.must(["sudo", "pacman", "-R", "--noconfirm", "p2pkanban"], "pacman -R")
            still_owned = [p for p in receipt_format.PACKAGE_FILES if Path(p).exists()]
            if still_owned:
                raise StepFailed("после pacman -R остались файлы пакета: " + ", ".join(still_owned))
            code, _ = self.session.run(["pacman", "-Q", "p2pkanban"], live=False)
            if code == 0:
                raise StepFailed("pacman -Q всё ещё видит p2pkanban")
            lost = [key for key, path in markers.items() if not path.is_file() or path.read_text(encoding="utf-8").strip() != nonce]
            if lost:
                raise StepFailed("pacman -R задел метки в " + ", ".join(lost))
            after = snapshot(roots, set(markers.values()))
            if after != before:
                changed = sorted(set(before) ^ set(after) | {k for k in before if k in after and before[k] != after[k]})
                raise StepFailed("pacman -R изменил данные профиля: " + ", ".join(changed[:5]))
            code, secret = self.session.run(["secret-tool", "lookup", *MARKER_ATTRS], hide_output=True)
            if code != 0 or secret.strip() != nonce:
                raise StepFailed("после pacman -R метки в SecretVault нет")
            vault_after = count_items(self.session, VAULT_ATTRS)
            if vault_after != vault_before:
                raise StepFailed(f"записей vault-root было {vault_before}, стало {vault_after}")
        finally:
            for path in markers.values():
                path.unlink(missing_ok=True)
            for root in created:
                try:
                    root.rmdir()
                except OSError:
                    pass
            self.session.run(["secret-tool", "clear", *MARKER_ATTRS], live=False)
        return {"файлов профиля сравнено": len(before), "записей vault-root": vault_before,
                "метки": "в 4 каталогах XDG и в SecretVault пережили pacman -R, затем удалены"}

    def reinstall(self) -> dict[str, Any]:
        facts = self.install_and_verify()
        facts.update(self.pacman_qkk())
        return facts

    # ---------------------------------------------------------------- helpers
    def install_and_verify(self) -> dict[str, Any]:
        self.session.must(["sudo", "pacman", "--config", str(self.conf), "-S", "--noconfirm",
                           f"{receipt_format.REPO_NAME}/p2pkanban"], "установка из репозитория чека")
        info = validated_by(self.session)
        if "Signature" not in info["validatedBy"]:
            raise StepFailed(f"pacman: Validated By = {info['validatedBy']!r}, а нужна подпись")
        if info["version"] != self.package["version"]:
            raise StepFailed(f"установлена {info['version']}, ожидалась {self.package['version']}")
        installed = receipt_format.sha256_file(receipt_format.BINARY)
        if installed != self.package["binarySha256"]:
            raise StepFailed("установленный /usr/bin/p2pkanban отличается от бинарника в пакете")
        return {"Validated By": info["validatedBy"], "версия": info["version"]}

    def previous_package(self) -> Path | None:
        for path in sorted(receipt_format.RECEIPT_ROOT.glob("*/receipt.json"), reverse=True):
            try:
                old = receipt_format.load(path)
            except (OSError, json.JSONDecodeError):
                continue
            built = any(s["id"] == "clean-chroot-build" and s["status"] == "PASS" for s in old.get("steps", []))
            same = all(old.get("tree", {}).get(k) == self.tree[k] for k in ("sourceArchiveSha256", "pkgbuildSha256"))
            candidate = path.parent / "stage" / self.package["file"]
            if built and same and candidate.is_file() and receipt_format.sha256_file(candidate) == old.get("package", {}).get("sha256"):
                return candidate
        return None


def privileged_plan(args: argparse.Namespace) -> list[str]:
    plan = []
    if not args.no_build:
        if not (args.chroot / "root").is_dir():
            plan.append(f"sudo mkdir -p {args.chroot} && sudo mkarchroot {args.chroot}/root base-devel   # создать чистый chroot")
        plan.append(f"makechrootpkg -c -u -n -r {args.chroot}   # сам вызывает sudo для chroot")
    plan += [
        "sudo pacman-key --add <ключ выпуска> && sudo pacman-key --lsign-key <отпечаток>",
        f"sudo pacman --config <конфиг только с [{receipt_format.REPO_NAME}]> -Sy",
        f"sudo pacman --config <тот же> -S {receipt_format.REPO_NAME}/p2pkanban",
        "sudo pacman -R p2pkanban   # проверка, что данные профиля и SecretVault остаются",
        f"sudo pacman --config <тот же> -S {receipt_format.REPO_NAME}/p2pkanban   # вернуть пакет",
    ]
    return plan


def resolve_key(key: str) -> str:
    if not KEY_RE.fullmatch(key):
        fail("--signing-key: нужен шестнадцатеричный отпечаток или id ключа, не файл и не пароль")
    p = subprocess.run(["gpg", "--batch", "--with-colons", "--fingerprint", "--list-secret-keys", key],
                       text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    fprs = [line.split(":")[9] for line in p.stdout.splitlines() if line.startswith("fpr:")]
    if p.returncode != 0 or not fprs:
        fail(f"в связке gpg нет секретного ключа {key}; создайте ключ выпуска: gpg --quick-gen-key 'p2pKanban release <you@example>' ed25519 sign 2y")
    return fprs[0]


def key_outside_repository() -> bool:
    p = subprocess.run(["gpgconf", "--list-dirs", "homedir"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    home = Path((p.stdout or "").strip() or Path.home() / ".gnupg").resolve()
    return not home.is_relative_to(MONOREPO.resolve())


def git_facts() -> dict[str, Any]:
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "."], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return {"gitCommit": head.stdout.strip() if head.returncode == 0 else None,
            "gitDirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None}


def host_facts() -> dict[str, Any]:
    os_name = ""
    try:
        os_name = dict(re.findall(r'^(\w+)="?([^"\n]*)"?', Path("/etc/os-release").read_text(), re.M)).get("PRETTY_NAME", "")
    except OSError:
        pass
    pacman = subprocess.run(["pacman", "-V"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    version = re.search(r"Pacman v\S+", pacman or "")
    return {"os": os_name, "kernel": platform.release(), "pacman": version.group(0) if version else None, "user": getpass.getuser()}


def main() -> int:
    ap = argparse.ArgumentParser(description="Выписать чек A15: собрать, подписать, установить, проверить и удалить пакет pacman.")
    ap.add_argument("--signing-key", default=os.environ.get("P2PKANBAN_RELEASE_KEY", ""),
                    help="отпечаток ключа выпуска из вашей связки gpg (или P2PKANBAN_RELEASE_KEY)")
    ap.add_argument("--chroot", type=Path, default=Path("/var/lib/archbuild/p2pkanban"), help="каталог чистого chroot")
    ap.add_argument("--no-build", action="store_true", default=os.environ.get("P2PKANBAN_A15_NO_BUILD") == "1",
                    help="не собирать: взять пакет прошлого чека с теми же входами выпуска (или P2PKANBAN_A15_NO_BUILD=1)")
    ap.add_argument("--dry-run", action="store_true", help="показать команды с sudo и выйти")
    ap.add_argument("--yes", action="store_true", help="не спрашивать подтверждение перед sudo")
    args = ap.parse_args()

    if sys.stdin.isatty():
        os.environ.setdefault("GPG_TTY", os.ttyname(sys.stdin.fileno()))  # pinentry for the release key
    plan = privileged_plan(args)
    if args.dry_run:
        print("A15: команды с повышенными правами, которые выполнит чек:")
        print("\n".join("  " + line for line in plan))
        return 0
    if os.geteuid() == 0:
        fail("запускайте от своего пользователя, не от root: проверка удаления смотрит ваши XDG-каталоги и связку ключей")
    missing = [name for name in REQUIRED if shutil.which(name) is None]
    if missing:
        fail("нет команд: " + ", ".join(missing) + " (обычно это пакеты devtools, namcap, libsecret)")
    if not (ROOT / "src-tauri/Cargo.lock").is_file():
        fail("нет src-tauri/Cargo.lock: сначала канонический UTS")
    if not args.signing_key:
        fail("укажите --signing-key <отпечаток> (ключ выпуска в вашей связке gpg, вне репозитория)")
    fingerprint = resolve_key(args.signing_key)
    outside = key_outside_repository()
    if not outside:
        fail("каталог gpg лежит внутри репозитория; ключ выпуска должен храниться вне его")

    print("A15: чек выполнит эти команды с повышенными правами:")
    print("\n".join("  " + line for line in plan))
    if not args.yes:
        try:
            if input("Продолжить? [y/N]: ").strip().lower() not in ("y", "д", "yes", "да"):
                fail("отменено")
        except EOFError:
            fail("нужен терминал для подтверждения (или --yes)")

    started = dt.datetime.now(dt.timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    work = receipt_format.RECEIPT_ROOT / stamp
    work.mkdir(parents=True, exist_ok=False)
    issuer = Issuer(args, fingerprint, work)
    issuer.tree.update(git_facts())
    steps: list[dict[str, Any]] = []
    failed = False
    for step_id, title in receipt_format.STEPS:
        if failed:
            steps.append({"id": step_id, "status": "NOT RUN", "seconds": 0.0, "commands": [], "facts": {}})
            continue
        print(f"\n=== {title}", flush=True)
        first = len(issuer.session.commands)
        begin = time.monotonic()
        row: dict[str, Any] = {"id": step_id}
        try:
            row["facts"] = getattr(issuer, step_id.replace("-", "_"))()
            row["status"] = "PASS"
        except StepFailed as error:
            row.update(status="FAIL", note=str(error), facts={})
            failed = True
        row["seconds"] = round(time.monotonic() - begin, 1)
        row["commands"] = issuer.session.commands[first:]
        steps.append(row)

    receipt = receipt_format.seal({
        "format": receipt_format.FORMAT, "version": receipt_format.VERSION, "receiptDir": stamp,
        "issuedAt": started.isoformat().replace("+00:00", "Z"),
        "finishedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": host_facts(), "tree": issuer.tree, "package": issuer.package,
        "signing": {"fingerprint": fingerprint, "keyOutsideRepository": outside},
        "options": {"noBuild": args.no_build, "chroot": str(args.chroot)}, "steps": steps,
    })
    path = work / "receipt.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (work / "receipt.md").write_text(receipt_format.render_markdown(receipt), encoding="utf-8")
    signed = subprocess.run(["gpg", "--yes", "--local-user", fingerprint, "--armor", "--detach-sign",
                             "--output", str(work / "receipt.json.asc"), str(path)]).returncode == 0
    for suffix in ("", ".asc"):
        source = work / ("receipt.json" + suffix)
        if source.is_file():
            shutil.copy2(source, receipt_format.RECEIPT_ROOT / ("latest.json" + suffix))
    shutil.copy2(work / "receipt.md", receipt_format.RECEIPT_ROOT / "latest.md")
    print("\n" + receipt_format.render_markdown(receipt))
    print(f"Чек: {path}")
    if not signed:
        print("A15 RECEIPT: чек не подписан ключом выпуска — UTS его не примет")
        return 1
    print("A15 RECEIPT: " + ("выписан, UTS покажет host.a15-release-receipt PASS" if receipt["overall"] == "pass" else "есть непройденные шаги"))
    return 0 if receipt["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
