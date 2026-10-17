#!/usr/bin/env python3
"""Shared A15 release-receipt format.

A receipt is written by tools/a15_issue_receipt.py on the Arch host after it has
really built, signed, installed, checked and removed the package. The canonical
UTS probe tools/a15_host_receipt_probe.py only reads it. This module holds what
both sides must agree on: where receipts live, the canonical hash, the mapping
from receipt steps to the A15 acceptance checklist and the human-readable copy.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Override only for the deterministic self-test; real receipts live under ignored .uts-reports/.
RECEIPT_ROOT = Path(os.environ.get("P2PKANBAN_A15_RECEIPT_ROOT") or ROOT / ".uts-reports" / "a15-receipts")
BINARY = Path("/usr/bin/p2pkanban")
LATEST = RECEIPT_ROOT / "latest.json"
FORMAT = "p2pkanban-a15-release-receipt"
VERSION = 1
REPO_NAME = "p2pkanban-receipt"
PACKAGE_FILES = (
    "/usr/bin/p2pkanban",
    "/usr/share/applications/org.p2pkanban.archnative.desktop",
    "/usr/share/icons/hicolor/64x64/apps/p2pkanban.png",
    "/usr/share/licenses/p2pkanban/LICENSE",
)
ISSUE_COMMAND = "cd abl && python3 -B tools/a15_issue_receipt.py --signing-key <fingerprint>"

# Receipt steps in execution order: id, title shown in the receipt.
STEPS = (
    ("release-inputs", "Входы выпуска из этого дерева: архив исходников и PKGBUILD с точной суммой"),
    ("clean-chroot-build", "Сборка в чистом chroot (makechrootpkg -c -u -n), check() выполнен"),
    ("package-namcap", "namcap готового пакета без ошибок"),
    ("package-file-list", "В пакете только /usr/bin/p2pkanban, desktop-файл, иконка и лицензия"),
    ("sign-repo", "Пакет и база репозитория подписаны ключом вне репозитория"),
    ("pacman-trust", "Публичный ключ выпуска доверен в связке pacman"),
    ("install-signed-repo", "Установка из подписанного репозитория, pacman: Validated By Signature"),
    ("pacman-qkk", "pacman -Qkk p2pkanban: ни одного изменённого файла"),
    ("remove-preserves-data", "pacman -R убрал файлы пакета, XDG-данные и записи SecretVault на месте"),
    ("reinstall", "Повторная установка из того же репозитория и pacman -Qkk"),
)
STEP_TITLES = dict(STEPS)

# Board card «A15: пакет pacman и подписанный репозиторий — приёмка на Arch»: open
# checklist items and the receipt steps that prove each of them.
CHECKLIST = (
    ("clean-chroot сборка и namcap", ("clean-chroot-build", "package-namcap", "package-file-list")),
    ("pacman -Qkk после установки из подписанного репозитория", ("install-signed-repo", "pacman-qkk")),
    ("pacman -R сохраняет XDG-данные и записи SecretVault", ("remove-preserves-data", "reinstall")),
    ("Подпись пакета и репозитория внешним ключом", ("sign-repo", "pacman-trust")),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(receipt: dict[str, Any]) -> str:
    body = {k: v for k, v in receipt.items() if k != "receiptSha256"}
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(text.encode("utf-8"))


def checklist(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status = {step["id"]: step["status"] for step in steps}
    rows = []
    for item, needed in CHECKLIST:
        states = [status.get(step_id, "NOT RUN") for step_id in needed]
        rows.append({"item": item, "steps": list(needed), "status": "PASS" if all(s == "PASS" for s in states) else "OPEN"})
    return rows


def seal(receipt: dict[str, Any]) -> dict[str, Any]:
    receipt["checklist"] = checklist(receipt["steps"])
    receipt["overall"] = "pass" if all(s["status"] == "PASS" for s in receipt["steps"]) and len(receipt["steps"]) == len(STEPS) else "fail"
    receipt["receiptSha256"] = canonical_hash(receipt)
    return receipt


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def render_markdown(receipt: dict[str, Any]) -> str:
    tree = receipt.get("tree", {})
    package = receipt.get("package", {})
    signing = receipt.get("signing", {})
    host = receipt.get("host", {})
    verdict = "ВЫПИСАН: все шаги прошли" if receipt.get("overall") == "pass" else "НЕ ВЫПИСАН: есть непройденные шаги"
    out = [
        "# Чек A15: пакет pacman собран, подписан, установлен и удалён на этом хосте",
        "",
        f"**{verdict}**",
        "",
        f"- выписан: {receipt.get('issuedAt')} → {receipt.get('finishedAt')}",
        f"- хост: {host.get('os')} · {host.get('pacman')} · пользователь {host.get('user')}",
        f"- дерево: коммит {tree.get('gitCommit') or 'неизвестен'}{' (есть незакоммиченные правки)' if tree.get('gitDirty') else ''}",
        f"- архив исходников: `{tree.get('sourceArchiveSha256')}`",
        f"- PKGBUILD: `{tree.get('pkgbuildSha256')}`",
        f"- пакет: `{package.get('file')}` · sha256 `{package.get('sha256')}`",
        f"- бинарник в пакете: sha256 `{package.get('binarySha256')}`",
        f"- ключ выпуска: `{signing.get('fingerprint')}` · вне репозитория: {'да' if signing.get('keyOutsideRepository') else 'нет'}",
        f"- сборка: {'пересобран сейчас' if not receipt.get('options', {}).get('noBuild') else 'взят пакет прошлого чека того же дерева (--no-build)'}",
        "",
        "## Пункты приёмки с доски",
        "",
    ]
    for row in receipt.get("checklist", []):
        out.append(f"- [{'x' if row['status'] == 'PASS' else ' '}] {row['item']}")
    out += ["", "## Шаги", ""]
    for step in receipt.get("steps", []):
        out.append(f"- [{step['status']}] `{step['id']}` {STEP_TITLES.get(step['id'], step['id'])} · {step.get('seconds', 0):.1f} с")
        for fact in step.get("facts", {}).items():
            out.append(f"  - {fact[0]}: {fact[1]}")
        if step.get("note"):
            out.append(f"  - {step['note']}")
        for command in step.get("commands", []):
            out.append(f"  - `$ {command['argv']}` → код {command['exitCode']} · лог `{command['log']}` (sha256 {command['logSha256'][:16]}…)")
    out += [
        "",
        f"Сумма чека (sha256 канонического JSON без этого поля): `{receipt.get('receiptSha256')}`.",
        "Подпись чека ключом выпуска — `receipt.json.asc` рядом.",
        "",
    ]
    return "\n".join(out)
