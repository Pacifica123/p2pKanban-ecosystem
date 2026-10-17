#!/usr/bin/env python3
"""Canonical UTS reader of the A15 release receipt. Read-only, non-root.

tools/a15_issue_receipt.py builds, signs, installs and removes the package in a
terminal and writes .uts-reports/a15-receipts/latest.json. This probe never
builds or changes anything; it decides whether that receipt still proves A15
for this tree on this host:

- PASS (exit 0): the receipt is intact (canonical hash, log hashes, release-key
  signature), every step passed, it was issued for the release inputs this tree
  produces now, and the installed package is the one from the receipt, validated
  by signature, with pacman -Qkk clean.
- SKIP (exit 77): nothing to judge yet — not an Arch host, no receipt, the
  receipt is for other release inputs, or another build is installed. The last
  line says what to run.
- FAIL (exit 1): the receipt was edited, its signature or logs do not verify,
  it records a failed step, or the receipt package fails pacman -Qkk.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import a15_receipt as receipt_format

ROOT = receipt_format.ROOT
SKIP_EXIT = 77


def capture(argv: list[str]) -> tuple[int, str]:
    p = subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout or ""


class Verdict(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def skip(reason: str) -> None:
    raise Verdict("SKIP", reason)


def fail(reason: str) -> None:
    raise Verdict("FAIL", reason)


def judge(report_dir: Path, facts: dict[str, Any]) -> str:
    if shutil.which("pacman") is None:
        skip("pacman нет: это не Arch-хост, чек A15 здесь не выписать")
    latest = receipt_format.LATEST
    if not latest.is_file():
        skip("чек A15 на этом хосте ещё не выписан: " + receipt_format.ISSUE_COMMAND)
    receipt = receipt_format.load(latest)
    if receipt.get("format") != receipt_format.FORMAT or receipt.get("version") != receipt_format.VERSION:
        fail("latest.json не чек A15 этой версии формата")
    if receipt_format.canonical_hash(receipt) != receipt.get("receiptSha256"):
        fail("чек изменён после выписки: сумма канонического JSON не сходится")
    facts["receipt"] = {k: receipt.get(k) for k in ("receiptDir", "issuedAt", "receiptSha256", "overall")}
    work = receipt_format.RECEIPT_ROOT / str(receipt.get("receiptDir", ""))
    if not (work / "receipt.json").is_file() or receipt_format.load(work / "receipt.json") != receipt:
        fail(f"latest.json не совпадает с {work.name}/receipt.json")
    for step in receipt.get("steps", []):
        for command in step.get("commands", []):
            log = work / command["log"]
            if not log.is_file() or receipt_format.sha256_file(log) != command["logSha256"]:
                fail(f"лог {command['log']} шага {step['id']} изменён или пропал")
    if shutil.which("gpg"):
        code, out = capture(["gpg", "--batch", "--status-fd", "1", "--verify", str(work / "receipt.json.asc"), str(work / "receipt.json")])
        valid = re.search(r"^\[GNUPG:\] VALIDSIG (\S+)", out, re.M)
        if code != 0 or not valid or valid.group(1).upper() != str(receipt.get("signing", {}).get("fingerprint", "")).upper():
            fail("подпись чека ключом выпуска не проверяется (receipt.json.asc)")
        facts["receiptSignature"] = valid.group(1)
    else:
        fail("gpg нет: подпись чека не проверить")
    if receipt.get("overall") != "pass":
        bad = next((s for s in receipt.get("steps", []) if s.get("status") != "PASS"), {})
        fail(f"чек выписан с ошибкой на шаге {bad.get('id')}: {bad.get('note', bad.get('status'))}")

    stage = report_dir / "a15-receipt-inputs"
    code, out = capture([sys.executable, "-B", str(ROOT / "tools/a15_prepare_release.py"),
                         "--cargo-lock", str(ROOT / "src-tauri/Cargo.lock"), "--stage", str(stage)])
    if code != 0:
        fail("входы выпуска этого дерева не готовятся:\n" + out)
    now = json.loads((stage / "release-inputs.json").read_text(encoding="utf-8"))["sourceArchive"]["sha256"]
    pkgbuild = receipt_format.sha256_file(stage / "PKGBUILD")
    tree = receipt.get("tree", {})
    facts["tree"] = {"sourceArchiveSha256": now, "pkgbuildSha256": pkgbuild}
    if (now, pkgbuild) != (tree.get("sourceArchiveSha256"), tree.get("pkgbuildSha256")):
        skip(f"чек {receipt['receiptDir']} выписан для других исходников abl; перевыпустите: " + receipt_format.ISSUE_COMMAND)

    package = receipt.get("package", {})
    code, out = capture(["pacman", "-Q", "p2pkanban"])
    installed = out.split()[-1] if code == 0 and out.split() else None
    binary = receipt_format.BINARY
    if installed != package.get("version") or not binary.is_file() or receipt_format.sha256_file(binary) != package.get("binarySha256"):
        skip(f"установлен не пакет из чека {receipt['receiptDir']}; перевыпустите или поставьте его заново: " + receipt_format.ISSUE_COMMAND)
    code, out = capture(["pacman", "-Qi", "p2pkanban"])
    validated = dict(re.findall(r"^([A-Za-z ]+?)\s*:\s*(.*)$", out, re.M)).get("Validated By", "")
    if "Signature" not in validated:
        skip(f"пакет из чека переустановлен без подписи (Validated By: {validated!r}); перевыпустите: " + receipt_format.ISSUE_COMMAND)
    code, out = capture(["pacman", "-Qkk", "p2pkanban"])
    if code != 0 or not re.search(r"\b0 altered files\b", out):
        fail("pacman -Qkk p2pkanban нашёл изменённые файлы:\n" + out)
    facts["installed"] = {"version": installed, "validatedBy": validated, "qkk": out.strip().splitlines()[-1]}
    facts["checklist"] = receipt.get("checklist", [])

    copy = report_dir / "a15-receipt"
    copy.mkdir(parents=True, exist_ok=True)
    for name in ("receipt.json", "receipt.json.asc", "receipt.md"):
        shutil.copy2(work / name, copy / name)
    shutil.copytree(work / "logs", copy / "logs", dirs_exist_ok=True)
    return f"чек {receipt['receiptDir']} действует: собран в чистом chroot, подписан {receipt['signing']['fingerprint'][-16:]}, установлен, pacman -Qkk чист, pacman -R сохранил данные"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    report = args.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    facts: dict[str, Any] = {}
    try:
        status, reason = "PASS", judge(report.parent, facts)
    except Verdict as verdict:
        status, reason = verdict.status, verdict.reason
    except (OSError, json.JSONDecodeError, KeyError) as error:
        status, reason = "FAIL", f"чек не читается: {error}"
    result = {"format": "p2pkanban-a15-host-receipt-probe", "version": 1, "status": status, "reason": reason, **facts}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"A15 RECEIPT: {status} — {reason.splitlines()[0]}")
    return {"PASS": 0, "SKIP": SKIP_EXIT}.get(status, 1)


if __name__ == "__main__":
    raise SystemExit(main())
