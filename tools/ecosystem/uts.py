#!/usr/bin/env python3
"""UTS экосистемы: общий тестер приёмки на хосте.

Запускается на машине владельца из корня монорепозитория или из его копии в
UserTestSpace. Проверяет все направления по tools/ecosystem/uts_plan.json,
выносит по каждому бинарный вердикт (PASS/FAIL), считает общую готовность в
процентах и показывает расхождение версий между исходниками и тем, что
реально стоит на хосте и телефоне. Логи пишутся в папку и в идентичный zip.

    python3 -B tools/ecosystem/uts.py                    # полный прогон
    python3 -B tools/ecosystem/uts.py --only web,mobile  # часть направлений
    python3 -B tools/ecosystem/uts.py --skip build       # без долгих сборок
    python3 -B tools/ecosystem/uts.py --interactive      # спросить о карточках «Ждёт хоста»
    python3 -B tools/ecosystem/uts.py --list             # показать план
    python3 -B tools/ecosystem/uts.py --self-test        # проверить сам тестер

Только стандартная библиотека. Формат отчёта: docs/ecosystem/uts.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
PLAN = Path(__file__).resolve().with_name("uts_plan.json")
REPORT_SCHEMA = "p2pkanban-uts-report/1"
OUT_DIR = ".uts"

LEVELS = {"static": 1, "build": 2, "host": 3, "device": 3, "manual": 2}
LEVEL_RU = {"static": "исходники", "build": "сборка", "host": "хост", "device": "устройство", "manual": "вручную"}
STATUSES = ("PASS", "WARN", "FAIL", "BLOCKED", "SKIP", "INFO")
CREDIT = {"PASS": 1.0, "WARN": 0.5}
GATE_OK = {"PASS", "WARN"}
RELATION_RU = {
    "match": "совпадает",
    "behind": "отстаёт",
    "ahead": "впереди исходников",
    "different": "другая сборка",
    "missing": "не установлено",
    "unknown": "неизвестно",
}
WEB_COMPOSE_PROJECT = "p2pkanban-bootstrap"
MOBILE_PACKAGE = "dev.p2pkanban.mobile"
ABL_PACKAGE = "p2pkanban"


# ---------------------------------------------------------------- модель


@dataclass
class Check:
    direction: str
    id: str
    title: str
    level: str
    gate: bool = True
    run: list[str] | None = None
    run_online: list[str] | None = None
    probe: str | None = None
    cwd: str = "."
    requires: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    timeout: int = 600
    note: str = ""
    flag_args: dict[str, list[str]] = field(default_factory=dict)
    card: dict | None = None

    @property
    def key(self) -> str:
        return f"{self.direction}.{self.id}"


@dataclass
class Result:
    direction: str
    id: str
    title: str
    level: str
    gate: bool
    status: str
    reason: str = ""
    seconds: float = 0.0
    log: str | None = None
    exit_code: int | None = None
    command: list[str] | None = None
    details: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.direction}.{self.id}"

    def as_json(self) -> dict:
        data = {
            "id": self.key, "title": self.title, "level": self.level, "gate": self.gate,
            "status": self.status, "reason": self.reason, "seconds": round(self.seconds, 2),
            "log": self.log, "exitCode": self.exit_code,
        }
        if self.command:
            data["command"] = self.command
        if self.details:
            data["details"] = self.details
        return data


class PlanError(Exception):
    pass


def load_plan(path: Path) -> dict:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlanError(f"план {path} не читается: {error}")
    if plan.get("schemaVersion") != 1 or not isinstance(plan.get("directions"), list):
        raise PlanError("план: ожидается schemaVersion 1 и список directions")
    seen_dirs = set()
    for direction in plan["directions"]:
        ident = direction.get("id")
        if not ident or ident in seen_dirs:
            raise PlanError(f"план: пустой или повторный id направления {ident!r}")
        seen_dirs.add(ident)
        ids = set()
        for raw in direction.get("checks", []):
            cid = raw.get("id")
            if not cid or cid in ids:
                raise PlanError(f"план: пустой или повторный id проверки {ident}.{cid}")
            ids.add(cid)
            if raw.get("level") not in LEVELS or raw["level"] == "manual":
                raise PlanError(f"план: {ident}.{cid}: уровень должен быть static, build, host или device")
            if not raw.get("run") and not raw.get("probe"):
                raise PlanError(f"план: {ident}.{cid}: нужен run или probe")
            if raw.get("probe") and raw["probe"] not in PROBES:
                raise PlanError(f"план: {ident}.{cid}: неизвестный probe {raw['probe']}")
            for need in raw.get("needs", []):
                if need not in ids:
                    raise PlanError(f"план: {ident}.{cid}: needs {need} должен стоять выше в том же направлении")
    return plan


def plan_checks(plan: dict) -> list[Check]:
    checks = []
    for direction in plan["directions"]:
        base = direction.get("dir", ".")
        for raw in direction.get("checks", []):
            cwd = raw.get("cwd")
            checks.append(Check(
                direction=direction["id"], id=raw["id"], title=raw.get("title", raw["id"]),
                level=raw["level"], gate=raw.get("gate", True), run=raw.get("run"),
                run_online=raw.get("runOnline"), probe=raw.get("probe"),
                cwd=base if cwd is None else str(Path(base) / cwd),
                requires=list(raw.get("requires", [])), needs=list(raw.get("needs", [])),
                timeout=int(raw.get("timeout", 600)), note=raw.get("note", ""),
                flag_args=dict(raw.get("flagArgs", {})),
            ))
    return checks


# ---------------------------------------------------------------- утилиты


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def capture(command: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int | None, str]:
    """Короткая команда-зонд: код возврата и объединённый вывод; None, если не запустилась."""
    executable = shutil.which(command[0])
    if not executable:
        return None, f"нет команды {command[0]}"
    try:
        done = subprocess.run([executable, *command[1:]], cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return None, f"таймаут {timeout} с"
    except OSError as error:
        return None, str(error)
    return done.returncode, (done.stdout + done.stderr).strip()


def first_line(text: str) -> str:
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_tuple(value: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"[.\-+]", value.strip()) if part)


def compare_versions(deployed: str, source: str) -> str:
    if deployed == source:
        return "match"
    try:
        return "behind" if version_tuple(deployed) < version_tuple(source) else "ahead"
    except TypeError:
        return "different"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "check"


def tail(path: Path, lines: int = 15) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    body = [line for line in content if not line.startswith("# ") and line not in ("--- вывод ---", "--- конец ---")]
    return body[-lines:]


# ---------------------------------------------------------------- что проверяется


def git_info(root: Path) -> dict | None:
    code, out = capture(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    if code != 0 or Path(out.strip()).resolve() != root.resolve():
        return None
    _, sha = capture(["git", "-C", str(root), "rev-parse", "HEAD"])
    _, subject = capture(["git", "-C", str(root), "log", "-1", "--format=%s"])
    _, status = capture(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"])
    return {"sha": sha.strip(), "subject": subject.strip(), "dirtyFiles": len([l for l in status.splitlines() if l.strip()])}


def find_workspace_repo(root: Path) -> Path | None:
    """Для копии в UserTestSpace: ближайший предок — git-репозиторий экосистемы."""
    for parent in root.resolve().parents:
        if (parent / ".git").exists() and (parent / "ecosystem.json").is_file():
            return parent
    return None


def tree_identity(root: Path) -> dict:
    identity: dict[str, Any] = {"root": str(root)}
    git = git_info(root)
    if git:
        identity.update(kind="git", sha=git["sha"], subject=git["subject"], dirtyFiles=git["dirtyFiles"])
    else:
        identity["kind"] = "copy"
        match = re.match(r"^project_(\d{8}_\d{6})_after_(.+)_([0-9a-f]{7,40})$", root.resolve().parent.name)
        if root.name == "project" and match:
            identity.update(kind="uts-copy", copiedAt=match.group(1), afterPatch=match.group(2), sha=match.group(3))
        repo = find_workspace_repo(root)
        if repo:
            identity["workspaceRepo"] = str(repo)
    try:
        board = json.loads((root / "board/board.json").read_text(encoding="utf-8"))
        origin = board.get("origin", {})
        identity["boardRevision"] = origin.get("boardRevision")
        identity["lastPatchId"] = origin.get("lastPatchId")
    except (OSError, json.JSONDecodeError):
        pass
    return identity


def host_facts() -> dict:
    facts: dict[str, Any] = {
        "system": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    probes = {
        "git": ["git", "--version"], "node": ["node", "--version"], "npm": ["npm", "--version"],
        "cargo": ["cargo", "--version"], "rustc": ["rustc", "--version"], "docker": ["docker", "--version"],
        "adb": ["adb", "version"], "java": ["java", "-version"], "pacman": ["pacman", "--version"],
        "devctl": ["devctl", "--version"],
    }
    tools = {}
    for name, command in probes.items():
        code, out = capture(command, timeout=15)
        lines = [l.strip(" .-") for l in out.splitlines() if l.strip() and not l.startswith("Picked up")]
        if name == "pacman":
            lines = [l for l in lines if "Pacman v" in l] or lines
        tools[name] = None if code is None else (lines[0][:80] if lines else "")
    facts["tools"] = tools
    os_release = Path("/etc/os-release")
    if os_release.is_file():
        for line in os_release.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("PRETTY_NAME="):
                facts["os"] = line.split("=", 1)[1].strip('"')
    return facts


# ---------------------------------------------------------------- зонды


@dataclass
class ProbeContext:
    root: Path
    options: argparse.Namespace
    tree: dict
    versions: dict
    cache: dict
    artifacts: Path
    log: Callable[[str], None]


@dataclass
class ProbeOutcome:
    status: str
    reason: str
    details: dict = field(default_factory=dict)


def record_version(ctx: ProbeContext, direction: str, source: dict, deployed: list[dict]) -> None:
    entry = ctx.versions.setdefault(direction, {"source": {}, "deployed": []})
    entry["source"].update(source)
    entry["deployed"].extend(deployed)


def web_discover(ctx: ProbeContext) -> dict:
    if "web" in ctx.cache:
        return ctx.cache["web"]
    info: dict[str, Any] = {"containers": {}}
    ctx.cache["web"] = info
    url = ctx.options.web_url
    if not url:
        code, out = capture(["docker", "ps", "--all", "--filter", f"label=com.docker.compose.project={WEB_COMPOSE_PROJECT}",
                             "--format", "{{json .}}"], timeout=30)
        ctx.log(f"$ docker ps --filter label=com.docker.compose.project={WEB_COMPOSE_PROJECT}\n{out}\n")
        if code is None:
            info["blocked"] = out
            return info
        if code != 0:
            info["blocked"] = f"нет доступа к Docker: {first_line(out)}"
            return info
        for line in out.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            labels = dict(item.split("=", 1) for item in row.get("Labels", "").split(",") if "=" in item)
            service = labels.get("com.docker.compose.service", row.get("Names", "?"))
            info["containers"][service] = {"image": row.get("Image"), "state": row.get("State"), "status": row.get("Status"),
                                           "ports": row.get("Ports", "")}
        gateway = info["containers"].get("gateway", {})
        match = re.search(r"([0-9.:\[\]]*):(\d+)->8080/tcp", gateway.get("ports", ""))
        if match:
            host = match.group(1) or "127.0.0.1"
            host = "127.0.0.1" if host in ("0.0.0.0", "::", "[::]") else host
            url = f"http://{host}:{match.group(2)}"
    info["url"] = url
    if not url:
        return info
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for path in ("/api/v1/health", "/health"):
        try:
            with opener.open(url.rstrip("/") + path, timeout=8) as response:
                body = response.read(65536).decode("utf-8", errors="replace")
            ctx.log(f"GET {url}{path} → {response.status}\n{body}\n")
            payload = json.loads(body)
        except (urllib.error.URLError, OSError, ValueError) as error:
            ctx.log(f"GET {url}{path} → {error}\n")
            continue
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if isinstance(data, dict) and data.get("version"):
            info["health"] = {"path": path, "status": data.get("status"), "version": data.get("version"), "service": data.get("service")}
            break
    image = (info["containers"].get("backend") or info["containers"].get("web") or {}).get("image") or ""
    if ":" in image:
        info["imageTag"] = image.rsplit(":", 1)[1]
    return info


def probe_web_node(check: Check, ctx: ProbeContext) -> ProbeOutcome:
    outcome = web_node_state(ctx)
    if outcome.status != "PASS":
        version = (ctx.root / "web/VERSION").read_text(encoding="utf-8").strip()
        record_version(ctx, "web", {"version": version}, [{"where": "узел", "version": None, "build": None,
                                                           "relation": "unknown", "detail": outcome.reason}])
    return outcome


def web_node_state(ctx: ProbeContext) -> ProbeOutcome:
    info = web_discover(ctx)
    if info.get("blocked"):
        return ProbeOutcome("BLOCKED", info["blocked"])
    containers = info["containers"]
    if not ctx.options.web_url and not containers:
        return ProbeOutcome("FAIL", f"контейнеров проекта {WEB_COMPOSE_PROJECT} нет: узел не развёрнут на этом хосте")
    stopped = sorted(name for name, row in containers.items() if name in ("backend", "web", "gateway", "postgres") and row.get("state") != "running")
    health = info.get("health")
    if not health:
        why = f"остановлены: {', '.join(stopped)}" if stopped else "health не ответил"
        return ProbeOutcome("FAIL", f"узел не отвечает ({why}); URL {info.get('url') or 'не найден'}", {"containers": containers})
    if stopped:
        return ProbeOutcome("FAIL", f"health отвечает, но остановлены: {', '.join(stopped)}", {"containers": containers})
    return ProbeOutcome("PASS", f"{info['url']} отвечает, версия {health['version']}", {"health": health, "containers": containers})


def web_source_identities(ctx: ProbeContext) -> tuple[str, list[str]]:
    web = ctx.root / "web"
    version = (web / "VERSION").read_text(encoding="utf-8").strip()
    identities = []
    if ctx.tree.get("kind") == "git" and ctx.tree.get("sha"):
        identities.append(ctx.tree["sha"][:12])
    code, out = capture([sys.executable, "-I", "-c",
                         "import sys; from pathlib import Path; r=Path(sys.argv[1]); sys.path.insert(0, str(r/'tools')); "
                         "import container_bootstrap as c; print(c.source_fingerprint(r))", str(web)], timeout=120)
    if code == 0 and re.fullmatch(r"[0-9a-f]{64}", out.strip().splitlines()[-1] if out.strip() else ""):
        identities.append(out.strip().splitlines()[-1][:12])
    else:
        ctx.log(f"отпечаток web не вычислен: {out}\n")
    return version, identities


def same_web_tree(ctx: ProbeContext, commit: str) -> bool | None:
    """True, если web/ в коммите сборки узла совпадает с web/ проверяемого дерева."""
    repo = ctx.root if ctx.tree.get("kind") == "git" else Path(ctx.tree["workspaceRepo"]) if ctx.tree.get("workspaceRepo") else None
    reference = ctx.tree.get("sha")
    if not repo or not reference:
        return None
    code, resolved = capture(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"])
    if code != 0:
        return None
    code, _ = capture(["git", "-C", str(repo), "diff", "--quiet", resolved.strip(), reference, "--", "web"], timeout=60)
    return {0: True, 1: False}.get(code)


def probe_web_node_build(check: Check, ctx: ProbeContext) -> ProbeOutcome:
    info = web_discover(ctx)
    version, identities = web_source_identities(ctx)
    health = info.get("health") or {}
    tag = info.get("imageTag") or ""
    node_version = health.get("version") or (tag.split("-", 1)[0] if tag else None)
    built_from = tag.split("-", 1)[1] if "-" in tag else None
    deployed = {"where": f"узел {info.get('url') or '?'}", "version": node_version, "build": built_from or tag or None}
    if not node_version:
        deployed["relation"] = "unknown"
        record_version(ctx, "web", {"version": version, "build": identities}, [deployed])
        return ProbeOutcome("BLOCKED", "версию узла узнать не удалось")
    relation = compare_versions(node_version, version)
    reason = f"узел {node_version}, исходники {version}"
    status = "PASS"
    if relation != "match":
        status = "FAIL"
        reason += f": узел {RELATION_RU[relation]}"
    elif built_from and identities and built_from[:12] in identities:
        reason += f"; сборка {built_from} — это дерево"
    elif built_from and re.fullmatch(r"[0-9a-f]{7,40}", built_from):
        same = same_web_tree(ctx, built_from)
        if same:
            reason += f"; сборка из коммита {built_from}, web/ в нём такой же"
        elif same is False:
            relation, status = "different", "FAIL"
            reason += f"; сборка из коммита {built_from}, web/ в нём другой"
        else:
            relation, status = "different", "FAIL"
            reason += (f"; сборка {built_from} не опознана: это не коммит и не отпечаток проверяемого web "
                       f"(ожидалось одно из {', '.join(identities) or 'нет данных'})")
    else:
        relation, status = "unknown", "WARN"
        reason += f"; тег образа {tag or 'неизвестен'} не позволяет сверить сборку"
    deployed["relation"] = relation
    record_version(ctx, "web", {"version": version, "build": identities}, [deployed])
    return ProbeOutcome(status, reason, {"imageTag": tag, "sourceIdentities": identities})


def mobile_source(root: Path) -> dict:
    mobile = root / "mobile"
    package = json.loads((mobile / "package.json").read_text(encoding="utf-8"))
    expo = json.loads((mobile / "app.json").read_text(encoding="utf-8")).get("expo", {})
    gradle = (mobile / "android/app/build.gradle").read_text(encoding="utf-8") if (mobile / "android/app/build.gradle").is_file() else ""
    code = re.search(r"versionCode\s+(\d+)", gradle)
    name = re.search(r'versionName\s+"([^"]+)"', gradle)
    return {
        "package.json": package.get("version"),
        "app.json": expo.get("version"),
        "app.json versionCode": expo.get("android", {}).get("versionCode"),
        "build.gradle": name.group(1) if name else None,
        "build.gradle versionCode": int(code.group(1)) if code else None,
        "applicationId": expo.get("android", {}).get("package") or MOBILE_PACKAGE,
    }


def probe_mobile_versions(check: Check, ctx: ProbeContext) -> ProbeOutcome:
    source = mobile_source(ctx.root)
    names = {source["package.json"], source["app.json"], source["build.gradle"]}
    codes = {source["app.json versionCode"], source["build.gradle versionCode"]}
    detail = (f"package.json {source['package.json']}, app.json {source['app.json']}/{source['app.json versionCode']}, "
              f"build.gradle {source['build.gradle']}/{source['build.gradle versionCode']}")
    if len(names) != 1 or len(codes) != 1 or None in names | codes:
        return ProbeOutcome("FAIL", f"версии расходятся: {detail}", source)
    return ProbeOutcome("PASS", detail, source)


def probe_mobile_device(check: Check, ctx: ProbeContext) -> ProbeOutcome:
    source = mobile_source(ctx.root)
    version, code = source["app.json"], source["app.json versionCode"]
    package = source["applicationId"]
    deployed: list[dict] = []
    apk_dir = ctx.root / "mobile/dist"
    for apk in sorted(apk_dir.glob("*.apk")) if apk_dir.is_dir() else []:
        stamp = datetime.fromtimestamp(apk.stat().st_mtime, timezone.utc).replace(microsecond=0)
        deployed.append({"where": f"файл mobile/dist/{apk.name}", "version": None, "build": sha256_file(apk)[:12],
                         "relation": "unknown", "detail": f"собран {iso(stamp)}; версию APK без aapt не прочитать"})
    status, reason = "BLOCKED", ""
    rc, out = capture(["adb", "devices"], timeout=30)
    ctx.log(f"$ adb devices\n{out}\n")
    if rc is None:
        reason = "adb не найден: телефон проверить нельзя"
    elif rc != 0:
        reason = f"adb devices: {first_line(out)}"
    else:
        rows = [line.split("\t") for line in out.splitlines()[1:] if "\t" in line]
        ready = [serial for serial, state in rows if state == "device"]
        other = [f"{serial} ({state})" for serial, state in rows if state != "device"]
        if not ready:
            reason = "телефон не подключён по adb" + (f"; есть, но недоступны: {', '.join(other)}" if other else "")
        verdicts = []
        for serial in ready:
            _, model = capture(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=30)
            _, dump = capture(["adb", "-s", serial, "shell", "dumpsys", "package", package], timeout=60)
            ctx.log(f"$ adb -s {serial} shell dumpsys package {package} (фрагмент)\n" +
                    "\n".join(l for l in dump.splitlines() if re.search(r"versionCode|versionName|lastUpdateTime|firstInstallTime", l)) + "\n")
            where = f"телефон {first_line(model) or serial}"
            found_code = re.search(r"versionCode=(\d+)", dump)
            found_name = re.search(r"versionName=(\S+)", dump)
            updated = re.search(r"lastUpdateTime=([0-9: -]+)", dump)
            if not found_code:
                deployed.append({"where": where, "version": None, "build": None, "relation": "missing",
                                 "detail": f"{package} не установлен"})
                verdicts.append("missing")
                continue
            device_code = int(found_code.group(1))
            relation = "match" if device_code == code else "behind" if device_code < code else "ahead"
            detail = f"обновлено {updated.group(1).strip()}" if updated else ""
            if relation == "match":
                detail += "; совпадение по versionCode (сборки с одинаковым versionCode неразличимы)"
            elif relation == "behind":
                detail += f"; отстаёт на {code - device_code} versionCode"
            deployed.append({"where": where, "version": f"{found_name.group(1) if found_name else '?'} ({device_code})",
                             "build": None, "relation": relation, "detail": detail.strip("; ")})
            verdicts.append(relation)
        if verdicts:
            if "match" in verdicts:
                status, reason = "PASS", f"на телефоне versionCode {code}, как в исходниках"
            elif "behind" in verdicts:
                status, reason = "FAIL", f"телефон отстаёт: стоит {', '.join(d['version'] for d in deployed if d['relation'] == 'behind')}, в исходниках {version} ({code})"
            elif "ahead" in verdicts:
                status, reason = "FAIL", f"на телефоне сборка новее исходников ({version} ({code})): проверяется не то дерево"
            else:
                status, reason = "FAIL", f"{package} не установлен на подключённом телефоне"
    if status == "BLOCKED":
        deployed.append({"where": "телефон", "version": None, "build": None, "relation": "unknown", "detail": reason})
    record_version(ctx, "mobile", {"version": f"{version} ({code})"}, deployed)
    return ProbeOutcome(status, reason)


def probe_abl_uts(check: Check, ctx: ProbeContext, exit_code: int | None) -> tuple[ProbeOutcome, list[Result]]:
    results_path = ctx.artifacts / "results.json"
    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ProbeOutcome("FAIL", f"UTS abl не оставил results.json (код {exit_code})"), []
    imported = []
    level_of = lambda rid: ("static" if rid.startswith(("deterministic.", "postbuild.")) else
                            "build" if rid.startswith(("frontend.", "cargo.")) else "host")
    relative = ctx.artifacts.relative_to(ctx.artifacts.parents[2])
    for row in data.get("results", []):
        status = row.get("status", "FAIL")
        status = status if status in STATUSES else "INFO"
        imported.append(Result(
            direction="abl", id=f"uts.{row.get('id')}", title=row.get("id", "?"), level=level_of(row.get("id", "")),
            gate=False, status=status, reason=row.get("note", ""), seconds=float(row.get("seconds") or 0),
            log=str(relative / row["log"]) if row.get("log") else None, exit_code=row.get("exit_code"),
        ))
    counts = {s: sum(1 for r in imported if r.status == s) for s in STATUSES}
    summary = ", ".join(f"{s} {n}" for s, n in counts.items() if n)
    ctx.cache["ablManual"] = data.get("manualEvidence", [])
    record_version(ctx, "abl", {"stage": data.get("stage")}, [])
    if data.get("overall") == "pass":
        return ProbeOutcome("PASS", f"этап {data.get('stage')}: overall pass ({summary})"), imported
    failures = [r for r in imported if r.status == "FAIL"] + [r for r in imported if r.status == "BLOCKED"]
    shown = [f"[{r.status}] {r.title}" + (f" — {r.reason}" if r.reason else "") + (f" · `{r.log}`" if r.log else "")
             for r in failures[:8]]
    if len(failures) > 8:
        shown.append(f"… и ещё {len(failures) - 8}")
    return ProbeOutcome("FAIL", f"этап {data.get('stage')}: overall {data.get('overall')} ({summary})",
                        {"failures": shown}), imported


def probe_abl_installed(check: Check, ctx: ProbeContext) -> ProbeOutcome:
    pkgbuild = (ctx.root / "abl/packaging/arch/PKGBUILD").read_text(encoding="utf-8")
    fields = dict(re.findall(r"^(pkgname|pkgver|pkgrel)=(\S+)", pkgbuild, re.M))
    source = f"{fields.get('pkgver')}-{fields.get('pkgrel')}"
    name = fields.get("pkgname", ABL_PACKAGE)
    code, out = capture(["pacman", "-Q", name])
    ctx.log(f"$ pacman -Q {name}\n{out}\n")
    if code is None:
        record_version(ctx, "abl", {"package": source}, [{"where": "pacman", "version": None, "build": None, "relation": "unknown", "detail": "pacman нет"}])
        return ProbeOutcome("BLOCKED", "pacman нет: это не Arch-хост")
    if code != 0:
        record_version(ctx, "abl", {"package": source}, [{"where": "pacman", "version": None, "build": None, "relation": "missing"}])
        return ProbeOutcome("FAIL", f"пакет {name} не установлен")
    installed = out.split()[-1]
    relation = compare_versions(installed, source)
    record_version(ctx, "abl", {"package": source}, [{"where": "pacman", "version": installed, "build": None, "relation": relation}])
    if relation == "match":
        return ProbeOutcome("PASS", f"установлен {name} {installed}, как в PKGBUILD")
    return ProbeOutcome("FAIL", f"установлен {name} {installed}, в PKGBUILD {source}: {RELATION_RU[relation]}")


def probe_devctl_installed(check: Check, ctx: ProbeContext) -> ProbeOutcome:
    script = ctx.root / "devctl/devctl.py"
    match = re.search(r'^DEVCTL_VERSION\s*=\s*"([^"]+)"', script.read_text(encoding="utf-8"), re.M)
    version = match.group(1) if match else "?"
    source_sha = sha256_file(script)
    launcher = shutil.which("devctl")
    if not launcher:
        record_version(ctx, "devctl", {"version": version, "build": source_sha[:12]}, [{"where": "PATH", "version": None, "build": None, "relation": "missing"}])
        return ProbeOutcome("FAIL", "команды devctl нет в PATH")
    code, out = capture(["devctl", "--version"])
    found = re.search(r"devctl\s+(\S+)", out or "")
    installed = found.group(1) if found else None
    managed = None
    try:
        text = Path(launcher).read_text(encoding="utf-8", errors="replace")
        quoted = re.search(r"exec\s+\S+\s+'([^']+devctl\.py)'", text)
        managed = Path(quoted.group(1)) if quoted else None
    except OSError:
        pass
    managed = managed or Path.home() / ".local/share/devctl/devctl.py"
    installed_sha = sha256_file(managed)[:12] if managed.is_file() else None
    ctx.log(f"launcher {launcher}\nmanaged {managed} sha {installed_sha}\n$ devctl --version\n{out}\n")
    if not installed:
        relation = "unknown"
    elif installed != version:
        relation = compare_versions(installed, version)
    else:
        relation = "match" if installed_sha in (None, source_sha[:12]) else "different"
    deployed = {"where": str(launcher), "version": installed, "build": installed_sha, "relation": relation}
    record_version(ctx, "devctl", {"version": version, "build": source_sha[:12]}, [deployed])
    if relation == "match":
        return ProbeOutcome("PASS", f"установлен devctl {installed}, тот же файл")
    if relation == "different":
        return ProbeOutcome("WARN", f"установлен devctl {installed}, но файл отличается от devctl/devctl.py ({installed_sha} ≠ {source_sha[:12]})")
    return ProbeOutcome("WARN", f"установлен devctl {installed or '?'}, в исходниках {version}: {RELATION_RU[relation]}")


PROBES: dict[str, Callable] = {
    "web-node": probe_web_node,
    "web-node-build": probe_web_node_build,
    "mobile-versions": probe_mobile_versions,
    "mobile-device": probe_mobile_device,
    "abl-uts": probe_abl_uts,
    "abl-installed": probe_abl_installed,
    "devctl-installed": probe_devctl_installed,
}


# ---------------------------------------------------------------- доска


def board_cards(root: Path, column_name: str, directions: set[str]) -> list[Check]:
    try:
        bundle = json.loads((root / "board/board.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    payload = bundle.get("payload", {})
    column = next((c for c in payload.get("columns", []) if c.get("name") == column_name), None)
    if not column:
        return []
    label_names = {label["id"]: label["name"] for label in payload.get("labels", [])}
    labels: dict[str, list[str]] = {}
    for edge in payload.get("cardLabels", []):
        labels.setdefault(edge["cardId"], []).append(label_names.get(edge["labelId"], ""))
    checklists = {c["id"]: c["cardId"] for c in payload.get("checklists", [])}
    open_items: dict[str, list[str]] = {}
    for item in sorted(payload.get("checklistItems", []), key=lambda i: i.get("position", 0)):
        if not item.get("isDone"):
            open_items.setdefault(checklists.get(item["checklistId"], ""), []).append(item["title"])
    checks = []
    cards = sorted((c for c in payload.get("cards", []) if c.get("columnId") == column["id"] and not c.get("archivedAt")),
                   key=lambda c: c.get("position", 0))
    for card in cards:
        owners = ["ecosystem" if name == "экосистема" else name for name in labels.get(card["id"], [])]
        owners = [name for name in owners if name in directions] or ["ecosystem"]
        info = {"cardId": card["id"], "title": card["title"], "openItems": open_items.get(card["id"], []), "directions": owners}
        for owner in owners:
            short = hashlib.sha1(card["id"].encode("utf-8")).hexdigest()[:8]
            checks.append(Check(direction=owner, id=f"card-{short}", title=card["title"], level="manual",
                                gate=False, card=info))
    return checks


# ---------------------------------------------------------------- прогон


class Runner:
    def __init__(self, root: Path, plan: dict, options: argparse.Namespace, run_dir: Path, *, quiet: bool = False):
        self.root = root
        self.plan = plan
        self.options = options
        self.run_dir = run_dir
        self.quiet = quiet
        self.results: list[Result] = []
        self.by_key: dict[str, Result] = {}
        self.versions: dict = {}
        self.cache: dict = {}
        self.tree = tree_identity(root)
        self.answers: dict[str, dict] = {}
        self.interrupted = False

    def say(self, text: str) -> None:
        if not self.quiet:
            print(text, flush=True)

    def selected(self) -> list[Check]:
        directions = [d["id"] for d in self.plan["directions"]]
        only = set(self.options.only or directions)
        checks = [c for c in plan_checks(self.plan) if c.direction in only]
        column = self.plan.get("boardColumn")
        if column:
            checks += [c for c in board_cards(self.root, column, set(directions)) if c.direction in only]
        order = {name: index for index, name in enumerate(directions)}
        return sorted(checks, key=lambda c: order[c.direction])

    def add(self, result: Result) -> Result:
        self.results.append(result)
        self.by_key[result.key] = result
        return result

    def execute(self) -> None:
        checks = self.selected()
        counters: dict[str, int] = {}
        total = len(checks)
        for index, check in enumerate(checks, 1):
            counters[check.direction] = counters.get(check.direction, 0) + 1
            number = counters[check.direction]
            prefix = f"[{index:>2}/{total}] {check.direction:<9} {check.id:<28}"
            if self.interrupted:
                result = self.skipped(check, "прогон прерван")
            else:
                if not self.quiet and check.level != "manual":
                    print(prefix, end=" ", flush=True)
                try:
                    result = self.run_check(check, number)
                except KeyboardInterrupt:
                    self.interrupted = True
                    result = self.skipped(check, "прогон прерван (Ctrl+C)")
            self.add(result)
            if not self.quiet:
                if check.level == "manual":
                    print(f"{prefix} {result.status}")
                else:
                    print(f"{result.status} {result.seconds:.1f}s" + (f" — {result.reason}" if result.status != "PASS" and result.reason else ""))
            for extra in result.details.pop("_imported", []):
                self.add(extra)

    def skipped(self, check: Check, reason: str) -> Result:
        return Result(check.direction, check.id, check.title, check.level, check.gate, "SKIP", reason)

    def run_check(self, check: Check, number: int) -> Result:
        if check.level in self.options.skip:
            return self.skipped(check, f"уровень «{LEVEL_RU[check.level]}» пропущен флагом --skip")
        if check.card:
            return self.ask_card(check)
        for need in check.needs:
            dependency = self.by_key.get(f"{check.direction}.{need}")
            if dependency is None or dependency.status not in GATE_OK:
                state = dependency.status if dependency else "не запускалась"
                return Result(check.direction, check.id, check.title, check.level, check.gate, "BLOCKED",
                              f"зависит от {need}: {state}")
        missing = [tool for tool in check.requires if not shutil.which(tool)]
        if missing:
            return Result(check.direction, check.id, check.title, check.level, check.gate, "BLOCKED",
                          f"нет команды {', '.join(missing)}")
        log_rel = Path("logs") / check.direction / f"{number:02d}-{slug(check.id)}.log"
        log_path = self.run_dir / log_rel
        log_path.parent.mkdir(parents=True, exist_ok=True)
        artifacts = log_path.with_suffix(".d")
        cwd = (self.root / check.cwd).resolve()
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            command = self.command_for(check, artifacts) if check.run else None
            log.write(f"# проверка: {check.key}\n# что: {check.title}\n# уровень: {check.level}  гейт: {'да' if check.gate else 'нет'}\n")
            if check.note:
                log.write(f"# заметка: {check.note}\n")
            log.write(f"# каталог: {cwd.relative_to(self.root.resolve()) if cwd != self.root.resolve() else '.'}\n")
            if command:
                log.write(f"# команда: {' '.join(command)}\n")
            log.write(f"# начало: {iso(now_utc())}\n--- вывод ---\n")
            log.flush()
            exit_code, timed_out = None, False
            if command:
                exit_code, timed_out = self.spawn(command, cwd, log, check.timeout)
            ctx = ProbeContext(self.root, self.options, self.tree, self.versions, self.cache, artifacts,
                               lambda text: (log.write(text), log.flush()))
            imported: list[Result] = []
            if check.probe == "abl-uts":
                outcome, imported = probe_abl_uts(check, ctx, exit_code)
                if timed_out:
                    outcome = ProbeOutcome("FAIL", f"таймаут {check.timeout} с")
            elif check.probe:
                try:
                    outcome = PROBES[check.probe](check, ctx)
                except (OSError, ValueError, KeyError) as error:
                    outcome = ProbeOutcome("FAIL", f"зонд упал: {error}")
            elif timed_out:
                outcome = ProbeOutcome("FAIL", f"таймаут {check.timeout} с")
            elif exit_code == 0:
                outcome = ProbeOutcome("PASS", "")
            else:
                outcome = ProbeOutcome("FAIL", f"код возврата {exit_code}")
            seconds = time.monotonic() - started
            log.write(f"\n--- конец ---\n# итог: {outcome.status}" + (f" — {outcome.reason}" if outcome.reason else "") +
                      f"\n# код: {exit_code}  секунд: {seconds:.2f}\n")
        if check.note and outcome.status != "PASS":
            outcome.reason = f"{outcome.reason}; {check.note}".strip("; ")
        details = dict(outcome.details)
        if imported:
            details["_imported"] = imported
        return Result(check.direction, check.id, check.title, check.level, check.gate, outcome.status, outcome.reason,
                      seconds, str(log_rel), exit_code, command, details)

    def command_for(self, check: Check, artifacts: Path) -> list[str]:
        base = check.run_online if (self.options.allow_network and check.run_online) else check.run
        command = [part.replace("{python}", sys.executable).replace("{artifacts}", str(artifacts)) for part in base]
        if self.options.allow_network:
            command += check.flag_args.get("allowNetwork", [])
        if self.options.no_runtime:
            command += check.flag_args.get("noRuntime", [])
        if command and command[0] != sys.executable:
            command[0] = shutil.which(command[0]) or command[0]
        return command

    def spawn(self, command: list[str], cwd: Path, log, timeout: int) -> tuple[int | None, bool]:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        kwargs: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
        try:
            process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       env=env, **kwargs)
        except OSError as error:
            log.write(f"не удалось запустить: {error}\n")
            return None, False
        try:
            return process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            self.stop(process)
            log.write(f"\n[uts] остановлено по таймауту {timeout} с\n")
            return None, True
        except KeyboardInterrupt:
            self.stop(process)
            log.write("\n[uts] прервано пользователем\n")
            raise

    @staticmethod
    def stop(process: subprocess.Popen) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

    def ask_card(self, check: Check) -> Result:
        card = check.card or {}
        make = lambda status, reason, extra=None: Result(check.direction, check.id, check.title, "manual", False, status, reason,
                                                         details={"cardId": card.get("cardId"), "openItems": card.get("openItems", []), **(extra or {})})
        if card.get("cardId") in self.answers:
            answer = self.answers[card["cardId"]]
            return make(answer["status"], answer["reason"], {"answeredAt": answer["at"]})
        if not self.options.interactive:
            return make("SKIP", "нужно подтверждение человека: запустите с --interactive")
        print(f"\n— Карточка «{card['title']}» ({', '.join(card['directions'])})")
        for item in card.get("openItems", []):
            print(f"    · {item}")
        while True:
            try:
                reply = input("  Принято на хосте? [y — да / n — нет / Enter — пропустить]: ").strip().lower()
            except EOFError:
                reply = ""
            if reply in ("", "y", "n", "д", "н"):
                break
        if not reply:
            status, reason = "SKIP", "пропущено при опросе"
        else:
            try:
                comment = input("  Комментарий (Enter — без него): ").strip()
            except EOFError:
                comment = ""
            accepted = reply in ("y", "д")
            status = "PASS" if accepted else "FAIL"
            reason = ("подтверждено владельцем" if accepted else "владелец: не принято") + (f": {comment}" if comment else "")
        self.answers[card["cardId"]] = {"status": status, "reason": reason, "at": iso(now_utc())}
        return make(status, reason, {"answeredAt": self.answers[card["cardId"]]["at"]})


# ---------------------------------------------------------------- оценка


def direction_scores(plan: dict, results: list[Result], only: set[str] | None) -> list[dict]:
    rows = []
    for direction in plan["directions"]:
        ident = direction["id"]
        own = [r for r in results if r.direction == ident]
        if only and ident not in only:
            rows.append({"id": ident, "title": direction.get("title", ident), "verdict": None, "readiness": None})
            continue
        weighed = [r for r in own if r.status != "INFO"]
        weight = lambda r: LEVELS[r.level] * (1.0 if r.gate else 0.5)
        total = sum(weight(r) for r in weighed)
        earned = sum(weight(r) * CREDIT.get(r.status, 0.0) for r in weighed)
        executed = [r for r in weighed if r.status not in ("SKIP", "BLOCKED")]
        gates = [r for r in own if r.gate]
        failed = [r for r in gates if r.status not in GATE_OK]
        levels = {}
        for level in LEVELS:
            subset = [r for r in weighed if r.level == level]
            if subset:
                levels[level] = {"passed": sum(1 for r in subset if r.status in GATE_OK), "total": len(subset)}
        rows.append({
            "id": ident, "title": direction.get("title", ident),
            "verdict": "PASS" if gates and not failed else "FAIL",
            "readiness": round(100 * earned / total) if total else 0,
            "coverage": round(100 * len(executed) / len(weighed)) if weighed else 0,
            "levels": levels,
            "failedGates": [{"id": r.key, "status": r.status, "reason": r.reason} for r in failed],
        })
    return rows


def readiness_label(value: int) -> str:
    if value >= 100:
        return "принято полностью"
    if value >= 90:
        return "готово с оговорками"
    if value >= 70:
        return "почти готово"
    if value >= 40:
        return "частично готово"
    return "далеко от готовности"


def skew_lines(versions: dict) -> list[str]:
    lines = []
    for direction, entry in versions.items():
        source = entry.get("source", {})
        shown = source.get("version") or source.get("package") or source.get("stage") or "?"
        for row in entry.get("deployed", []):
            if row.get("relation") not in ("behind", "ahead", "different"):
                continue
            what = (row.get("version") or "?") + (f" · сборка {row['build']}" if row.get("build") else "")
            lines.append(f"{direction}: {row['where']} — {what}, в исходниках {shown}: "
                         f"{RELATION_RU.get(row['relation'], row['relation'])}" + (f" ({row['detail']})" if row.get("detail") else ""))
    return lines


def deployed_version(versions: dict, direction: str) -> str | None:
    for row in versions.get(direction, {}).get("deployed", []):
        if row.get("version") and row.get("relation") in ("match", "behind", "ahead", "different"):
            return str(row["version"]).split(" ")[0]
    return None


def contracts_view(root: Path, versions: dict) -> list[dict]:
    """contracts/compatibility.json против того, что реально стоит на хосте и телефоне."""
    try:
        data = json.loads((root / "contracts/compatibility.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    for contract in data.get("contracts", []):
        cells = {}
        for direction, impl in (contract.get("implementations") or {}).items():
            if not impl:
                cells[direction] = {"state": "absent", "text": "не реализован"}
                continue
            since = str(impl.get("since") or "")
            deployed = deployed_version(versions, direction)
            accepted = "принят на хосте" if impl.get("hostAccepted") else "не принят на хосте"
            if not deployed or not since:
                state, text = "unknown", f"с {since or '?'}; что стоит — неизвестно; {accepted}"
            elif compare_versions(deployed, since) == "behind":
                state, text = "missing", f"с {since}; стоит {deployed} — контракта там нет; {accepted}"
            else:
                state, text = "present", f"с {since}; стоит {deployed} — есть; {accepted}"
            cells[direction] = {"state": state, "text": text, "since": since, "deployed": deployed}
        rows.append({"id": contract.get("id"), "status": contract.get("status"), "directions": cells})
    return rows


# ---------------------------------------------------------------- отчёт


def run_identifier(started: datetime, tree: dict) -> str:
    revision = tree.get("boardRevision")
    sha = (tree.get("sha") or "nosha")[:7]
    return f"uts_{started.strftime('%Y%m%dT%H%M%SZ')}_r{revision if revision is not None else 'x'}_{sha}"


def write_report(runner: Runner, started: datetime, finished: datetime, run_id: str, archive_name: str, host: dict) -> dict:
    only = set(runner.options.only) if runner.options.only else None
    rows = direction_scores(runner.plan, runner.results, only)
    measured = [row for row in rows if row["readiness"] is not None]
    overall = round(sum(row["readiness"] for row in measured) / len(measured)) if measured else 0
    contracts = contracts_view(runner.root, runner.versions)
    report = {
        "schema": REPORT_SCHEMA,
        "runId": run_id,
        "startedAt": iso(started),
        "finishedAt": iso(finished),
        "archive": archive_name,
        "options": {
            "only": runner.options.only, "skip": sorted(runner.options.skip), "allowNetwork": runner.options.allow_network,
            "noRuntime": runner.options.no_runtime, "interactive": runner.options.interactive, "webUrl": runner.options.web_url,
        },
        "interrupted": runner.interrupted,
        "tree": runner.tree,
        "host": host,
        "overall": {
            "readiness": overall, "label": readiness_label(overall),
            "allPassed": bool(measured) and all(row["verdict"] == "PASS" for row in measured),
            "partial": bool(only) or bool(runner.options.skip) or runner.interrupted,
        },
        "directions": rows,
        "versions": runner.versions,
        "contracts": contracts,
        "skew": skew_lines(runner.versions) + [
            f"контракт {row['id']}: {direction} — {cell['text']}"
            for row in contracts for direction, cell in row["directions"].items() if cell["state"] == "missing"
        ],
        "manualEvidence": {"abl": runner.cache.get("ablManual", [])},
        "results": [r.as_json() for r in runner.results],
    }
    (runner.run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (runner.run_dir / "SUMMARY.md").write_text(render_summary(report, runner), encoding="utf-8")
    return report


def render_summary(report: dict, runner: Runner) -> str:
    tree = report["tree"]
    overall = report["overall"]
    verdicts = " · ".join(f"{row['title']} {row['verdict'] or '—'}" for row in report["directions"])
    out = [f"# UTS экосистемы {report['runId']}", ""]
    out.append(f"**Готовность {overall['readiness']}%** ({overall['label']}) · {verdicts}")
    if overall["partial"]:
        reasons = []
        if report["options"]["only"]:
            reasons.append("только " + ", ".join(report["options"]["only"]))
        if report["options"]["skip"]:
            reasons.append("пропущены уровни " + ", ".join(LEVEL_RU[l] for l in report["options"]["skip"]))
        if report["interrupted"]:
            reasons.append("прерван")
        out.append(f"\nНеполный прогон ({'; '.join(reasons)}): это не приёмка, а диагностика.")
    if report["skew"]:
        out += ["", "## ⚠ Смешанные версии", "",
                "На хосте или телефоне стоит не то, что в проверяемом дереве. Результаты о связке направлений относятся к этой смеси.", ""]
        out += [f"- {line}" for line in report["skew"]]
    out += ["", "## Что проверялось", ""]
    if tree.get("kind") == "git":
        state = "чистое" if not tree.get("dirtyFiles") else f"изменено файлов: {tree['dirtyFiles']}"
        out.append(f"- дерево: git `{tree['sha'][:7]}` «{tree.get('subject', '')}» ({state})")
    elif tree.get("kind") == "uts-copy":
        out.append(f"- дерево: копия UserTestSpace после `{tree['afterPatch']}` (`{tree['sha']}`), снята {tree['copiedAt']}")
    else:
        out.append("- дерево: копия без git, происхождение по имени каталога не определено")
    out.append(f"- путь: `{tree['root']}`")
    out.append(f"- доска: ревизия {tree.get('boardRevision')}, последний патч `{tree.get('lastPatchId')}`")
    host = report["host"]
    tools = ", ".join(f"{k} {v}" for k, v in host["tools"].items() if v)
    missing = ", ".join(k for k, v in host["tools"].items() if not v)
    out.append(f"- хост: {host.get('os') or host['system']}; python {host['python']}")
    out.append(f"- инструменты: {tools}" + (f"; нет: {missing}" if missing else ""))
    out.append(f"- время: {report['startedAt']} → {report['finishedAt']}")
    out += ["", "## Направления", "",
            "| Направление | Вердикт | Готовность | Покрытие | " + " | ".join(LEVEL_RU[l].capitalize() for l in LEVELS) + " |",
            "|---|---|---|---|" + "---|" * len(LEVELS)]
    for row in report["directions"]:
        if row["verdict"] is None:
            out.append(f"| {row['title']} | не запускалось | — | — | " + " | ".join("—" for _ in LEVELS) + " |")
            continue
        cells = [f"{row['levels'][l]['passed']}/{row['levels'][l]['total']}" if l in row["levels"] else "—" for l in LEVELS]
        out.append(f"| {row['title']} | **{row['verdict']}** | {row['readiness']}% | {row['coverage']}% | " + " | ".join(cells) + " |")
    out += ["", "Вердикт PASS — все гейт-проверки направления прошли (PASS или WARN). Готовность — доля "
            "доказанного с весами уровней; покрытие — доля проверок, которые вообще удалось выполнить.", ""]
    if report["versions"]:
        out += ["## Версии", "", "| Направление | В исходниках | Где стоит | Что стоит | Состояние |", "|---|---|---|---|---|"]
        for direction, entry in report["versions"].items():
            source = entry.get("source", {})
            shown = ", ".join(f"{k} {v if not isinstance(v, list) else '/'.join(v)}" for k, v in source.items() if v) or "?"
            rows = entry.get("deployed") or [{"where": "—", "version": None, "relation": None}]
            for deployed in rows:
                what = deployed.get("version") or "—"
                if deployed.get("build"):
                    what += f" · сборка {deployed['build']}"
                state = RELATION_RU.get(deployed.get("relation"), "—")
                if deployed.get("detail"):
                    state += f" — {deployed['detail']}"
                out.append(f"| {direction} | {shown} | {deployed['where']} | {what} | {state} |")
        out.append("")
    if report["contracts"]:
        directions = sorted({d for row in report["contracts"] for d in row["directions"]},
                            key=lambda d: ["web", "mobile", "abl"].index(d) if d in ("web", "mobile", "abl") else 9)
        out += ["## Контракты на хосте", "", "По `contracts/compatibility.json`: с какой версии направление реализует "
                "контракт и есть ли эта версия там, где оно развёрнуто.", "",
                "| Контракт | Статус | " + " | ".join(directions) + " |", "|---|---|" + "---|" * len(directions)]
        for row in report["contracts"]:
            out.append(f"| {row['id']} | {row['status']} | " +
                       " | ".join(row["directions"].get(d, {}).get("text", "—") for d in directions) + " |")
        out.append("")
    problems = [r for r in runner.results if r.status in ("FAIL", "BLOCKED") and (r.gate or r.level != "manual")]
    gate_problems = [r for r in problems if r.gate]
    other_problems = [r for r in problems if not r.gate and not r.id.startswith("uts.")]
    gate_skipped = [r for r in runner.results if r.gate and r.status == "SKIP"]
    if gate_problems or gate_skipped:
        out += ["## Почему FAIL", ""]
    if gate_skipped:
        out.append("Гейт-проверки, которые не запускались, тоже не дают PASS: " +
                   ", ".join(f"`{r.key}`" for r in gate_skipped) + ".")
        out.append("")
    if gate_problems:
        for result in gate_problems:
            out.append(f"### {result.key} — {result.status}")
            out.append(f"{result.title}: {result.reason}" if result.reason else result.title)
            if result.log:
                out.append(f"\nЛог: `{result.log}`")
            if result.details.get("failures"):
                out += ["", "Первые провалы внутри:", ""] + [f"- {line}" for line in result.details["failures"]]
            elif result.log:
                lines = tail(runner.run_dir / result.log)
                if lines:
                    out += ["", "```text", *lines, "```"]
            out.append("")
    if other_problems:
        out += ["## Не гейт, но не доказано", ""]
        for result in other_problems:
            out.append(f"- `{result.key}` {result.status}: {result.title}" + (f": {result.reason}" if result.reason else "") + (f" (`{result.log}`)" if result.log else ""))
        out.append("")
    cards = [r for r in runner.results if r.level == "manual"]
    if cards:
        out += [f"## Карточки «{runner.plan.get('boardColumn')}»", "",
                "Ручная приёмка с доски. Отвечать — с флагом `--interactive`; ответы попадают в report.json.", ""]
        seen = set()
        for result in cards:
            card_id = result.details.get("cardId")
            if card_id in seen:
                continue
            seen.add(card_id)
            out.append(f"- [{result.status}] {result.title} — {result.reason}")
        out.append("")
    if report["manualEvidence"].get("abl"):
        out += ["## Что abl просит подтвердить глазами", ""] + [f"- {item}" for item in report["manualEvidence"]["abl"]] + [""]
    out += ["## Все проверки", ""]
    for row in report["directions"]:
        own = [r for r in runner.results if r.direction == row["id"] and not r.id.startswith("uts.")]
        if not own:
            continue
        out.append(f"**{row['title']}**")
        out.append("")
        for result in own:
            mark = "" if result.gate else " (не гейт)"
            line = f"- [{result.status}] `{result.id}` {result.title}{mark}, {LEVEL_RU[result.level]}"
            if result.seconds >= 0.05:
                line += f", {result.seconds:.1f} с"
            if result.reason and result.status != "PASS":
                line += f" — {result.reason}"
            elif result.reason and result.level in ("host", "device"):
                line += f" — {result.reason}"
            if result.log:
                line += f" · `{result.log}`"
            out.append(line)
        imported = [r for r in runner.results if r.direction == row["id"] and r.id.startswith("uts.")]
        if imported:
            counts = {s: sum(1 for r in imported if r.status == s) for s in STATUSES}
            out.append("- собственный UTS: " + ", ".join(f"{s} {n}" for s, n in counts.items() if n) +
                       " — подробно в report.json и в каталоге отчёта abl")
        out.append("")
    out += ["## Файлы", "", "- `SUMMARY.md` — эта сводка", "- `report.json` — всё то же для машины (схема " + report["schema"] + ")",
            "- `logs/<направление>/NN-<проверка>.log` — полный вывод каждой проверки; шапка лога — команда, каталог, итог",
            f"- архив `{report['archive']}` рядом с папкой — точная копия этой папки", ""]
    return "\n".join(out)


def build_archive(run_dir: Path, archive: Path) -> int:
    files = sorted(p for p in run_dir.rglob("*") if p.is_file())
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            bundle.write(path, f"{run_dir.name}/{path.relative_to(run_dir).as_posix()}")
    with zipfile.ZipFile(archive) as bundle:
        names = {n for n in bundle.namelist() if not n.endswith("/")}
        expected = {f"{run_dir.name}/{p.relative_to(run_dir).as_posix()}" for p in files}
        if names != expected:
            raise RuntimeError("архив не совпадает с папкой по составу")
        for path in files:
            data = bundle.read(f"{run_dir.name}/{path.relative_to(run_dir).as_posix()}")
            if hashlib.sha256(data).hexdigest() != sha256_file(path):
                raise RuntimeError(f"архив не совпадает с папкой: {path.name}")
    return len(files)


def run(root: Path, plan_path: Path, options: argparse.Namespace, *, quiet: bool = False) -> tuple[int, dict, Path]:
    plan = load_plan(plan_path)
    known = {d["id"] for d in plan["directions"]}
    if options.only:
        unknown = set(options.only) - known
        if unknown:
            raise PlanError(f"нет таких направлений: {', '.join(sorted(unknown))}; есть: {', '.join(sorted(known))}")
    started = now_utc()
    base = Path(options.out).resolve() if options.out else root / OUT_DIR
    probe_tree = tree_identity(root)
    run_id = run_identifier(started, probe_tree)
    while (base / run_id).exists():
        run_id += "+"
    run_dir = base / run_id
    run_dir.mkdir(parents=True)
    archive = base / f"{run_id}.zip"
    runner = Runner(root, plan, options, run_dir, quiet=quiet)
    if not quiet:
        print(f"UTS экосистемы → {run_dir}")
    host = {"system": platform.platform(), "python": platform.python_version(), "tools": {}} if quiet else host_facts()
    (run_dir / "host.json").write_text(json.dumps(host, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runner.execute()
    report = write_report(runner, started, now_utc(), run_id, archive.name, host)
    count = build_archive(run_dir, archive)
    (base / "latest.txt").write_text(f"{run_id}\n", encoding="utf-8")
    if not quiet:
        print_console_summary(report, run_dir, archive, count)
    return (0 if report["overall"]["allPassed"] else 1), report, run_dir


def print_console_summary(report: dict, run_dir: Path, archive: Path, count: int) -> None:
    overall = report["overall"]
    print()
    print(f"Готовность: {overall['readiness']}% — {overall['label']}" + (" (неполный прогон)" if overall["partial"] else ""))
    for row in report["directions"]:
        if row["verdict"] is None:
            print(f"  {row['title']:<10} —     не запускалось")
        else:
            print(f"  {row['title']:<10} {row['verdict']:<5} готовность {row['readiness']:>3}%, покрытие {row['coverage']:>3}%")
    if report["skew"]:
        print("Смешанные версии:")
        for line in report["skew"]:
            print(f"  ! {line}")
    print(f"Сводка: {run_dir / 'SUMMARY.md'}")
    print(f"Архив:  {archive} ({count} файлов, совпадает с папкой)")


# ---------------------------------------------------------------- самопроверка


def self_test() -> int:
    """Прогон на синтетическом дереве: статусы, вердикты, баллы, папка и архив."""
    errors = []
    try:
        real = load_plan(PLAN)
        for check in plan_checks(real):
            for part in check.run or []:
                if re.search(r"\.(py|mjs|json)$", part) and "{" not in part and not part.startswith("-"):
                    if not (ROOT / check.cwd / part).is_file():
                        errors.append(f"план: {check.key} ссылается на отсутствующий {check.cwd}/{part}")
    except PlanError as error:
        errors.append(str(error))
    with tempfile.TemporaryDirectory(prefix="uts-self-test-") as temp:
        root = Path(temp) / "tree"
        (root / "alpha").mkdir(parents=True)
        (root / "board").mkdir()
        python = [sys.executable, "-c"]
        plan = {"schemaVersion": 1, "boardColumn": "Ждёт хоста", "directions": [
            {"id": "alpha", "dir": "alpha", "checks": [
                {"id": "ok", "level": "static", "run": python + ["print('привет')"]},
                {"id": "slow-build", "level": "build", "run": python + ["import sys; sys.exit(3)"]},
                {"id": "after", "level": "host", "needs": ["slow-build"], "run": python + ["pass"]},
                {"id": "optional", "level": "static", "gate": False, "run": python + ["import sys; sys.exit(1)"]},
            ]},
            {"id": "beta", "dir": ".", "checks": [
                {"id": "ok", "level": "static", "run": python + ["pass"]},
                {"id": "tool", "level": "host", "gate": False, "requires": ["no-such-tool-uts"], "run": ["no-such-tool-uts"]},
                {"id": "timeout", "level": "build", "gate": False, "timeout": 1, "run": python + ["import time; time.sleep(30)"]},
            ]},
        ]}
        board = {"payload": {"columns": [{"id": "c1", "name": "Ждёт хоста"}], "labels": [{"id": "l1", "name": "beta"}],
                             "cards": [{"id": "card-0000-aaaaaaaa", "columnId": "c1", "title": "Карточка", "position": 1}],
                             "cardLabels": [{"cardId": "card-0000-aaaaaaaa", "labelId": "l1"}],
                             "checklists": [], "checklistItems": []},
                 "origin": {"boardRevision": 7, "lastPatchId": "self-test"}}
        (root / "board/board.json").write_text(json.dumps(board), encoding="utf-8")
        plan_path = Path(temp) / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        options = argparse.Namespace(only=None, skip=set(), allow_network=False, no_runtime=False, interactive=False,
                                     web_url=None, out=None)
        code, report, run_dir = run(root, plan_path, options, quiet=True)
        status = {r["id"]: r["status"] for r in report["results"]}
        expect = {"alpha.ok": "PASS", "alpha.slow-build": "FAIL", "alpha.after": "BLOCKED", "alpha.optional": "FAIL",
                  "beta.ok": "PASS", "beta.tool": "BLOCKED", "beta.timeout": "FAIL", "beta.card-da5f6cee": "SKIP"}
        if status != expect:
            errors.append(f"статусы {status} ≠ {expect}")
        verdicts = {row["id"]: row["verdict"] for row in report["directions"]}
        if verdicts != {"alpha": "FAIL", "beta": "PASS"} or code != 1:
            errors.append(f"вердикты {verdicts}, код {code}")
        alpha = next(row for row in report["directions"] if row["id"] == "alpha")
        # ok 1·1 из (1 + 2 + 3 + 0.5) = 6.5 → 15 %
        if alpha["readiness"] != 15:
            errors.append(f"готовность alpha {alpha['readiness']} ≠ 15")
        archive = run_dir.parent / f"{run_dir.name}.zip"
        for name in ("SUMMARY.md", "report.json", "host.json"):
            if not (run_dir / name).is_file():
                errors.append(f"нет {name}")
        if not archive.is_file() or build_archive(run_dir, Path(temp) / "again.zip") < 4:
            errors.append("архив не создан или пуст")
        if (run_dir.parent / "latest.txt").read_text(encoding="utf-8").strip() != run_dir.name:
            errors.append("latest.txt не указывает на прогон")
        if not run_dir.name.startswith("uts_") or "_r7_" not in run_dir.name:
            errors.append(f"имя прогона {run_dir.name}")
        log = (run_dir / "logs/alpha/01-ok.log").read_text(encoding="utf-8")
        if "привет" not in log or "# итог: PASS" not in log:
            errors.append("лог проверки неполон")
        options.only = ["beta"]
        options.skip = {"build"}
        _, partial, _ = run(root, plan_path, options, quiet=True)
        if not partial["overall"]["partial"] or partial["directions"][0]["verdict"] is not None:
            errors.append("частичный прогон не помечен")
        if version_tuple("2.0.9") >= version_tuple("2.1.0") or compare_versions("23", "24") != "behind":
            errors.append("сравнение версий")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("OK: тестер UTS: план корректен, статусы, вердикты, баллы, папка и архив совпадают")
    return 0


# ---------------------------------------------------------------- вход


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="направления через запятую (ecosystem,web,mobile,abl,devctl)")
    parser.add_argument("--skip", default="", help="уровни через запятую: static,build,host,device,manual")
    parser.add_argument("--allow-network", action="store_true", help="разрешить npm и UTS abl докачать зависимости")
    parser.add_argument("--no-runtime", action="store_true", help="UTS abl без запуска окна (нет графической сессии)")
    parser.add_argument("--interactive", action="store_true", help="спросить о карточках «Ждёт хоста»")
    parser.add_argument("--web-url", help="адрес web-узла, если он не в Docker этого хоста")
    parser.add_argument("--out", help=f"куда класть прогоны (по умолчанию {OUT_DIR}/ в корне дерева)")
    parser.add_argument("--list", action="store_true", help="показать план и выйти")
    parser.add_argument("--self-test", action="store_true", help="проверить сам тестер на синтетическом дереве")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    args.only = [item.strip() for item in args.only.split(",") if item.strip()] if args.only else None
    args.skip = {item.strip() for item in args.skip.split(",") if item.strip()}
    if args.skip - set(LEVELS):
        parser.error(f"неизвестные уровни: {', '.join(sorted(args.skip - set(LEVELS)))}")
    try:
        if args.list:
            plan = load_plan(PLAN)
            directions = {d["id"] for d in plan["directions"]}
            checks = plan_checks(plan) + board_cards(ROOT, plan.get("boardColumn", ""), directions)
            for check in checks:
                print(f"{check.key:<40} {LEVEL_RU[check.level]:<11} {'гейт' if check.gate else '    '}  {check.title}")
            return 0
        code, _, _ = run(ROOT, PLAN, args)
        return code
    except PlanError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
