#!/usr/bin/env python3
"""Эталонная реализация общих контрактов (только стандартная библиотека).

Покрывает `p2p-kanban-account-ring/1`, `p2p-kanban-keyring/1`,
`p2p-kanban-rendezvous/1`, `p2p-kanban-error-report/1`,
`p2p-kanban-project-board/1` и `p2p-kanban-launcher-entry/1` из `contracts/`. Это не продуктовый код: она медленная
и нужна, чтобы у web, mobile и abl был один исполняемый ответ на вопрос «как
правильно». Направления реализуют контракты своими библиотеками и сверяются с
векторами в `contracts/*/1/vectors/`, которые эта же реализация производит.

    python -B tools/ecosystem/contract_ref.py generate   # перезаписать векторы

Криптография: secp256k1 BIP-340 (подписи Nostr), NIP-44 v2, XChaCha20-Poly1305,
HKDF-SHA256. Реализации прямолинейные и не защищены от атак по времени: только
для проверок и векторов, не для настоящих ключей.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"

RING = "p2p-kanban-account-ring/1"
KEYRING = "p2p-kanban-keyring/1"
RENDEZVOUS = "p2p-kanban-rendezvous/1"
ROAMING = "p2p-kanban-roaming/1"
ERROR_REPORT = "p2p-kanban-error-report/1"
PROJECT_BOARD = "p2p-kanban-project-board/1"
LAUNCHER_ENTRY = "p2p-kanban-launcher-entry/1"
LAUNCHER_STATUS = "p2p-kanban-launcher-status/1"

KIND_RING_ENTRY = 27790
KIND_RENDEZVOUS = 1991
KIND_SEALED = {"ring-log": 31990, "keyring": 31991, "presence": 31992}

MAX_ENTRIES = 1024
MAX_ENTRY_CONTENT = 16 * 1024
MAX_PARENTS = 16
MAX_RECIPIENTS = 64
ENTRY_TYPES = {"genesis", "add", "remove", "rename", "relays"}
DEVICE_KINDS = {"web", "android", "arch"}
ROLES = {"admin", "member"}


# ---------------------------------------------------------------- кодировки

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    if not isinstance(text, str) or "=" in text:
        raise ValueError("ожидается base64url без '='")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(value: object) -> str:
    """Каноническая форма JSON: ключи по порядку, без пробелов, UTF-8 как есть."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


# ---------------------------------------------------------------- secp256k1

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def _jac_double(p):
    x, y, z = p
    if y == 0:
        return (0, 0, 0)
    ys = y * y % P
    s = 4 * x * ys % P
    m = 3 * x * x % P
    nx = (m * m - 2 * s) % P
    ny = (m * (s - nx) - 8 * ys * ys) % P
    return (nx, ny, 2 * y * z % P)


def _jac_add(p, q):
    if p[2] == 0:
        return q
    if q[2] == 0:
        return p
    z1s, z2s = p[2] * p[2] % P, q[2] * q[2] % P
    u1, u2 = p[0] * z2s % P, q[0] * z1s % P
    s1, s2 = p[1] * z2s * q[2] % P, q[1] * z1s * p[2] % P
    if u1 == u2:
        return _jac_double(p) if s1 == s2 else (0, 0, 0)
    h, r = (u2 - u1) % P, (s2 - s1) % P
    h2 = h * h % P
    h3 = h * h2 % P
    nx = (r * r - h3 - 2 * u1 * h2) % P
    ny = (r * (u1 * h2 - nx) - s1 * h3) % P
    return (nx, ny, h * p[2] * q[2] % P)


def point_mul(point, scalar: int):
    result, addend = (0, 0, 0), (point[0], point[1], 1)
    while scalar:
        if scalar & 1:
            result = _jac_add(result, addend)
        addend = _jac_double(addend)
        scalar >>= 1
    if result[2] == 0:
        return None
    zi = pow(result[2], P - 2, P)
    return (result[0] * zi * zi % P, result[1] * zi * zi * zi % P)


def point_add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    r = _jac_add((a[0], a[1], 1), (b[0], b[1], 1))
    if r[2] == 0:
        return None
    zi = pow(r[2], P - 2, P)
    return (r[0] * zi * zi % P, r[1] * zi * zi * zi % P)


def lift_x(x: int):
    if x >= P:
        return None
    ys = (pow(x, 3, P) + 7) % P
    y = pow(ys, (P + 1) // 4, P)
    if y * y % P != ys:
        return None
    return (x, y if y % 2 == 0 else P - y)


def tagged_hash(tag: str, data: bytes) -> bytes:
    t = sha256(tag.encode())
    return sha256(t + t + data)


def _secret_int(secret_hex: str) -> int:
    d = int(secret_hex, 16)
    if not 1 <= d < N:
        raise ValueError("секретный ключ вне диапазона")
    return d


def public_key(secret_hex: str) -> str:
    return "%064x" % point_mul(G, _secret_int(secret_hex))[0]


def schnorr_sign(msg: bytes, secret_hex: str, aux: bytes) -> bytes:
    d0 = _secret_int(secret_hex)
    pt = point_mul(G, d0)
    d = d0 if pt[1] % 2 == 0 else N - d0
    t = (d ^ int.from_bytes(tagged_hash("BIP0340/aux", aux), "big")).to_bytes(32, "big")
    k0 = int.from_bytes(tagged_hash("BIP0340/nonce", t + pt[0].to_bytes(32, "big") + msg), "big") % N
    if k0 == 0:
        raise ValueError("k0 = 0")
    r = point_mul(G, k0)
    k = k0 if r[1] % 2 == 0 else N - k0
    e = int.from_bytes(tagged_hash("BIP0340/challenge", r[0].to_bytes(32, "big") + pt[0].to_bytes(32, "big") + msg), "big") % N
    return r[0].to_bytes(32, "big") + ((k + e * d) % N).to_bytes(32, "big")


def schnorr_verify(msg: bytes, pubkey: bytes, sig: bytes) -> bool:
    if len(pubkey) != 32 or len(sig) != 64:
        return False
    pt = lift_x(int.from_bytes(pubkey, "big"))
    r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    if pt is None or r >= P or s >= N:
        return False
    e = int.from_bytes(tagged_hash("BIP0340/challenge", sig[:32] + pubkey + msg), "big") % N
    rp = point_add(point_mul(G, s), point_mul(pt, N - e))
    return rp is not None and rp[1] % 2 == 0 and rp[0] == r


def ecdh_x(secret_hex: str, pubkey_hex: str) -> bytes:
    pt = lift_x(int(pubkey_hex, 16))
    if pt is None:
        raise ValueError("публичный ключ не на кривой")
    return point_mul(pt, _secret_int(secret_hex))[0].to_bytes(32, "big")


# ---------------------------------------------------------------- события Nostr

def event_id(event: dict) -> str:
    body = [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]]
    return sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()).hex()


