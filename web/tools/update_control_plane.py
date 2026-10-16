#!/usr/bin/env python3
"""Loopback-only UI bridge for safe p2pKanban source updates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


CONTROL_VERSION = "1.3.0"
DEFAULT_PORT = 8765
DEFAULT_REPOSITORY = "https://github.com/Pacifica123/p2pKanban-ecosystem"
# Before the monorepo the node was published from its own repository. Nodes
# that still remember it follow the monorepo instead.
LEGACY_REPOSITORIES = frozenset({"https://github.com/pacifica123/p2p_planner"})
# In the monorepo web lives in web/. Only commits that change this directory
# are offered as node updates; mobile, abl, devctl and board commits are not.
SOURCE_PATH = "web"
DEFAULT_BRANCH = "main"
CONTROL_STATE = Path(".dev-bootstrap/update-control.json")
STACK_STATE = Path(".dev-bootstrap/container-stack.json")
JOB_STATE = Path(".dev-bootstrap/update-job.json")
LATEST_CACHE = Path(".dev-bootstrap/latest-source-commit.json")
JOB_LOG = Path(".dev-bootstrap/update-job.log")
MAX_BODY_BYTES = 16 * 1024
MAX_FAILURE_REASON_CHARS = 1500


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_object(path: Path, value: dict[str, Any], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if private and os.name != "nt":
        os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def normalize_repository(value: object) -> str:
    candidate = str(value or "").strip().removesuffix(".git")
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        return DEFAULT_REPOSITORY
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return DEFAULT_REPOSITORY
    repository = f"https://github.com/{parts[0]}/{parts[1]}"
    if repository.lower() in LEGACY_REPOSITORIES:
        return DEFAULT_REPOSITORY
    return repository


def github_api_commit_url(repository: str, branch: str) -> str:
    owner_repo = normalize_repository(repository).removeprefix("https://github.com/")
    return (
        f"https://api.github.com/repos/{owner_repo}/commits/"
        f"{urllib.parse.quote(branch, safe='')}"
    )


def github_api_path_commits_url(repository: str, branch: str, path: str) -> str:
    owner_repo = normalize_repository(repository).removeprefix("https://github.com/")
    query = urllib.parse.urlencode({"sha": branch, "path": path, "per_page": 1})
    return f"https://api.github.com/repos/{owner_repo}/commits?{query}"


def github_api_compare_url(repository: str, base: str, head: str) -> str:
    owner_repo = normalize_repository(repository).removeprefix("https://github.com/")
    return f"https://api.github.com/repos/{owner_repo}/compare/{base}...{head}"


def github_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"p2pKanban-update-control/{CONTROL_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GitHub не ответил: {exc}") from exc


def is_revision(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{7,40}", value) is not None


def revisions_match(left: object, right: object) -> bool:
    if not is_revision(left) or not is_revision(right):
        return False
    return str(left).startswith(str(right)) or str(right).startswith(str(left))


def fetch_latest_commit(repository: str, branch: str) -> dict[str, Any]:
    """Latest commit of the branch that changed web/.

    A repository without web/ (the pre-monorepo layout) has no such commits;
    then the branch head itself is the update.
    """
    scoped = github_json(github_api_path_commits_url(repository, branch, SOURCE_PATH))
    if isinstance(scoped, list) and scoped:
        latest = commit_from_payload(scoped[0], repository)
        latest["sourcePath"] = SOURCE_PATH
        return latest
    latest = commit_from_payload(github_json(github_api_commit_url(repository, branch)), repository)
    latest["sourcePath"] = None
    return latest


def installed_contains(repository: str, latest_sha: str, installed: str | None) -> bool:
    """True when the running revision already has the web/ of latest_sha.

    The running node may be built from a later commit that only touched other
    directions. GitHub compare answers "ahead"/"identical" for it. An unknown
    revision (an old repository, a source fingerprint) is not evidence.
    """
    if not is_revision(installed):
        return False
    if revisions_match(latest_sha, installed):
        return True
    try:
        payload = github_json(github_api_compare_url(repository, latest_sha, str(installed)))
    except RuntimeError:
        return False
    return isinstance(payload, dict) and payload.get("status") in {"ahead", "identical"}


def commit_from_payload(payload: object, repository: str) -> dict[str, Any]:
    commit = payload.get("commit") if isinstance(payload, dict) else None
    if not isinstance(commit, dict):
        raise RuntimeError("GitHub вернул неожиданный ответ для main.")
    sha = str(payload.get("sha") or "")
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        raise RuntimeError("GitHub не вернул корректный commit SHA.")
    assert isinstance(payload, dict)
    committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    return {
        "sha": sha,
        "shortSha": sha[:12],
        "message": str(commit.get("message") or "Новый commit в main"),
        "committedAt": committer.get("date"),
        "url": str(payload.get("html_url") or f"{repository}/commit/{sha}"),
        "repository": normalize_repository(repository),
        "checkedAt": iso_now(),
    }


def git_output(project_root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def installed_revision(project_root: Path) -> str | None:
    stack = read_object(project_root / STACK_STATE)
    revision = stack.get("activeRevision")
    if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision):
        return revision
    build_info = read_object(project_root / "BUILD_INFO.json")
    commit = build_info.get("gitCommit")
    if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit):
        return commit
    image_tag = stack.get("imageTag")
    if isinstance(image_tag, str):
        match = re.search(r"(?:^|[-_.])([0-9a-f]{12,40})$", image_tag)
        if match:
            return match.group(1)
    # The checkout may already contain a devctl commit while the running image
    # still contains the previous source. Git HEAD is therefore not evidence of
    # the installed web revision.
    return None


def failure_reason(log_path: Path) -> str | None:
    """The updater's own explanation from its log: the text after its last
    "Запуск остановлен:" line, otherwise the last lines of the log."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    marker = "Запуск остановлен:"
    starts = [index for index, line in enumerate(lines) if line.lstrip().startswith(marker)]
    if starts:
        tail = lines[starts[-1]:]
        tail[0] = tail[0].lstrip().removeprefix(marker).strip()
    else:
        tail = lines[-6:]
    reason = "\n".join(line.rstrip() for line in tail if line.strip()).strip()
    if len(reason) > MAX_FAILURE_REASON_CHARS:
        reason = reason[: MAX_FAILURE_REASON_CHARS - 1] + "…"
    return reason or None


