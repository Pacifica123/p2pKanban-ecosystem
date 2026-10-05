from __future__ import annotations

import json
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


def _now() -> str:
    return "2026-05-28T00:00:00Z"


def _page_info() -> dict[str, Any]:
    return {"nextCursor": None, "prevCursor": None, "hasNextPage": False, "hasPrevPage": False}


@dataclass
class MockState:
    user_id: str = "uiux-user-1"
    email: str = "uiux-user@local.test"
    display_name: str = "UIX Evidence User"
    workspaces: list[dict[str, Any]] = field(default_factory=list)
    boards: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    columns: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    cards: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    request_log: list[dict[str, Any]] = field(default_factory=list)
    next_id: int = 1

    def new_id(self, prefix: str) -> str:
        value = f"{prefix}-{self.next_id}"
        self.next_id += 1
        return value


class MockApiHandler(BaseHTTPRequestHandler):
    server: "MockApiServer"  # type: ignore[assignment]

    def log_message(self, fmt: str, *args: Any) -> None:  # keep runner output compact
        return

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send(204, None)

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle("DELETE")

    def _body(self) -> dict[str, Any]:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _send(self, status: int, payload: Any) -> None:
        origin = self.headers.get("Origin") or "*"
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "authorization,content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        if payload is not None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
        else:
            encoded = b""
            self.send_header("Content-Length", "0")
        self.end_headers()
        if encoded:
            self.wfile.write(encoded)

    def _data(self, value: Any) -> dict[str, Any]:
        return {"data": value}

    def _auth_success(self) -> dict[str, Any]:
        state = self.server.state
        return self._data(
            {
                "accessToken": "uiux-mock-access-token",
                "sessionId": "uiux-mock-session",
                "deviceId": "uiux-mock-device",
                "user": {"id": state.user_id, "email": state.email, "displayName": state.display_name},
            }
        )

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._body() if method in {"POST", "PATCH", "DELETE"} else {}
        state = self.server.state
        state.request_log.append({"method": method, "path": path, "query": parse_qs(parsed.query), "body": body})
        if not path.startswith("/api/v1"):
            self._send(404, {"error": {"code": "not_found", "message": "mock route not found"}})
            return
        route = path.removeprefix("/api/v1") or "/"

        if route == "/auth/refresh" and method == "POST":
            self._send(401, {"error": {"code": "unauthorized", "message": "Unauthorized"}})
            return
        if route in {"/auth/sign-in", "/auth/sign-up"} and method == "POST":
            state.email = str(body.get("email") or state.email)
            state.display_name = str(body.get("displayName") or state.display_name)
            self._send(200, self._auth_success())
            return
        if route == "/auth/sign-out" and method == "POST":
            self._send(200, self._data({"signedOut": True}))
            return
        if route == "/me/appearance" and method == "GET":
            self._send(
                200,
                self._data(
                    {
                        "userId": state.user_id,
                        "isCustomized": False,
                        "appTheme": "system",
                        "density": "comfortable",
                        "reduceMotion": False,
                        "checklistItemSubmitMode": "ctrl_enter",
                        "cardDetailsMode": "drawer",
                        "createdAt": _now(),
                        "updatedAt": _now(),
                    }
                ),
            )
            return
        if route == "/workspaces" and method == "GET":
            self._send(200, self._data({"items": state.workspaces, "pageInfo": _page_info()}))
            return
        if route == "/workspaces" and method == "POST":
            workspace = {
                "id": state.new_id("workspace"),
                "name": str(body.get("name") or "UIX Workspace"),
                "slug": None,
                "description": body.get("description"),
                "visibility": body.get("visibility") or "private",
                "ownerUserId": state.user_id,
                "memberCount": 1,
                "isArchived": False,
                "createdAt": _now(),
                "updatedAt": _now(),
                "archivedAt": None,
            }
            state.workspaces.append(workspace)
            state.boards.setdefault(workspace["id"], [])
            self._send(200, self._data(workspace))
            return
        match = re.fullmatch(r"/workspaces/([^/]+)/boards", route)
        if match and method == "GET":
            workspace_id = match.group(1)
            self._send(200, self._data({"items": state.boards.get(workspace_id, []), "pageInfo": _page_info()}))
            return
        if match and method == "POST":
            workspace_id = match.group(1)
            board = {
                "id": state.new_id("board"),
                "workspaceId": workspace_id,
                "name": str(body.get("name") or "UIX Board"),
                "description": body.get("description"),
                "boardType": body.get("boardType") or "kanban",
                "isArchived": False,
                "createdAt": _now(),
                "updatedAt": _now(),
                "archivedAt": None,
            }
            state.boards.setdefault(workspace_id, []).append(board)
            state.columns.setdefault(board["id"], [])
            state.cards.setdefault(board["id"], [])
            self._send(200, self._data(board))
            return
        match = re.fullmatch(r"/boards/([^/]+)", route)
        if match and method == "GET":
            board_id = match.group(1)
            board = next((item for boards in state.boards.values() for item in boards if item["id"] == board_id), None)
            self._send(200 if board else 404, self._data(board) if board else {"error": {"code": "not_found", "message": "board not found"}})
            return
        match = re.fullmatch(r"/boards/([^/]+)/appearance", route)
        if match and method == "GET":
            board_id = match.group(1)
            self._send(
                200,
                self._data(
                    {
                        "boardId": board_id,
                        "isCustomized": False,
                        "themePreset": "default",
                        "wallpaper": {"kind": "none", "value": None},
                        "columnDensity": "comfortable",
                        "cardPreviewMode": "expanded",
                        "showCardDescription": True,
                        "showCardDates": True,
                        "showChecklistProgress": True,
                        "customProperties": {},
                        "createdAt": _now(),
                        "updatedAt": _now(),
                    }
                ),
            )
            return
        match = re.fullmatch(r"/boards/([^/]+)/labels", route)
        if match and method == "GET":
            self._send(200, self._data({"items": []}))
            return
        if match and method == "POST":
            board_id = match.group(1)
            label = {
                "id": state.new_id("label"),
                "boardId": board_id,
                "name": str(body.get("name") or "UIX Label"),
                "color": str(body.get("color") or "blue"),
                "description": body.get("description"),
                "createdAt": _now(),
                "updatedAt": _now(),
            }
            self._send(200, self._data(label))
            return
        match = re.fullmatch(r"/boards/([^/]+)/columns", route)
        if match and method == "GET":
            board_id = match.group(1)
            self._send(200, self._data({"items": state.columns.get(board_id, []), "pageInfo": _page_info()}))
            return
        if match and method == "POST":
            board_id = match.group(1)
            column = {
                "id": state.new_id("column"),
                "boardId": board_id,
                "name": str(body.get("name") or "Todo"),
                "description": body.get("description"),
                "position": len(state.columns.get(board_id, [])) + 1,
                "colorToken": None,
                "wipLimit": None,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
            state.columns.setdefault(board_id, []).append(column)
            self._send(200, self._data(column))
            return
        match = re.fullmatch(r"/boards/([^/]+)/cards", route)
        if match and method == "GET":
            board_id = match.group(1)
            self._send(200, self._data({"items": state.cards.get(board_id, []), "pageInfo": _page_info()}))
            return
        if match and method == "POST":
            board_id = match.group(1)
            card = {
                "id": state.new_id("card"),
                "boardId": board_id,
                "columnId": body.get("columnId"),
                "title": str(body.get("title") or "UIX Card"),
                "description": body.get("description"),
                "status": body.get("status") or "todo",
                "priority": body.get("priority") or "medium",
                "position": len(state.cards.get(board_id, [])) + 1,
                "startAt": None,
                "dueAt": None,
                "isArchived": False,
                "createdAt": _now(),
                "updatedAt": _now(),
                "archivedAt": None,
            }
            state.cards.setdefault(board_id, []).append(card)
            self._send(200, self._data(card))
            return
        match = re.fullmatch(r"/boards/([^/]+)/activity", route)
        if match and method == "GET":
            self._send(200, self._data({"items": [], "pageInfo": _page_info()}))
            return
        if route == "/sync/replicas" and method == "POST":
            self._send(
                200,
                self._data(
                    {
                        "replica": {
                            "id": "replica-uiux-1",
                            "replicaKey": body.get("replicaKey"),
                            "kind": body.get("kind") or "browser_profile",
                            "status": "active",
                            "userId": state.user_id,
                            "deviceId": "uiux-mock-device",
                            "displayName": body.get("displayName"),
                            "platform": body.get("platform"),
                            "protocolVersion": body.get("protocolVersion"),
                            "appVersion": body.get("appVersion"),
                            "lastSeenAt": _now(),
                            "createdAt": _now(),
                            "updatedAt": _now(),
                        }
                    }
                ),
            )
            return
        if route == "/sync/status" and method == "GET":
            self._send(200, self._data({"healthy": True, "mode": "mock", "serverTime": _now(), "maxServerOrder": 0, "replica": None}))
            return
        if route == "/sync/pull" and method == "GET":
            query = parse_qs(parsed.query)
            self._send(
                200,
                self._data(
                    {
                        "events": [],
                        "nextCursor": {
                            "scope": {"scope": query.get("scope", ["global"])[0], "workspaceId": query.get("workspaceId", [None])[0]},
                            "replicaId": query.get("replicaId", ["replica-uiux-1"])[0],
                            "lastServerOrder": 0,
                        },
                        "hasMore": False,
                    }
                ),
            )
            return
        self._send(404, {"error": {"code": "not_found", "message": f"mock route not found: {method} {route}"}})


class MockApiServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], state: MockState) -> None:
        super().__init__(address, MockApiHandler)
        self.state = state


@dataclass
class MockApiRuntime:
    server: MockApiServer
    thread: threading.Thread
    state: MockState
    url: str

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def start_mock_api(host: str = "127.0.0.1") -> MockApiRuntime:
    state = MockState()
    port = _free_port(host)
    server = MockApiServer((host, port), state)
    thread = threading.Thread(target=server.serve_forever, name="uiux-mock-api", daemon=True)
    thread.start()
    # Small readiness proof for deterministic reports.
    time.sleep(0.05)
    return MockApiRuntime(server=server, thread=thread, state=state, url=f"http://{host}:{port}/api/v1")