def sign_event(secret_hex: str, kind: int, content: str, created_at: int, tags=None) -> dict:
    event = {"pubkey": public_key(secret_hex), "created_at": created_at, "kind": kind, "tags": tags or [], "content": content}
    event["id"] = event_id(event)
    # Детерминированный aux_rand: векторы воспроизводимы. Продуктовый код берёт случайный.
    event["sig"] = schnorr_sign(bytes.fromhex(event["id"]), secret_hex, sha256(b"vector-aux" + bytes.fromhex(event["id"]))).hex()
    return {k: event[k] for k in ("id", "pubkey", "created_at", "kind", "tags", "content", "sig")}


def verify_event(event: object, kind: int | None = None) -> str | None:
    """Возвращает причину отказа или None."""
    if not isinstance(event, dict):
        return "not-an-event"
    try:
        if kind is not None and event.get("kind") != kind:
            return "wrong-kind"
        if event_id(event) != event.get("id"):
            return "bad-id"
        if not schnorr_verify(bytes.fromhex(event["id"]), bytes.fromhex(event["pubkey"]), bytes.fromhex(event["sig"])):
            return "bad-signature"
    except (KeyError, TypeError, ValueError):
        return "malformed-event"
    return None


# ---------------------------------------------------------------- HKDF, ChaCha20, Poly1305

def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


def _rotl(v: int, c: int) -> int:
    return ((v << c) & 0xFFFFFFFF) | (v >> (32 - c))