def empty_job() -> dict[str, Any]:
    return {
        "id": "none",
        "status": "idle",
        "phase": "ожидание",
        "progress": 0,
        "message": "Обновление не запущено.",
        "targetSha": None,
        "startedAt": None,
        "finishedAt": None,
        "error": None,
        "verified": False,
    }


class ControlApplication:
    def __init__(self, project_root: Path, port: int) -> None:
        self.project_root = project_root.resolve()
        self.port = port
        self.lock = threading.RLock()
        self.server: ThreadingHTTPServer | None = None
        self.loaded_script_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        existing = read_object(self.project_root / CONTROL_STATE)
        token = existing.get("sessionToken")
        self.session_token = token if isinstance(token, str) and len(token) >= 32 else secrets.token_urlsafe(32)
        self.repository = normalize_repository(
            read_object(self.project_root / STACK_STATE).get("updateRepository")
            or DEFAULT_REPOSITORY
        )
        self.branch = str(
            read_object(self.project_root / STACK_STATE).get("updateBranch")
            or DEFAULT_BRANCH
        )
        self._write_control_state()
        job = read_object(self.project_root / JOB_STATE)
        if job.get("status") in {"queued", "running"}:
            job.update({
                "status": "failed",
                "phase": "остановлено",
                "finishedAt": iso_now(),
                "error": "Управляющий процесс был перезапущен во время обновления. Проверьте состояние stack.",
                "message": "Требуется проверка состояния.",
                "verified": False,
            })
            write_object(self.project_root / JOB_STATE, job)

    def script_sha256(self) -> str:
        return self.loaded_script_sha256

    def _write_control_state(self) -> None:
        write_object(
            self.project_root / CONTROL_STATE,
            {
                "schemaVersion": 1,
                "controlVersion": CONTROL_VERSION,
                "pid": os.getpid(),
                "port": self.port,
                "projectRoot": str(self.project_root),
                "sessionToken": self.session_token,
                "scriptSha256": self.script_sha256(),
                "startedAt": iso_now(),
            },
            private=True,
        )

    def allowed_origins(self) -> set[str]:
        stack = read_object(self.project_root / STACK_STATE)
        port = stack.get("webPort") if isinstance(stack.get("webPort"), int) else 8080
        return {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }

    def latest(self, *, refresh: bool = False) -> dict[str, Any] | None:
        cache_path = self.project_root / LATEST_CACHE
        cached = read_object(cache_path)
        # A cache written for another repository (the pre-monorepo one) says
        # nothing about this channel.
        if cached and not str(cached.get("url") or "").startswith(self.repository + "/"):
            cached = {}
        if cached and not refresh:
            return cached
        try:
            latest = fetch_latest_commit(self.repository, self.branch)
        except RuntimeError:
            if cached:
                return cached
            raise
        installed = installed_revision(self.project_root)
        latest["evaluatedFor"] = installed
        latest["webUpdateAvailable"] = not installed_contains(
            self.repository, latest["sha"], installed
        )
        write_object(cache_path, latest)
        return latest

    def update_available(self, latest: dict[str, Any] | None, installed: str | None) -> bool:
        if not latest or revisions_match(latest.get("sha"), installed):
            return False
        verdict = latest.get("webUpdateAvailable")
        if latest.get("evaluatedFor") == installed and isinstance(verdict, bool):
            return verdict
        return True

    def job(self) -> dict[str, Any]:
        return {**empty_job(), **read_object(self.project_root / JOB_STATE)}

    def state(self, *, refresh_latest: bool = False) -> dict[str, Any]:
        latest = self.latest(refresh=refresh_latest)
        installed = installed_revision(self.project_root)
        return {
            "available": True,
            "sessionToken": self.session_token,
            "repository": self.repository,
            "branch": self.branch,
            "sourcePath": latest.get("sourcePath") if latest else SOURCE_PATH,
            "installedRevision": installed,
            "updateAvailable": self.update_available(latest, installed),
            "latest": latest,
            "job": self.job(),
        }

    def _set_job(self, job: dict[str, Any], **changes: Any) -> dict[str, Any]:
        with self.lock:
            job.update(changes)
            write_object(self.project_root / JOB_STATE, job)
            return dict(job)

    def start_update(self, target_sha: str) -> None:
        with self.lock:
            current = self.job()
            if current.get("status") in {"queued", "running"}:
                raise RuntimeError("Обновление уже выполняется.")
            latest = self.latest(refresh=True)
            if not latest or latest.get("sha") != target_sha:
                raise RuntimeError("web в main уже изменился. Сначала получите новое предложение обновления.")
            job = {
                **empty_job(),
                "id": f"update-{int(time.time())}",
                "status": "queued",
                "phase": "подготовка",
                "progress": 2,
                "message": "Готовим безопасное обновление.",
                "targetSha": target_sha,
                "startedAt": iso_now(),
            }
            write_object(self.project_root / JOB_STATE, job)
            threading.Thread(target=self._run_update, args=(job,), daemon=True).start()

    def _progress_for_line(self, line: str) -> tuple[str, int, str] | None:
        markers = (
            ("Получаю исходники", "получение исходников", 8),
            ("Проверяю полученный source", "проверка исходников", 14),
            ("Собираю p2pKanban", "сборка контейнеров", 28),
            ("Создаю backup PostgreSQL", "резервная копия", 70),
            ("Переключаю backend и web", "переключение контейнеров", 84),
            ("Проверяю сохранность данных", "проверка данных", 93),
            ("p2pKanban обновлён", "готово", 99),
        )
        for marker, phase, progress in markers:
            if marker in line:
                return phase, progress, line.strip()
        return None

    def _run_update(self, job: dict[str, Any]) -> None:
        self._set_job(
            job,
            status="running",
            phase="получение исходников",
            progress=5,
            message="Получаем зафиксированный commit из GitHub.",
        )
        command = [
            sys.executable,
            "-B",
            "-u",
            str(self.project_root / "bootstrap.py"),
            "update",
            "--repository",
            self.repository,
            "--branch",
            self.branch,
            "--target-commit",
            str(job["targetSha"]),
        ]
        log_path = self.project_root / JOB_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=self.project_root,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                )
                self._set_job(job, childPid=process.pid)
                assert process.stdout is not None
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    progress = self._progress_for_line(line)
                    if progress:
                        phase, value, message = progress
                        self._set_job(job, phase=phase, progress=value, message=message)
                return_code = process.wait()
        except OSError as exc:
            self._set_job(
                job,
                status="failed",
                phase="ошибка запуска",
                finishedAt=iso_now(),
                error=str(exc),
                message="Не удалось запустить updater.",
                verified=False,
            )
            return

        revision = installed_revision(self.project_root)
        stack = read_object(self.project_root / STACK_STATE)
        verified = return_code == 0 and revision == job["targetSha"] and stack.get("status") == "running"
        if verified:
            self._set_job(
                job,
                status="succeeded",
                phase="готово",
                progress=100,
                finishedAt=iso_now(),
                error=None,
                message="Commit установлен, данные проверены, контейнеры готовы.",
                verified=True,
            )
            return
        reason = failure_reason(log_path) if return_code != 0 else None
        self._set_job(
            job,
            status="failed",
            phase="остановлено",
            finishedAt=iso_now(),
            error=(
                (f"{reason}\n" if reason else "")
                + f"Updater завершился с кодом {return_code}. "
                + f"Активный commit: {revision or 'не определён'}. "
                + f"Журнал: {JOB_LOG.as_posix()}"
            ),
            message="Рабочая версия сохранена либо автоматически возвращена.",
            verified=False,
        )

    def shutdown(self) -> None:
        if self.server:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


