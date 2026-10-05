from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time
from typing import Any, Callable
from urllib.parse import urlparse


class CdpError(RuntimeError):
    pass


class WebSocketClient:
    def __init__(self, url: str, timeout: float = 15.0) -> None:
        self.url = url
        self.timeout = timeout
        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise CdpError(f"only ws:// CDP endpoints are supported, got {parsed.scheme!r}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path or "/"
        if parsed.query:
            self.path += "?" + parsed.query
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._handshake()

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if len(response) > 8192:
                break
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise CdpError("CDP websocket handshake failed: " + response[:200].decode("utf-8", errors="replace"))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def send_text(self, text: str) -> None:
        data = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        payload_parts: list[bytes] = []
        while True:
            first = self._recv_exact(2)
            opcode = first[0] & 0x0F
            masked = bool(first[1] & 0x80)
            length = first[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length) if length else b""
            if masked:
                data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
            if opcode == 0x8:
                raise CdpError("CDP websocket closed")
            if opcode == 0x9:  # ping
                self._send_pong(data)
                continue
            if opcode in {0x1, 0x0}:
                payload_parts.append(data)
                if first[0] & 0x80:
                    return b"".join(payload_parts).decode("utf-8", errors="replace")

    def _send_pong(self, data: bytes) -> None:
        header = bytearray([0x8A])
        length = len(data)
        header.append(0x80 | length)
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise CdpError("unexpected EOF from CDP websocket")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class CdpSession:
    def __init__(self, websocket_url: str, on_event: Callable[[dict[str, Any]], None] | None = None, timeout: float = 15.0) -> None:
        self.ws = WebSocketClient(websocket_url, timeout=timeout)
        self.next_id = 0
        self.on_event = on_event

    def close(self) -> None:
        self.ws.close()

    def command(self, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        self.next_id += 1
        command_id = self.next_id
        self.ws.send_text(json.dumps({"id": command_id, "method": method, "params": params or {}}, separators=(",", ":")))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError(f"timeout waiting for CDP command {method}")
            self.ws.sock.settimeout(remaining)
            message = json.loads(self.ws.recv_text())
            if "id" in message and message["id"] == command_id:
                if "error" in message:
                    raise CdpError(f"CDP {method} failed: {message['error']}")
                return message.get("result", {})
            if self.on_event:
                self.on_event(message)

    def drain_events(self, seconds: float = 0.1) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                self.ws.sock.settimeout(max(0.01, deadline - time.monotonic()))
                message = json.loads(self.ws.recv_text())
            except (socket.timeout, TimeoutError):
                return
            if self.on_event:
                self.on_event(message)

    def evaluate(self, expression: str, *, await_promise: bool = True, timeout: float = 15.0) -> Any:
        result = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
            },
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            raise CdpError(f"Runtime.evaluate exception: {result['exceptionDetails']}")
        remote = result.get("result", {})
        if "value" in remote:
            return remote["value"]
        if remote.get("type") == "undefined":
            return None
        return remote.get("description")