def _quarter(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF; s[d] = _rotl(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF; s[b] = _rotl(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF; s[d] = _rotl(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF; s[b] = _rotl(s[b] ^ s[c], 7)


def _rounds(state):
    for _ in range(10):
        _quarter(state, 0, 4, 8, 12); _quarter(state, 1, 5, 9, 13)
        _quarter(state, 2, 6, 10, 14); _quarter(state, 3, 7, 11, 15)
        _quarter(state, 0, 5, 10, 15); _quarter(state, 1, 6, 11, 12)
        _quarter(state, 2, 7, 8, 13); _quarter(state, 3, 4, 9, 14)


_SIGMA = struct.unpack("<4I", b"expand 32-byte k")


def chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    init = list(_SIGMA) + list(struct.unpack("<8I", key)) + [counter] + list(struct.unpack("<3I", nonce))
    s = init[:]
    _rounds(s)
    return struct.pack("<16I", *((s[i] + init[i]) & 0xFFFFFFFF for i in range(16)))


def chacha20(key: bytes, nonce: bytes, data: bytes, counter: int = 0) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 64):
        block = chacha20_block(key, counter + i // 64, nonce)
        out += bytes(a ^ b for a, b in zip(data[i:i + 64], block))
    return bytes(out)


def hchacha20(key: bytes, nonce16: bytes) -> bytes:
    s = list(_SIGMA) + list(struct.unpack("<8I", key)) + list(struct.unpack("<4I", nonce16))
    _rounds(s)
    return struct.pack("<8I", *(s[0:4] + s[12:16]))


def poly1305(key: bytes, msg: bytes) -> bytes:
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:], "little")
    acc, p = 0, (1 << 130) - 5
    for i in range(0, len(msg), 16):
        chunk = msg[i:i + 16] + b"\x01"
        acc = (acc + int.from_bytes(chunk, "little")) * r % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _pad16(n: int) -> bytes:
    return b"\x00" * (-n % 16)


def xchacha_seal(key: bytes, nonce24: bytes, plaintext: bytes, aad: bytes) -> bytes:
    subkey, nonce = hchacha20(key, nonce24[:16]), b"\x00" * 4 + nonce24[16:]
    otk = chacha20_block(subkey, 0, nonce)[:32]
    ct = chacha20(subkey, nonce, plaintext, 1)
    mac = poly1305(otk, aad + _pad16(len(aad)) + ct + _pad16(len(ct)) + struct.pack("<QQ", len(aad), len(ct)))
    return ct + mac


def xchacha_open(key: bytes, nonce24: bytes, sealed: bytes, aad: bytes) -> bytes:
    if len(sealed) < 16:
        raise ValueError("шифртекст короче тега")
    subkey, nonce = hchacha20(key, nonce24[:16]), b"\x00" * 4 + nonce24[16:]
    otk = chacha20_block(subkey, 0, nonce)[:32]
    ct, tag = sealed[:-16], sealed[-16:]
    mac = poly1305(otk, aad + _pad16(len(aad)) + ct + _pad16(len(ct)) + struct.pack("<QQ", len(aad), len(ct)))
    if not hmac.compare_digest(mac, tag):
        raise ValueError("AEAD: подмена или чужой ключ")
    return chacha20(subkey, nonce, ct, 1)


# ---------------------------------------------------------------- NIP-44 v2

def nip44_conversation_key(secret_hex: str, pubkey_hex: str) -> bytes:
    return hkdf_extract(b"nip44-v2", ecdh_x(secret_hex, pubkey_hex))


def _nip44_padded_len(n: int) -> int:
    if n <= 32:
        return 32
    nxt = 1 << (n - 1).bit_length()
    chunk = 32 if nxt <= 256 else nxt // 8
    return chunk * ((n - 1) // chunk + 1)


def _nip44_keys(conv: bytes, nonce: bytes):
    k = hkdf_expand(conv, nonce, 76)
    return k[:32], k[32:44], k[44:]


def nip44_encrypt(conv: bytes, plaintext: str, nonce: bytes) -> str:
    raw = plaintext.encode()
    if not 1 <= len(raw) <= 65535:
        raise ValueError("NIP-44: длина 1..65535")
    padded = struct.pack(">H", len(raw)) + raw + b"\x00" * (_nip44_padded_len(len(raw)) - len(raw))
    ck, cn, hk = _nip44_keys(conv, nonce)
    ct = chacha20(ck, cn, padded)
    mac = hmac.new(hk, nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(b"\x02" + nonce + ct + mac).decode()


def nip44_decrypt(conv: bytes, payload: str) -> str:
    data = base64.b64decode(payload, validate=True)
    if len(data) < 99 or data[0] != 2:
        raise ValueError("NIP-44: неизвестная версия или короткий payload")
    nonce, ct, mac = data[1:33], data[33:-32], data[-32:]
    ck, cn, hk = _nip44_keys(conv, nonce)
    if not hmac.compare_digest(hmac.new(hk, nonce + ct, hashlib.sha256).digest(), mac):
        raise ValueError("NIP-44: неверный MAC")
    padded = chacha20(ck, cn, ct)
    n = struct.unpack(">H", padded[:2])[0]
    if n == 0 or len(padded) != 2 + _nip44_padded_len(n):
        raise ValueError("NIP-44: неверное выравнивание")
    return padded[2:2 + n].decode()


# ---------------------------------------------------------------- запечатанный конверт

def account_tag(account_id: str) -> str:
    return b64url(hmac.new(bytes.fromhex(account_id), b"p2p-kanban:account-tag:v1", hashlib.sha256).digest())


def seal_aad(record_type: str, tag: str) -> bytes:
    return f"p2p-kanban:seal:v1|{record_type}|{tag}".encode()


def seal(sender_secret: str, recipients: list[str], record_type: str, tag: str, plaintext: dict, seed: bytes) -> dict:
    """Содержимое записи на relay: шифртекст один, ключ обёрнут NIP-44 для каждого участника."""
    if not 1 <= len(recipients) <= MAX_RECIPIENTS:
        raise ValueError("получателей 1..64")
    cek = sha256(b"cek" + seed)
    nonce = sha256(b"nonce" + seed)[:24]
    wrapped = []
    for index, pk in enumerate(sorted(set(recipients))):
        conv = nip44_conversation_key(sender_secret, pk)
        wrapped.append(nip44_encrypt(conv, b64url(cek), sha256(b"wrap" + seed + bytes([index]))))
    return {
        "version": 1,
        "type": record_type,
        "nonce": b64url(nonce),
        "ciphertext": b64url(xchacha_seal(cek, nonce, canonical(plaintext).encode(), seal_aad(record_type, tag))),
        "recipients": sorted(wrapped),
    }


def unseal(recipient_secret: str, sender_pubkey: str, tag: str, sealed: dict) -> dict:
    conv = nip44_conversation_key(recipient_secret, sender_pubkey)
    for wrapped in sealed["recipients"]:
        try:
            cek = unb64url(nip44_decrypt(conv, wrapped))
        except ValueError:
            continue
        plain = xchacha_open(cek, unb64url(sealed["nonce"]), unb64url(sealed["ciphertext"]), seal_aad(sealed["type"], tag))
        return json.loads(plain.decode())
    raise ValueError("конверт запечатан не для этого устройства")


def sealed_event(sender_secret: str, record_type: str, account_id: str, recipients: list[str], plaintext: dict, created_at: int, seed: bytes) -> dict:
    tag = account_tag(account_id)
    content = seal(sender_secret, recipients, record_type, tag, plaintext, seed)
    tags = [["d", tag], ["t", "p2pkanban-ring"], ["v", "1"]]
    return sign_event(sender_secret, KIND_SEALED[record_type], canonical(content), created_at, tags)


# ---------------------------------------------------------------- журнал кольца

def make_entry(secret_hex: str, body: dict, created_at: int) -> dict:
    body = dict(body)
    body.setdefault("protocol", RING)
    return sign_event(secret_hex, KIND_RING_ENTRY, canonical(body), created_at)


def _parse_entry(event: dict):
    """(content, причина отказа)."""
    reason = verify_event(event, KIND_RING_ENTRY)
    if reason:
        return None, reason
    if len(event["content"].encode()) > MAX_ENTRY_CONTENT:
        return None, "too-large"
    try:
        content = json.loads(event["content"])
    except json.JSONDecodeError:
        return None, "malformed-content"
    if not isinstance(content, dict) or not isinstance(content.get("type"), str):
        return None, "malformed-content"
    protocol = content.get("protocol")
    if protocol != RING:
        return None, "foreign-protocol"
    parents = content.get("parents")
    if not isinstance(parents, list) or len(parents) > MAX_PARENTS or len(set(parents)) != len(parents):
        return None, "bad-parents"
    if content["type"] == "genesis":
        if parents:
            return None, "bad-parents"
    elif not parents:
        return None, "bad-parents"
    return content, None


def _device_ok(device: object) -> bool:
    return (
        isinstance(device, dict)
        and isinstance(device.get("publicKey"), str) and len(device["publicKey"]) == 64
        and lift_x(int(device["publicKey"], 16)) is not None
        and isinstance(device.get("name"), str) and 1 <= len(device["name"]) <= 64
        and device.get("kind") in DEVICE_KINDS
        and device.get("role") in ROLES
    )


def _relays_ok(relays: object) -> bool:
    if not isinstance(relays, dict):
        return False
    urls, acks = relays.get("urls"), relays.get("minAcks")
    return (
        isinstance(urls, list) and 1 <= len(urls) <= 16 and len(set(urls)) == len(urls)
        and all(isinstance(u, str) and u.startswith("wss://") and len(u) <= 256 for u in urls)
        and isinstance(acks, int) and not isinstance(acks, bool) and 1 <= acks <= len(urls)
    )


class _State:
    def __init__(self):
        self.members: dict[str, dict] = {}
        self.removed: dict[str, str] = {}
        self.relays: dict | None = None

    def admins(self) -> set[str]:
        return {pk for pk, d in self.members.items() if d["role"] == "admin"}


def _apply(state: _State, content: dict, signer: str, entry_id: str) -> None:
    kind = content["type"]
    if kind == "genesis":
        d = content["device"]
        state.members[d["publicKey"]] = {**{k: d[k] for k in ("publicKey", "name", "kind", "role")}, "addedBy": None, "addEntry": entry_id}
        state.relays = content["relays"]
    elif kind == "add":
        d = content["device"]
        if d["publicKey"] not in state.removed and d["publicKey"] not in state.members:
            state.members[d["publicKey"]] = {**{k: d[k] for k in ("publicKey", "name", "kind", "role")}, "addedBy": signer, "addEntry": entry_id}
    elif kind == "remove":
        state.removed.setdefault(content["publicKey"], entry_id)
        state.members.pop(content["publicKey"], None)
    elif kind == "rename":
        if content["publicKey"] in state.members:
            state.members[content["publicKey"]]["name"] = content["name"]
    elif kind == "relays":
        state.relays = content["relays"]


def _authorize(past: _State, content: dict, signer: str) -> str | None:
    """Причина отказа или None. Проверяется по причинному прошлому записи."""
    kind = content["type"]
    member = past.members.get(signer)
    if kind == "genesis":
        return "duplicate-genesis"  # настоящий genesis разбирается отдельно
    if member is None:
        return "signer-removed" if signer in past.removed else "signer-not-member"
    admin = member["role"] == "admin"
    if kind == "add":
        if not admin:
            return "signer-not-admin"
        if not _device_ok(content.get("device")) or content.get("via") not in {"rendezvous", "migration"}:
            return "malformed-content"
        target = content["device"]["publicKey"]
        if target in past.removed:
            return "key-was-removed"
        if target in past.members:
            return "already-member"
        return None
    if kind == "remove":
        target = content.get("publicKey")
        if target not in past.members:
            return "unknown-target"
        if not admin and target != signer:
            return "signer-not-admin"
        if past.admins() == {target}:
            return "last-admin"
        return None
    if kind == "rename":
        target, name = content.get("publicKey"), content.get("name")
        if target not in past.members:
            return "unknown-target"
        if not admin and target != signer:
            return "signer-not-admin"
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            return "malformed-content"
        return None
    if kind == "relays":
        if not admin:
            return "signer-not-admin"
        return None if _relays_ok(content.get("relays")) else "malformed-content"
    return None  # неизвестный тип: любой участник, без последствий


def fold_ring(entries: list[dict], account_id: str | None = None) -> dict:
    """Свернуть журнал в состояние. Порядок входа не важен.

    account_id — id genesis; без него журнал обязан содержать ровно один genesis.
    """
    if len(entries) > MAX_ENTRIES:
        raise ValueError("журнал длиннее 1024 записей")
    rejected: dict[str, str] = {}
    outdated: set[str] = set()
    parsed: dict[str, tuple[dict, dict]] = {}
    for event in entries:
        eid = event.get("id") if isinstance(event, dict) else None
        if isinstance(eid, str) and eid in parsed:
            continue
        content, reason = _parse_entry(event)
        if reason:
            if reason == "foreign-protocol":
                try:
                    proto = json.loads(event["content"]).get("protocol", "")
                    if isinstance(proto, str) and proto.startswith("p2p-kanban-account-ring/"):
                        outdated.add(f"protocol:{proto}")
                except (ValueError, AttributeError, KeyError, TypeError):
                    pass
            rejected[str(eid)] = reason
            continue
        parsed[eid] = (event, content)

    geneses = sorted(eid for eid, (_, c) in parsed.items() if c["type"] == "genesis")
    if account_id is not None:
        genesis = account_id if account_id in geneses else None
    else:
        genesis = geneses[0] if len(geneses) == 1 else None
    if genesis is None:
        raise ValueError("в журнале нет единственного genesis этого аккаунта")
    g_event, g_content = parsed[genesis]
    if not _device_ok(g_content.get("device")) or g_content["device"]["role"] != "admin" \
            or g_content["device"]["publicKey"] != g_event["pubkey"] or not _relays_ok(g_content.get("relays")) \
            or not isinstance(g_content.get("nonce"), str) or len(g_content["nonce"]) < 22:
        raise ValueError("genesis некорректен")
    for eid in list(parsed):
        _, c = parsed[eid]
        if eid != genesis and (c["type"] == "genesis" or c.get("accountId") != genesis):
            rejected[eid] = "duplicate-genesis" if c["type"] == "genesis" else "foreign-account"
            del parsed[eid]

    # Записи с неизвестными предками ждут; ожидание наследуется.
    pending: dict[str, list[str]] = {}
    changed = True
    while changed:
        changed = False
        for eid, (_, c) in list(parsed.items()):
            missing = [p for p in c["parents"] if p not in parsed]
            if missing:
                pending[eid] = sorted(missing)
                del parsed[eid]
                changed = True

    # Линеаризация: Кан, среди готовых — меньший id.
    children: dict[str, list[str]] = {eid: [] for eid in parsed}
    indegree = {eid: len(c["parents"]) for eid, (_, c) in parsed.items()}
    for eid, (_, c) in parsed.items():
        for p in c["parents"]:
            children[p].append(eid)
    ready = sorted(eid for eid, d in indegree.items() if d == 0)
    order: list[str] = []
    while ready:
        eid = ready.pop(0)
        order.append(eid)
        for ch in children[eid]:
            indegree[ch] -= 1
            if indegree[ch] == 0:
                ready.append(ch)
        ready.sort()
    position = {eid: i for i, eid in enumerate(order)}

    ancestors: dict[str, set[str]] = {}
    for eid in order:
        acc: set[str] = set()
        for p in parsed[eid][1]["parents"]:
            acc.add(p)
            acc |= ancestors[p]
        ancestors[eid] = acc

    def past_state(eid: str, valid: set[str]) -> _State:
        st = _State()
        for a in sorted(ancestors[eid] & valid, key=position.get):
            ev, c = parsed[a]
            _apply(st, c, ev["pubkey"], a)
        return st

    def run(frozen: set[str], forced: set[str]) -> tuple[set[str], dict[str, str]]:
        valid: set[str] = set()
        reasons: dict[str, str] = {}
        for eid in order:
            ev, c = parsed[eid]
            if eid == genesis:
                valid.add(eid)
                continue
            if eid in frozen:
                reasons[eid] = "frozen-by-remove"
                continue
            if eid in forced:
                valid.add(eid)
                continue
            why = _authorize(past_state(eid, valid), c, ev["pubkey"])
            if why:
                reasons[eid] = why
            else:
                valid.add(eid)
        return valid, reasons

    # Фаза A: права по причинному прошлому.
    valid_a, _ = run(set(), set())
    removes = [e for e in valid_a if parsed[e][1]["type"] == "remove"]
    # Фаза B: удаление замораживает всё, что удалённое устройство сделало «за спиной» удалившего.
    frozen: set[str] = set()
    for eid in valid_a:
        ev, c = parsed[eid]
        if c["type"] in ("remove", "genesis"):
            continue
        against = [r for r in removes if parsed[r][1]["publicKey"] == ev["pubkey"]]
        if against and not any(eid in ancestors[r] for r in against):
            frozen.add(eid)
    # Фаза C: каскад; законные в своём прошлом удаления действуют всегда.
    valid, reasons = run(frozen, set(removes))

    final = _State()
    unknown = []
    for eid in order:
        if eid in valid:
            ev, c = parsed[eid]
            _apply(final, c, ev["pubkey"], eid)
            if c["type"] not in ENTRY_TYPES:
                unknown.append({"id": eid, "type": c["type"]})
                outdated.add(f"type:{c['type']}")
    for eid, why in reasons.items():
        rejected[eid] = why

    parents_of_any = {p for eid in order for p in parsed[eid][1]["parents"]}
    return {
        "accountId": genesis,
        "accountTag": account_tag(genesis),
        "members": sorted(final.members.values(), key=lambda d: d["publicKey"]),
        "removed": [{"publicKey": pk, "removeEntry": rid} for pk, rid in sorted(final.removed.items())],
        "relays": final.relays,
        "heads": sorted(eid for eid in order if eid not in parents_of_any),
        "order": order,
        "rejected": [{"id": eid, "reason": why} for eid, why in sorted(rejected.items())],
        "pending": [{"id": eid, "missing": miss} for eid, miss in sorted(pending.items())],
        "unknown": unknown,
        "readerOutdated": sorted(outdated),
    }


RING_PROTOCOLS = (RING, KEYRING, RENDEZVOUS)


def presence_skew(presences: list[dict], ring_heads: list[str]) -> list[dict]:
    """Какие устройства отстают: не знают протоколов кольца или видели старый журнал."""
    skew = []
    for p in sorted(presences, key=lambda x: x["publicKey"]):
        known = set((p.get("software") or {}).get("protocols") or [])
        missing = [proto for proto in RING_PROTOCOLS if proto not in known]
        stale = sorted(p.get("ringHeads") or []) != sorted(ring_heads)
        if missing or stale:
            skew.append({"publicKey": p["publicKey"], "missingProtocols": missing, "staleRing": stale})
    return skew


# ---------------------------------------------------------------- связка ключей

def _item_rank(item: dict):
    roaming = item.get("roaming") if isinstance(item.get("roaming"), dict) else {}
    epoch = roaming.get("epoch", 0) if isinstance(roaming.get("epoch", 0), int) else 0
    return (epoch, item.get("rev", 0), sha256(canonical(item).encode()).hex())


def merge_keyrings(copies: list[dict]) -> list[dict]:
    """Слияние копий связки: побеждает (epoch, rev, sha256); удаление необратимо."""
    best: dict[tuple[str, str], dict] = {}
    deleted: set[tuple[str, str]] = set()
    for copy in copies:
        for item in copy.get("items", []):
            key = (item["kind"], item["id"])
            if item.get("deleted") is True:
                deleted.add(key)
            if key not in best or _item_rank(item) > _item_rank(best[key]):
                best[key] = item
    merged = []
    for key in sorted(best):
        item = best[key]
        if key in deleted and item.get("deleted") is not True:
            item = {k: v for k, v in item.items() if k != "roaming"}
            item["deleted"] = True
        merged.append(item)
    return merged


def keyring_digest(items: list[dict]) -> str:
    return sha256(canonical(sorted(items, key=lambda i: (i["kind"], i["id"]))).encode()).hex()


# ---------------------------------------------------------------- встреча

QR_PREFIX = "p2pkanban:rv1:"


def qr_encode(qr: dict) -> str:
    return QR_PREFIX + b64url(canonical(qr).encode())


def qr_decode(text: str) -> dict:
    if not text.startswith(QR_PREFIX):
        raise ValueError("не QR встречи p2pKanban версии 1")
    return json.loads(unb64url(text[len(QR_PREFIX):]).decode())


def session_id(secret: bytes) -> str:
    return b64url(hmac.new(secret, b"p2p-kanban:rendezvous-id:v1", hashlib.sha256).digest())


def session_key(secret: bytes) -> bytes:
    return hkdf_expand(hkdf_extract(b"p2p-kanban:rendezvous:v1", secret), b"session-key", 32)


def confirm_code(sid: str, joiner_pubkey: str) -> str:
    n = int.from_bytes(sha256(f"p2p-kanban:rendezvous-confirm:v1|{sid}|{joiner_pubkey}".encode())[:4], "big") % 1_000_000
    return f"{n // 1000:03d} {n % 1000:03d}"


def rendezvous_aad(sid: str, sender_pubkey: str, part: int, parts: int) -> bytes:
    return f"p2p-kanban:rendezvous:v1|{sid}|{sender_pubkey}|{part}/{parts}".encode()


def rendezvous_event(secret_hex: str, secret: bytes, message: dict, created_at: int, expires_at: int, seed: bytes) -> dict:
    sid = session_id(secret)
    nonce = sha256(b"rv-nonce" + seed)[:24]
    sender = public_key(secret_hex)
    ct = xchacha_seal(session_key(secret), nonce, canonical(message).encode(), rendezvous_aad(sid, sender, 1, 1))
    content = canonical({"version": 1, "nonce": b64url(nonce), "ciphertext": b64url(ct)})
    tags = [["s", sid], ["t", "p2pkanban-rendezvous"], ["part", "1", "1"], ["expiration", str(expires_at)]]
    return sign_event(secret_hex, KIND_RENDEZVOUS, content, created_at, tags)


def rendezvous_open(event: dict, secret: bytes) -> dict:
    sid = session_id(secret)
    tags = {t[0]: t[1:] for t in event["tags"]}
    if tags.get("s") != [sid]:
        raise ValueError("событие другой встречи")
    part, parts = (int(x) for x in tags.get("part", ["1", "1"]))
    body = json.loads(event["content"])
    plain = xchacha_open(session_key(secret), unb64url(body["nonce"]), unb64url(body["ciphertext"]), rendezvous_aad(sid, event["pubkey"], part, parts))
    return json.loads(plain.decode())


# ---------------------------------------------------------------- отчёт об ошибке

HIDDEN = "[скрыто]"
REPORT_LIMITS = {
    "message": 1000, "screen": 200, "operation": 200, "stage": 200, "platform": 200,
    "error.name": 200, "error.detail": 2000, "http.path": 500, "http.body": 4000, "log": 500,
}
MAX_LOG_LINES = 50
REDACTED_FIELDS = ("message", "stage", "error.detail", "http.path", "http.body")

_BEARER = re.compile(r"bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_NSEC = re.compile(r"nsec1[02-9ac-hj-np-z]{20,}")
_URL_CREDENTIALS = re.compile(r"://[^/\s:@]+:[^/\s@]+@")
_KEY_VALUE = re.compile(
    r'(^|[^A-Za-z0-9])'
    r'([A-Za-z0-9_-]*(?:password|passwd|secret|token|apikey|api_key|api-key|privatekey|private_key|'
    r'passphrase|mnemonic|boardkey|board_key|masterkey|master_key|cookie)[A-Za-z0-9_-]*)'
    r'(\\?"?[ \t]*[:=][ \t]*)'
    r'(\\"(?:[^\\]|\\[^"])*?\\"|"(?:[^"\\]|\\[\s\S])*"|[^\s,;&}"\\]+)',
    re.IGNORECASE,
)


def redact(text: str) -> tuple[str, int]:
    """Вырезать секреты из строки. Возвращает (текст, число замен)."""
    count = 0

    def plain(replacement: str):
        def sub(match: re.Match) -> str:
            nonlocal count
            count += 1
            return replacement
        return sub

    text = _BEARER.sub(plain("Bearer " + HIDDEN), text)
    text = _JWT.sub(plain("[скрыто:jwt]"), text)
    text = _NSEC.sub(plain("[скрыто:nsec]"), text)
    text = _URL_CREDENTIALS.sub(plain("://" + HIDDEN + "@"), text)

    def key_value(match: re.Match) -> str:
        nonlocal count
        lead, key, sep, value = match.groups()
        if value.startswith('\\"'):
            hidden = '\\"' + HIDDEN + '\\"'
        elif value.startswith('"'):
            hidden = '"' + HIDDEN + '"'
        else:
            hidden = HIDDEN
        if value == hidden or value.startswith("Bearer") or value.startswith("[скрыто"):
            return match.group(0)
        count += 1
        return lead + key + sep + hidden

    text = _KEY_VALUE.sub(key_value, text)
    return text, count


def truncate(text: str, limit: int) -> str:
    """Обрезка по кодовым точкам Unicode (не по байтам и не по UTF-16)."""
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def build_report(raw: dict) -> dict:
    """Нормализовать сырой отчёт: переводы строк, вырезание секретов, пределы длины.

    Вход — те же поля, что в report.schema.json, с любыми длинами; `redacted`
    входа (если есть) прибавляется к новым заменам, поэтому повторная
    нормализация ничего не меняет.
    """
    report = json.loads(json.dumps(raw))
    report["protocol"] = ERROR_REPORT
    count = report.get("redacted", 0) if isinstance(report.get("redacted"), int) else 0

    def field(path: str):
        node = report
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                return None, None
        return node, parts[-1]

    for path in ("message", "screen", "operation", "stage", "platform", "error.name", "error.detail", "http.path", "http.body"):
        node, key = field(path)
        if node is None or not isinstance(node.get(key), str):
            continue
        value = _newlines(node[key])
        if path in REDACTED_FIELDS:
            value, n = redact(value)
            count += n
        node[key] = truncate(value, REPORT_LIMITS[path])
    lines = []
    for line in (report.get("logs") or [])[-MAX_LOG_LINES:]:
        value, n = redact(_newlines(line).replace("\n", " "))
        count += n
        lines.append(truncate(value, REPORT_LIMITS["log"]))
    report["logs"] = lines
    report["redacted"] = count
    return report


def _continued(text: str) -> str:
    return text.replace("\n", "\n  ")


def render_report(report: dict) -> str:
    """Текст кнопки «Скопировать подробности»: сначала для человека, в конце JSON для машины."""
    sw = report["software"]
    lines = [
        "p2pKanban: подробности ошибки",
        f"Отчёт: {report['reportId']} · {report['at']}",
        f"Программа: {sw['direction']} {sw['version']} · сборка {sw.get('build') or 'неизвестна'} · коммит {sw.get('commit') or 'неизвестен'}",
    ]
    if report.get("platform"):
        lines.append(f"Платформа: {report['platform']}")
    where = [report[k] for k in ("screen", "operation", "stage") if report.get(k)]
    if where:
        lines.append("Где: " + " → ".join(where))
    lines.append(f"Сообщение: {_continued(report['message'])}")
    error = report["error"]
    lines.append("Ошибка: " + " · ".join(_continued(x) for x in (error["kind"], error.get("name"), error.get("detail")) if x))
    http = report.get("http")
    if http:
        status = str(http["status"]) if http.get("status") else "нет ответа"
        line = f"HTTP: {http['method']} {http['path']} → {status}"
        if http.get("requestId"):
            line += f" · запрос {http['requestId']}"
        if http.get("errorId"):
            line += f" · ошибка узла {http['errorId']}"
        lines.append(line)
    peer = report.get("peer")
    if peer:
        lines.append(f"Узел: {peer['direction']} {peer.get('version') or '?'} · сборка {peer.get('build') or 'неизвестна'} · коммит {peer.get('commit') or 'неизвестен'}")
    if http and http.get("body"):
        lines.append("Ответ узла:")
        lines.extend("  " + row for row in http["body"].split("\n"))
    if report.get("redacted"):
        lines.append(f"Скрыто значений: {report['redacted']}")
    if report.get("logs"):
        lines.append(f"Журнал ({len(report['logs'])} последних строк):")
        lines.extend("  " + row for row in report["logs"])
    lines.append(f"--- {ERROR_REPORT} ---")
    lines.append(canonical(report))
    return "\n".join(lines) + "\n"


def parse_report_text(text: str) -> dict:
    """Обратное чтение: JSON после разделителя — источник истины, текст выше — для человека."""
    marker = f"--- {ERROR_REPORT} ---\n"
    head, sep, tail = text.partition(marker)
    if not sep:
        raise ValueError("в тексте нет отчёта p2p-kanban-error-report/1")
    return json.loads(tail)


NODE_HEADER = "x-p2p-kanban-node"
ERROR_ID_HEADER = "x-p2p-error-id"


def parse_node_header(value: str) -> dict:
    """`2.1.0; build=8087da08253b; commit=<40 hex>` → {version, build, commit}; unknown → null."""
    parts = [p.strip() for p in value.split(";")]
    out = {"version": parts[0] or None, "build": None, "commit": None}
    for part in parts[1:]:
        key, _, val = part.partition("=")
        if key in ("build", "commit"):
            out[key] = None if val in ("", "unknown") else val
    return out


# ---------------------------------------------------------------- встроенная доска проекта

PROJECT_BOARD_ID = "01a10d38-f902-7665-8612-3e74278ceafa"
PROJECT_WORKSPACE_ID = "01a10d38-f901-746d-92f7-10598bb1cc42"
PROJECT_BOARD_MAX_BYTES = 10 * 1024 * 1024
PROJECT_BOARD_SOURCES = ("build", "cache", "node", "upstream")


class ProjectBoardRejected(ValueError):
    """Кандидат не является доской проекта; `reason` — код из SPEC."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def project_board_summary(raw: bytes) -> dict:
    """Байты переносимой доски → сводка доски проекта или ProjectBoardRejected.

    Проверяется только то, что нужно для выбора: формат, постоянный id доски,
    ревизия. Полную проверку содержимого делает импортёр направления.
    """
    if len(raw) > PROJECT_BOARD_MAX_BYTES:
        raise ProjectBoardRejected("too-large")
    try:
        bundle = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProjectBoardRejected("not-json") from None
    if not isinstance(bundle, dict):
        raise ProjectBoardRejected("not-json")
    manifest = bundle.get("manifest.json")
    origin = bundle.get("origin")
    if (not isinstance(manifest, dict) or manifest.get("format") != "p2p_planner_bundle"
            or manifest.get("formatVersion") != 1 or manifest.get("bundleKind") != "portable_export"
            or manifest.get("scopeKind") != "board"):
        raise ProjectBoardRejected("wrong-format")
    if manifest.get("boardId") != PROJECT_BOARD_ID or manifest.get("workspaceId") != PROJECT_WORKSPACE_ID:
        raise ProjectBoardRejected("foreign-board")
    if not isinstance(origin, dict) or origin.get("selfHosted") is not True:
        raise ProjectBoardRejected("foreign-board")
    revision = origin.get("boardRevision")
    patch = origin.get("lastPatchId")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1 \
            or not isinstance(patch, str) or not patch.strip():
        raise ProjectBoardRejected("no-revision")
    generated = origin.get("generatedAt")
    return {
        "protocol": PROJECT_BOARD,
        "boardId": PROJECT_BOARD_ID,
        "revision": revision,
        "lastPatchId": patch,
        "generatedAt": generated if isinstance(generated, str) else None,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def select_project_board(candidates: list[dict]) -> dict:
    """Выбрать, какую доску проекта показать.

    `candidates` — [{source, summary}] или [{source, rejected}] в порядке,
    в котором клиент их знает (build первым). Побеждает старшая ревизия; при
    равной ревизии и разных байтах — меньший sha256 и `conflict: true`; при
    полном совпадении — первый по списку.
    """
    valid = [c for c in candidates if c.get("summary")]
    rejected = [{"source": c["source"], "reason": c["rejected"]} for c in candidates if not c.get("summary")]
    if not valid:
        return {"protocol": PROJECT_BOARD, "chosen": None, "revision": None, "lastPatchId": None,
                "sha256": None, "conflict": False, "behind": [], "rejected": rejected}
    top = max(c["summary"]["revision"] for c in valid)
    leaders = [c for c in valid if c["summary"]["revision"] == top]
    hashes = sorted({c["summary"]["sha256"] for c in leaders})
    winner = next(c for c in leaders if c["summary"]["sha256"] == hashes[0])
    behind = [{"source": c["source"], "revision": c["summary"]["revision"]}
              for c in valid if c["summary"]["revision"] < top]
    return {
        "protocol": PROJECT_BOARD,
        "chosen": winner["source"],
        "revision": top,
        "lastPatchId": winner["summary"]["lastPatchId"],
        "sha256": hashes[0],
        "conflict": len(hashes) > 1,
        "behind": behind,
        "rejected": rejected,
    }


# ---------------------------------------------------------------- launcher-entry/1

LAUNCHER_PYTHON = "{python}"
LAUNCHER_VALUE = "{value}"
LAUNCHER_SETTING_TYPES = ("port", "choice", "bool")
_LAUNCHER_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_LAUNCHER_ARG = re.compile(r"^[^\x00-\x1f]{1,200}$")
_LAUNCHER_SCRIPT = re.compile(r"^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_./-]+\.py$")
_LAUNCHER_URL = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+(?:/[^\s]*)?$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


class LauncherRejected(ValueError):
    """Объявление, команда или ответ status не по контракту; `reason` — код из SPEC."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def _launcher_text(value, limit: int = 400) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) and len(value) <= limit


def _launcher_value_ok(setting: dict, value) -> bool:
    kind = setting["type"]
    if value is None:
        return kind != "bool"
    if kind == "port":
        return isinstance(value, int) and not isinstance(value, bool) and \
            setting.get("min", 1024) <= value <= setting.get("max", 65535)
    if kind == "choice":
        return value in [item["value"] for item in setting["choices"]]
    return isinstance(value, bool)


def launcher_entry_check(entry, component: str | None = None) -> dict:
    """Проверить `<направление>/launcher.json`; вернуть его без изменений или LauncherRejected."""
    if not isinstance(entry, dict) or entry.get("schema") != LAUNCHER_ENTRY:
        raise LauncherRejected("wrong-schema")
    name = entry.get("component")
    if not isinstance(name, str) or not _LAUNCHER_ID.match(name) or (component is not None and name != component):
        raise LauncherRejected("bad-component", str(name))
    settings = entry.get("settings", [])
    if not isinstance(settings, list):
        raise LauncherRejected("bad-setting", "settings — список")
    known: dict[str, dict] = {}
    for setting in settings:
        if not isinstance(setting, dict) or not isinstance(setting.get("id"), str) or not _LAUNCHER_ID.match(setting["id"]):
            raise LauncherRejected("bad-setting", "id")
        sid = setting["id"]
        if sid in known:
            raise LauncherRejected("duplicate-id", sid)
        if setting.get("type") not in LAUNCHER_SETTING_TYPES or not _launcher_text(setting.get("label"), 80):
            raise LauncherRejected("bad-setting", sid)
        if setting["type"] == "choice":
            choices = setting.get("choices")
            if not isinstance(choices, list) or not choices or any(
                    not isinstance(c, dict) or not isinstance(c.get("value"), str) or not _launcher_text(c.get("label"), 80)
                    for c in choices) or len({c["value"] for c in choices}) != len(choices):
                raise LauncherRejected("bad-setting", sid)
        if setting["type"] == "port":
            low, high = setting.get("min", 1024), setting.get("max", 65535)
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (low, high)) or not 1 <= low <= high <= 65535:
                raise LauncherRejected("bad-setting", sid)
        if "default" in setting and not _launcher_value_ok(setting, setting["default"]):
            raise LauncherRejected("bad-setting", f"{sid}.default")
        known[sid] = setting
    actions = entry.get("actions")
    if not isinstance(actions, list) or not actions:
        raise LauncherRejected("no-actions")
    seen: set[str] = set()
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not _LAUNCHER_ID.match(action["id"]):
            raise LauncherRejected("bad-action", "id")
        aid = action["id"]
        if aid in seen:
            raise LauncherRejected("duplicate-id", aid)
        seen.add(aid)
        if not _launcher_text(action.get("label"), 80) or action.get("output", "text") not in ("text", "status"):
            raise LauncherRejected("bad-action", aid)
        if action.get("confirm") is not None and not _launcher_text(action.get("confirm")):
            raise LauncherRejected("bad-action", f"{aid}.confirm")
        for flag in ("privileged", "detached"):
            if flag in action and not isinstance(action[flag], bool):
                raise LauncherRejected("bad-action", f"{aid}.{flag}")
        timeout = action.get("timeoutSeconds", 600)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
            raise LauncherRejected("bad-action", f"{aid}.timeoutSeconds")
        argv = action.get("argv")
        if not isinstance(argv, list) or len(argv) < 2 or argv[0] != LAUNCHER_PYTHON \
                or not isinstance(argv[1], str) or not _LAUNCHER_SCRIPT.match(argv[1]):
            raise LauncherRejected("bad-argv", aid)
        for arg in argv[1:] + list(action.get("dryRun", [])):
            if not isinstance(arg, str) or not _LAUNCHER_ARG.match(arg):
                raise LauncherRejected("bad-argv", aid)
            if "{" in arg or "}" in arg:
                raise LauncherRejected("bad-placeholder", aid)
        if not isinstance(action.get("dryRun", []), list):
            raise LauncherRejected("bad-argv", f"{aid}.dryRun")
        options = action.get("options", [])
        if not isinstance(options, list):
            raise LauncherRejected("bad-action", f"{aid}.options")
        for option in options:
            if not isinstance(option, dict) or option.get("setting") not in known:
                raise LauncherRejected("unknown-setting", f"{aid}: {option.get('setting') if isinstance(option, dict) else option}")
            setting = known[option["setting"]]
            parts = option.get("argv")
            if not isinstance(parts, list) or not parts:
                raise LauncherRejected("bad-argv", f"{aid}.{setting['id']}")
            for part in parts:
                if not isinstance(part, str) or not _LAUNCHER_ARG.match(part):
                    raise LauncherRejected("bad-argv", f"{aid}.{setting['id']}")
                if part != LAUNCHER_VALUE and ("{" in part or "}" in part):
                    raise LauncherRejected("bad-placeholder", aid)
            uses_value = LAUNCHER_VALUE in parts
            if uses_value == (setting["type"] == "bool"):
                raise LauncherRejected("bad-placeholder", f"{aid}.{setting['id']}")
    status = next((a for a in actions if a["id"] == "status"), None)
    if status is None or status.get("output") != "status" or status.get("privileged") or status.get("confirm"):
        raise LauncherRejected("no-status")
    if any(a.get("output") == "status" for a in actions if a["id"] != "status"):
        raise LauncherRejected("bad-action", "output=status только у status")
    profiles = entry.get("profiles", [])
    if not isinstance(profiles, list):
        raise LauncherRejected("bad-profile")
    pids: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("id"), str) or not _LAUNCHER_ID.match(profile["id"]) \
                or profile["id"] in pids or not _launcher_text(profile.get("label"), 80) \
                or not isinstance(profile.get("supported"), bool):
            raise LauncherRejected("bad-profile", str(profile.get("id") if isinstance(profile, dict) else profile))
        pids.add(profile["id"])
        if profile["supported"]:
            if profile.get("action") not in seen:
                raise LauncherRejected("bad-profile", f"{profile['id']}: action")
            for sid in profile.get("ask", []):
                if sid not in known:
                    raise LauncherRejected("bad-profile", f"{profile['id']}: ask {sid}")
            for sid, value in (profile.get("values") or {}).items():
                if sid not in known or not _launcher_value_ok(known[sid], value):
                    raise LauncherRejected("bad-profile", f"{profile['id']}: values.{sid}")
        elif not _launcher_text(profile.get("reason")):
            raise LauncherRejected("bad-profile", f"{profile['id']}: нужна reason")
    return entry


def launcher_values(entry: dict, values: dict | None) -> dict:
    """Значения настроек: умолчания объявления, поверх — выбор пользователя."""
    out = {}
    given = values or {}
    for setting in entry.get("settings", []):
        sid = setting["id"]
        value = given.get(sid, setting.get("default", False if setting["type"] == "bool" else None))
        if not _launcher_value_ok(setting, value):
            raise LauncherRejected("bad-value", sid)
        out[sid] = value
    unknown = sorted(set(given) - set(out))
    if unknown:
        raise LauncherRejected("bad-value", ", ".join(unknown))
    return out


def launcher_command(entry: dict, action_id: str, values: dict | None = None, dry_run: bool = False) -> dict:
    """Команда, которую лаунчер выполнит: argv без оболочки, каталог — каталог направления."""
    action = next((a for a in entry["actions"] if a["id"] == action_id), None)
    if action is None:
        raise LauncherRejected("unknown-action", action_id)
    if dry_run and not action.get("dryRun"):
        raise LauncherRejected("no-dry-run", action_id)
    chosen = launcher_values(entry, values)
    kinds = {s["id"]: s["type"] for s in entry.get("settings", [])}
    argv = list(action["argv"])
    for option in action.get("options", []):
        value = chosen[option["setting"]]
        if kinds[option["setting"]] == "bool":
            if value:
                argv += option["argv"]
        elif value is not None:
            argv += [str(value) if part == LAUNCHER_VALUE else part for part in option["argv"]]
    if dry_run:
        argv += action["dryRun"]
    return {"component": entry["component"], "action": action_id, "argv": argv, "cwd": entry["component"],
            "privileged": bool(action.get("privileged")), "detached": bool(action.get("detached")),
            "timeoutSeconds": action.get("timeoutSeconds", 600)}


def launcher_status(entry: dict, exit_code: int, stdout: str) -> dict:
    """Ответ команды status → состояние установки для лаунчера.

    state: absent (не установлено), installed (установлено, работает ли — неизвестно),
    running, stopped, broken (status упал или ответил не по контракту).
    """
    def broken(reason: str) -> dict:
        return {"protocol": LAUNCHER_STATUS, "state": "broken", "reason": reason, "version": None,
                "revision": None, "url": None, "values": {}, "detail": None, "problems": []}
    if exit_code != 0:
        return broken("exit-code")
    try:
        value = json.loads(stdout)
    except (TypeError, ValueError):
        return broken("bad-output")
    if not isinstance(value, dict) or value.get("schema") != LAUNCHER_STATUS or value.get("component") != entry["component"]:
        return broken("bad-output")
    installed, running = value.get("installed"), value.get("running")
    if not isinstance(installed, bool) or running not in (True, False, None):
        return broken("bad-output")
    revision, url, version = value.get("revision"), value.get("url"), value.get("version")
    if (revision is not None and not (isinstance(revision, str) and _HEX40.match(revision))) \
            or (url is not None and not (isinstance(url, str) and _LAUNCHER_URL.match(url))) \
            or (version is not None and not _launcher_text(version, 80)):
        return broken("bad-output")
    problems = value.get("problems", [])
    if not isinstance(problems, list) or not all(isinstance(p, str) for p in problems):
        return broken("bad-output")
    kinds = {s["id"]: s for s in entry.get("settings", [])}
    values = {k: v for k, v in (value.get("values") or {}).items() if k in kinds and _launcher_value_ok(kinds[k], v)} \
        if isinstance(value.get("values"), dict) else {}
    detail = value.get("detail") if isinstance(value.get("detail"), str) else None
    state = "absent" if not installed else {True: "running", False: "stopped", None: "installed"}[running]
    return {"protocol": LAUNCHER_STATUS, "state": state, "reason": None, "version": version if installed else None,
            "revision": revision if installed else None, "url": url if installed else None,
            "values": values, "detail": detail, "problems": problems[:20]}


# ---------------------------------------------------------------- генерация векторов

def _vectors():
    from contract_vectors import build  # noqa: WPS433 — рядом, только для генерации
    return build()


def main(argv: list[str]) -> int:
    if argv[1:2] != ["generate"]:
        print(__doc__)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    for rel, data in _vectors().items():
        path = CONTRACTS / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("записан", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