class ControlHandler(BaseHTTPRequestHandler):
    server_version = "p2pKanbanUpdateControl/1"

    @property
    def app(self) -> ControlApplication:
        return getattr(self.server, "application")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin in self.app.allowed_origins()

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin in self.app.allowed_origins():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-P2PKanban-Control")
            self.send_header("Access-Control-Max-Age", "600")

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("Некорректный Content-Length.") from None
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("Тело запроса слишком большое.")
        if not length:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Ожидался JSON-объект.") from None
        if not isinstance(value, dict):
            raise ValueError("Ожидался JSON-объект.")
        return value

    def _authorized(self) -> bool:
        return (
            self._origin_allowed()
            and secrets.compare_digest(
                self.headers.get("X-P2PKanban-Control", ""),
                self.app.session_token,
            )
        )

    def do_OPTIONS(self) -> None:
        if not self._origin_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Origin не разрешён."})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            self._json(HTTPStatus.OK, {
                "status": "ok",
                "controlVersion": CONTROL_VERSION,
                "projectRoot": str(self.app.project_root),
                "scriptSha256": self.app.script_sha256(),
            })
            return
        if path != "/v1/status":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Маршрут не найден."})
            return
        if not self._origin_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Доступ только из локального web-клиента."})
            return
        try:
            self._json(HTTPStatus.OK, self.app.state())
        except RuntimeError as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/internal/shutdown":
            if not secrets.compare_digest(
                self.headers.get("X-P2PKanban-Control", ""),
                self.app.session_token,
            ):
                self._json(HTTPStatus.FORBIDDEN, {"error": "Неверный token."})
                return
            self._json(HTTPStatus.OK, {"status": "stopping"})
            self.app.shutdown()
            return
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Локальная сессия обновления не подтверждена."})
            return
        try:
            if path == "/v1/check":
                self._json(HTTPStatus.OK, self.app.state(refresh_latest=True))
                return
            if path == "/v1/update":
                payload = self._read_json()
                target_sha = str(payload.get("targetSha") or "")
                self.app.start_update(target_sha)
                self._json(HTTPStatus.ACCEPTED, self.app.state())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Маршрут не найден."})
        except (RuntimeError, ValueError) as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})


def serve(project_root: Path, port: int) -> int:
    if not 1 <= port <= 65535:
        raise SystemExit("control port должен быть от 1 до 65535")
    application = ControlApplication(project_root, port)
    server = ThreadingHTTPServer(("127.0.0.1", port), ControlHandler)
    setattr(server, "application", application)
    application.server = server
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--project-root", required=True)
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return serve(Path(args.project_root), args.port)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
