"""Эталонные векторы общих контрактов: кольцо устройств и отчёт об ошибке.

Вызывается из `contract_ref.py generate` и из `check_contracts.py`, который
пересобирает векторы в памяти и сравнивает с файлами в `contracts/`. Всё
детерминировано: одинаковый вход даёт байт-в-байт одинаковые файлы.

Ключи здесь тестовые и публичные. Ни одно настоящее устройство не должно ими
пользоваться.
"""
from __future__ import annotations

import contract_ref as c

T0 = 1791244800  # 2026-10-06T00:00:00Z
RELAYS = {"urls": ["wss://relay-a.example", "wss://relay-b.example", "wss://relay-c.example"], "minAcks": 2}
TEST_NOTE = "ТОЛЬКО ДЛЯ ТЕСТОВ: секреты опубликованы, настоящие устройства их не используют."


def _sk(label: str) -> str:
    return c.sha256(f"p2p-kanban test key: {label}".encode()).hex()


KEYS = {
    "node": ("Домашний узел", "web"),
    "phone": ("Телефон", "android"),
    "laptop": ("Ноутбук", "arch"),
    "tablet": ("Планшет гостя", "android"),
    "intruder": ("Чужое устройство", "android"),
    "pc2": ("Рабочий ПК", "web"),
}
SK = {name: _sk(name) for name in KEYS}
PK = {name: c.public_key(sk) for name, sk in SK.items()}


def device(name: str, role: str = "admin") -> dict:
    title, kind = KEYS[name]
    return {"publicKey": PK[name], "name": title, "kind": kind, "role": role}


class Log:
    def __init__(self, nonce_label: str = "main"):
        self.clock = T0
        self.genesis = c.make_entry(SK["node"], {
            "type": "genesis", "parents": [], "nonce": c.b64url(c.sha256(nonce_label.encode())[:16]),
            "device": device("node"), "relays": RELAYS,
        }, self.tick())
        self.account = self.genesis["id"]
        self.entries = [self.genesis]

    def tick(self) -> int:
        self.clock += 60
        return self.clock

    def add(self, signer: str, parents: list[dict], body: dict) -> dict:
        full = {"accountId": self.account, "parents": sorted(p["id"] for p in parents), **body}
        entry = c.make_entry(SK[signer], full, self.tick())
        self.entries.append(entry)
        return entry


def _expected(entries: list[dict], account: str) -> dict:
    state = c.fold_ring(entries, account)
    return {k: state[k] for k in ("accountId", "accountTag", "members", "removed", "relays", "heads", "order", "rejected", "pending", "unknown", "readerOutdated")}


def _scenario(name: str, description: str, log: Log, entries: list[dict] | None = None) -> tuple[str, dict]:
    entries = log.entries if entries is None else entries
    return f"account-ring/1/vectors/ring-{name}.json", {
        "contract": c.RING,
        "description": description,
        "accountId": log.account,
        "entries": entries,
        "expected": _expected(entries, log.account),
    }


def ring_scenarios() -> dict:
    out = {}

    # 1. Обычная жизнь: узел, телефон по QR, ноутбук от телефона, переименование, смена relay.
    log = Log("linear")
    g = log.genesis
    a1 = log.add("node", [g], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    a2 = log.add("phone", [a1], {"type": "add", "device": device("laptop"), "via": "rendezvous"})
    a3 = log.add("laptop", [a2], {"type": "rename", "publicKey": PK["laptop"], "name": "Ноутбук в поездке"})
    log.add("node", [a3], {"type": "relays", "relays": {**RELAYS, "urls": RELAYS["urls"] + ["wss://relay-d.example"]}})
    out.update([_scenario("linear", "Узел создаёт кольцо, добавляет телефон; телефон добавляет ноутбук; ноутбук переименовывает себя; узел расширяет набор relay.", log)])

    # 2. Параллельные добавления с разных устройств сливаются как множество.
    log = Log("concurrent")
    g = log.genesis
    a1 = log.add("node", [g], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    b1 = log.add("node", [a1], {"type": "add", "device": device("laptop"), "via": "rendezvous"})
    b2 = log.add("phone", [a1], {"type": "add", "device": device("tablet", "member"), "via": "rendezvous"})
    log.add("laptop", [b1, b2], {"type": "rename", "publicKey": PK["tablet"], "name": "Планшет (гость)"})
    out.update([_scenario("concurrent-add", "Узел добавляет ноутбук, а телефон в это же время планшет-участник; ноутбук видит обе ветки и сливает их.", log)])

    # 3. Украденный телефон: удаление замораживает то, что телефон сделал «за спиной» узла.
    log = Log("stolen-phone")
    g = log.genesis
    a1 = log.add("node", [g], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    a2 = log.add("node", [a1], {"type": "add", "device": device("laptop"), "via": "rendezvous"})
    x1 = log.add("phone", [a1], {"type": "add", "device": device("intruder"), "via": "rendezvous"})
    log.add("intruder", [x1], {"type": "relays", "relays": {"urls": ["wss://evil.example"], "minAcks": 1}})
    log.add("node", [a2], {"type": "remove", "publicKey": PK["phone"], "reason": "lost"})
    out.update([_scenario("stolen-phone", "Телефон украден. Узел удаляет его, не видя, что телефон успел добавить чужое устройство. Чужое устройство не становится участником, его смена relay отклоняется каскадом.", log)])

    # 4. Удаление после того, как удаляющий видел добавление: добавленное остаётся.
    log = Log("seen-before-remove")
    g = log.genesis
    a1 = log.add("node", [g], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    a2 = log.add("phone", [a1], {"type": "add", "device": device("laptop"), "via": "rendezvous"})
    log.add("node", [a2], {"type": "remove", "publicKey": PK["phone"], "reason": "replaced"})
    out.update([_scenario("remove-after-seen-add", "Телефон добавил ноутбук, узел это видел и потом удалил телефон. Ноутбук остаётся в кольце.", log)])

    # 5. Взаимное удаление: оба удаления действуют.
    log = Log("mutual")
    g = log.genesis
    a1 = log.add("node", [g], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    a2 = log.add("node", [a1], {"type": "add", "device": device("laptop"), "via": "rendezvous"})
    log.add("node", [a2], {"type": "remove", "publicKey": PK["phone"], "reason": "other"})
    log.add("phone", [a2], {"type": "remove", "publicKey": PK["node"], "reason": "other"})
    out.update([_scenario("mutual-remove", "Узел и телефон одновременно удаляют друг друга. Удаление консервативно: оба выходят, кольцо продолжает ноутбук.", log)])

    # 6. Запись от более новой версии: сохраняется, но читатель помечен устаревшим.
    log = Log("newer-writer")
    g = log.genesis
    a1 = log.add("node", [g], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    a2 = log.add("node", [a1], {"type": "role", "publicKey": PK["phone"], "role": "member", "futureField": {"x": 1}})
    log.add("phone", [a2], {"type": "rename", "publicKey": PK["phone"], "name": "Телефон 2", "comment": "неизвестное поле игнорируется"})
    out.update([_scenario("newer-writer", "Узел более новой версии пишет запись неизвестного типа «role». Старый читатель хранит её, не применяет и сообщает, что устарел.", log)])

    # 7. Ошибки: каждая запись отклоняется со своей причиной.
    log = Log("rejections")
    g = log.genesis
    a1 = log.add("node", [g], {"type": "add", "device": device("tablet", "member"), "via": "rendezvous"})
    log.add("tablet", [a1], {"type": "add", "device": device("intruder"), "via": "rendezvous"})
    log.add("node", [a1], {"type": "remove", "publicKey": PK["node"], "reason": "left"})
    r1 = log.add("node", [a1], {"type": "remove", "publicKey": PK["tablet"], "reason": "other"})
    log.add("node", [r1], {"type": "add", "device": device("tablet"), "via": "rendezvous"})
    log.add("node", [r1], {"type": "add", "device": device("laptop"), "via": "teleport"})
    forged = c.make_entry(SK["intruder"], {"accountId": log.account, "parents": [r1["id"]], "type": "add", "device": device("pc2"), "via": "rendezvous"}, log.tick())
    forged = {**forged, "pubkey": PK["node"]}
    orphan = c.make_entry(SK["node"], {"accountId": log.account, "parents": ["f" * 64], "type": "rename", "publicKey": PK["node"], "name": "Сирота"}, log.tick())
    child = c.make_entry(SK["node"], {"accountId": log.account, "parents": [orphan["id"]], "type": "rename", "publicKey": PK["node"], "name": "Ребёнок сироты"}, log.tick())
    other = Log("other-account")
    stray = c.make_entry(SK["node"], {"accountId": other.account, "parents": [other.account], "type": "rename", "publicKey": PK["node"], "name": "Не наш аккаунт"}, log.tick())
    future = c.make_entry(SK["node"], {"protocol": "p2p-kanban-account-ring/2", "accountId": log.account, "parents": [r1["id"]], "type": "add"}, log.tick())
    entries = log.entries + [forged, orphan, child, stray, future]
    out.update([_scenario("rejections", "Набор нарушений: участник без прав admin добавляет устройство, последний admin удаляет себя, повторное добавление удалённого ключа, неизвестный способ добавления, поддельная подпись, неизвестный предок, чужой аккаунт, запись протокола /2.", log, entries)])
    return out


def sealed_vectors() -> dict:
    log = Log("linear")
    g = log.genesis
    a1 = log.add("node", [g], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    a2 = log.add("phone", [a1], {"type": "add", "device": device("laptop"), "via": "rendezvous"})
    members = [PK["node"], PK["phone"], PK["laptop"]]
    plaintext = {"protocol": c.RING, "accountId": log.account, "entries": log.entries}
    event = c.sealed_event(SK["phone"], "ring-log", log.account, members, plaintext, T0 + 3600, b"sealed-ring-log")

    presence = {
        "protocol": c.RING, "type": "presence", "accountId": log.account, "publicKey": PK["laptop"],
        "seenAt": T0 + 7200,
        "software": {"direction": "abl", "version": "A20", "protocols": [c.RING, c.KEYRING, c.RENDEZVOUS, c.ROAMING]},
        "ringHeads": [a2["id"]],
        "keyring": {"digest": c.sha256(b"keyring-example").hex(), "items": 4, "boards": 3},
        "relays": [{"url": u, "reachable": u != "wss://relay-c.example"} for u in RELAYS["urls"]],
        "boards": [{"boardId": "01a10d38-f902-7665-8612-3e74278ceafa", "keyEpoch": 2, "baseline": True}],
    }
    presence_event = c.sealed_event(SK["laptop"], "presence", log.account, members, presence, T0 + 7200, b"sealed-presence")

    old_phone = {
        "protocol": c.RING, "type": "presence", "accountId": log.account, "publicKey": PK["phone"],
        "seenAt": T0 + 5400,
        "software": {"direction": "mobile", "version": "2.2.0", "protocols": [c.RING, c.ROAMING]},
        "ringHeads": [a1["id"]],
        "keyring": None,
        "relays": [{"url": u, "reachable": True} for u in RELAYS["urls"][:2]],
    }
    old_event = c.sealed_event(SK["phone"], "presence", log.account, members, old_phone, T0 + 5400, b"sealed-presence-old")
    return {
        "account-ring/1/vectors/sealed-ring-log.json": {
            "contract": c.RING,
            "description": "Телефон публикует свою копию журнала кольца на relay, запечатанную для трёх участников. Любой из них открывает её своим секретом.",
            "note": TEST_NOTE,
            "recipient": {"name": "laptop", "secretKey": SK["laptop"], "publicKey": PK["laptop"]},
            "outsider": {"name": "intruder", "secretKey": SK["intruder"], "publicKey": PK["intruder"]},
            "accountTag": c.account_tag(log.account),
            "event": event,
            "expectedPlaintext": plaintext,
        },
        "account-ring/1/vectors/presence.json": {
            "contract": c.RING,
            "description": "Отметки присутствия: ноутбук на свежей версии и телефон, который отстаёт (не знает keyring/1). Экран кольца показывает отставание, а не молчит о нём.",
            "note": TEST_NOTE,
            "recipient": {"name": "node", "secretKey": SK["node"], "publicKey": PK["node"]},
            "accountTag": c.account_tag(log.account),
            "events": [presence_event, old_event],
            "expectedPlaintexts": [presence, old_phone],
            "ringHeads": [a2["id"]],
            "expectedSkew": c.presence_skew([presence, old_phone], [a2["id"]]),
        },
    }


def keyring_vectors() -> dict:
    log = Log("linear")
    space = "01a11100-0000-7000-8000-000000000001"
    empty_space = "01a11100-0000-7000-8000-000000000002"
    board_a = "01a11100-0000-7000-8000-0000000000a1"
    board_b = "01a11100-0000-7000-8000-0000000000b2"
    board_c = "01a11100-0000-7000-8000-0000000000c3"

    def key(label: str) -> str:
        return c.b64url(c.sha256(f"board key {label}".encode()))

    def board(bid, name, epoch, rev, by, label, sp=space, **extra):
        return {"kind": "board", "id": bid, "spaceId": sp, "name": name, "rev": rev, "updatedBy": PK[by], "deleted": False,
                "roaming": {"protocol": c.ROAMING, "epoch": epoch, "boardKey": key(label)}, **extra}

    node_copy = {"protocol": c.KEYRING, "accountId": log.account, "ringHeads": [log.account], "items": [
        {"kind": "space", "id": space, "name": "Личное", "rev": 1, "updatedBy": PK["node"], "deleted": False},
        board(board_a, "Планы", 1, 3, "node", "a1"),
        board(board_b, "Ремонт", 2, 1, "node", "b2-rotated"),
        board(board_c, "Старая доска", 1, 1, "node", "c1"),
    ]}
    phone_copy = {"protocol": c.KEYRING, "accountId": log.account, "ringHeads": [log.account], "items": [
        {"kind": "space", "id": space, "name": "Личное", "rev": 1, "updatedBy": PK["node"], "deleted": False},
        {"kind": "space", "id": empty_space, "name": "Поездка", "rev": 1, "updatedBy": PK["phone"], "deleted": False},
        board(board_a, "Планы на октябрь", 1, 4, "phone", "a1"),
        board(board_b, "Ремонт", 1, 7, "phone", "b1"),
        {"kind": "board", "id": board_c, "spaceId": space, "name": "Старая доска", "rev": 2, "updatedBy": PK["phone"], "deleted": True},
        {"kind": "calendar", "id": "01a11100-0000-7000-8000-0000000000d4", "rev": 1, "updatedBy": PK["phone"], "deleted": False, "futureField": "из новой версии"},
    ]}
    merged = c.merge_keyrings([node_copy, phone_copy])
    sealed = c.sealed_event(SK["phone"], "keyring", log.account, [PK["node"], PK["phone"]],
                            {**phone_copy, "items": merged}, T0 + 4000, b"sealed-keyring")
    return {
        "keyring/1/vectors/merge.json": {
            "contract": c.KEYRING,
            "description": "Слияние копий связки узла и телефона: пустое пространство из поездки доходит, ротированный ключ (эпоха 2) побеждает больший rev старой эпохи, удаление доски необратимо и убирает ключ, элемент неизвестного вида переносится без изменений.",
            "copies": [node_copy, phone_copy],
            "expected": {"items": merged, "digest": c.keyring_digest(merged), "boards": sum(1 for i in merged if i["kind"] == "board" and not i["deleted"])},
        },
        "keyring/1/vectors/sealed-keyring.json": {
            "contract": c.KEYRING,
            "description": "Телефон публикует слитую связку, запечатанную для узла и себя.",
            "note": TEST_NOTE,
            "recipient": {"name": "node", "secretKey": SK["node"], "publicKey": PK["node"]},
            "accountTag": c.account_tag(log.account),
            "event": sealed,
            "expectedPlaintext": {**phone_copy, "items": merged},
        },
    }


def rendezvous_vectors() -> dict:
    out = {}

    # Режим invite: узел в кольце показывает QR, телефон сканирует и входит.
    log = Log("invite")
    secret = c.sha256(b"rendezvous secret invite")
    expires = T0 + 600
    qr = {"v": 1, "m": "invite", "k": PK["node"], "s": c.b64url(secret), "r": RELAYS["urls"], "n": "Домашний узел", "t": "web", "x": expires}
    sid = c.session_id(secret)
    hello = {"type": "hello", "sessionId": sid, "device": {k: v for k, v in device("phone").items() if k != "role"},
             "software": {"direction": "mobile", "version": "2.3.0", "protocols": [c.RING, c.KEYRING, c.RENDEZVOUS, c.ROAMING]},
             "ring": None}
    e_hello = c.rendezvous_event(SK["phone"], secret, hello, T0 + 30, expires, b"invite-hello")
    add = log.add("node", [log.genesis], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    keyring = {"protocol": c.KEYRING, "accountId": log.account, "ringHeads": [add["id"]], "items": [
        {"kind": "space", "id": "01a11100-0000-7000-8000-000000000001", "name": "Личное", "rev": 1, "updatedBy": PK["node"], "deleted": False}]}
    welcome = {"type": "welcome", "sessionId": sid, "accountId": log.account, "entries": log.entries, "keyring": keyring}
    e_welcome = c.rendezvous_event(SK["node"], secret, welcome, T0 + 90, expires, b"invite-welcome")
    ack = {"type": "ack", "sessionId": sid, "accountId": log.account, "heads": [add["id"]]}
    e_ack = c.rendezvous_event(SK["phone"], secret, ack, T0 + 95, expires, b"invite-ack")
    out["rendezvous/1/vectors/invite-mode.json"] = {
        "contract": c.RENDEZVOUS,
        "description": "Режим «Войти в кольцо узла»: узел показывает QR, телефон сканирует, оба показывают один код подтверждения, человек подтверждает на узле, узел дописывает add и отдаёт журнал и связку.",
        "note": TEST_NOTE,
        "qrText": c.qr_encode(qr), "qr": qr,
        "derived": {"sessionId": sid, "sessionKey": c.session_key(secret).hex(), "confirmCode": c.confirm_code(sid, PK["phone"])},
        "roles": {"sponsor": PK["node"], "joiner": PK["phone"], "scanner": "joiner"},
        "events": [e_hello, e_welcome, e_ack],
        "expectedMessages": [hello, welcome, ack],
        "expectedRingAfter": _expected(log.entries, log.account),
    }

    # Режим join: новый ноутбук показывает QR, телефон из кольца сканирует и добавляет его.
    log = Log("join")
    phone_add = log.add("node", [log.genesis], {"type": "add", "device": device("phone"), "via": "rendezvous"})
    secret = c.sha256(b"rendezvous secret join")
    qr = {"v": 1, "m": "join", "k": PK["laptop"], "s": c.b64url(secret), "r": RELAYS["urls"][:2], "n": "Ноутбук", "t": "arch", "x": expires}
    sid = c.session_id(secret)
    hello = {"type": "hello", "sessionId": sid, "device": {k: v for k, v in device("laptop").items() if k != "role"},
             "software": {"direction": "abl", "version": "A20", "protocols": [c.RING, c.KEYRING, c.RENDEZVOUS, c.ROAMING]},
             "ring": {"accountId": None, "members": 1}}
    e_hello = c.rendezvous_event(SK["laptop"], secret, hello, T0 + 10, expires, b"join-hello")
    add = log.add("phone", [phone_add], {"type": "add", "device": device("laptop"), "via": "rendezvous"})
    keyring = {"protocol": c.KEYRING, "accountId": log.account, "ringHeads": [add["id"]], "items": []}
    welcome = {"type": "welcome", "sessionId": sid, "accountId": log.account, "entries": log.entries, "keyring": keyring}
    e_welcome = c.rendezvous_event(SK["phone"], secret, welcome, T0 + 70, expires, b"join-welcome")
    ack = {"type": "ack", "sessionId": sid, "accountId": log.account, "heads": [add["id"]]}
    e_ack = c.rendezvous_event(SK["laptop"], secret, ack, T0 + 75, expires, b"join-ack")
    out["rendezvous/1/vectors/join-mode.json"] = {
        "contract": c.RENDEZVOUS,
        "description": "Режим «Добавить узел в своё кольцо»: ноутбук показывает QR и заранее кладёт hello в почтовый ящик; телефон из кольца сканирует, видит имя и код, человек подтверждает на телефоне; ноутбук получает всё кольцо, включая устройства, которых он не видел.",
        "note": TEST_NOTE,
        "qrText": c.qr_encode(qr), "qr": qr,
        "derived": {"sessionId": sid, "sessionKey": c.session_key(secret).hex(), "confirmCode": c.confirm_code(sid, PK["laptop"])},
        "roles": {"sponsor": PK["phone"], "joiner": PK["laptop"], "scanner": "sponsor"},
        "events": [e_hello, e_welcome, e_ack],
        "expectedMessages": [hello, welcome, ack],
        "expectedRingAfter": _expected(log.entries, log.account),
    }

    # Отказ: у входящего уже своё кольцо с другими участниками — это слияние аккаунтов.
    other = Log("other-ring")
    secret = c.sha256(b"rendezvous secret merge")
    qr = {"v": 1, "m": "join", "k": PK["pc2"], "s": c.b64url(secret), "r": RELAYS["urls"], "n": "Рабочий ПК", "t": "web", "x": expires}
    sid = c.session_id(secret)
    hello = {"type": "hello", "sessionId": sid, "device": {k: v for k, v in device("pc2").items() if k != "role"},
             "software": {"direction": "web", "version": "2.3.0", "protocols": [c.RING, c.KEYRING, c.RENDEZVOUS, c.ROAMING]},
             "ring": {"accountId": other.account, "members": 3}}
    e_hello = c.rendezvous_event(SK["pc2"], secret, hello, T0 + 10, expires, b"merge-hello")
    refuse = {"type": "refuse", "sessionId": sid, "reason": "ring-merge-unsupported",
              "detail": "Рабочий ПК уже состоит в другом кольце из 3 устройств. Слияние колец пока не поддерживается."}
    e_refuse = c.rendezvous_event(SK["phone"], secret, refuse, T0 + 40, expires, b"merge-refuse")
    out["rendezvous/1/vectors/refuse-ring-merge.json"] = {
        "contract": c.RENDEZVOUS,
        "description": "Телефон сканирует QR рабочего ПК, который уже в другом кольце с другими участниками. Это слияние двух аккаунтов, а не добавление: встреча останавливается с объяснением.",
        "note": TEST_NOTE,
        "qrText": c.qr_encode(qr), "qr": qr,
        "derived": {"sessionId": sid, "sessionKey": c.session_key(secret).hex(), "confirmCode": c.confirm_code(sid, PK["pc2"])},
        "roles": {"sponsor": PK["phone"], "joiner": PK["pc2"], "scanner": "sponsor"},
        "events": [e_hello, e_refuse],
        "expectedMessages": [hello, refuse],
    }
    return out


def keys_vector() -> dict:
    return {"account-ring/1/vectors/keys.json": {
        "note": TEST_NOTE,
        "derivation": "secretKey = sha256(\"p2p-kanban test key: \" + name)",
        "keys": [{"name": n, "title": KEYS[n][0], "kind": KEYS[n][1], "secretKey": SK[n], "publicKey": PK[n]} for n in KEYS],
    }}


def error_report_vectors() -> dict:
    redact_cases = [
        ("bearer", "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"),
        ("json-body", '{"email":"john@example.com","password":"пароль с пробелом","accessToken":"abc.def","publicKey":"' + PK["phone"] + '"}'),
        ("escaped-json", 'payload="{\\"refreshToken\\":\\"r-123\\",\\"name\\":\\"Доска\\"}"'),
        ("url", "GET https://user:hunter2@relay.example/api?token=t-1&board=42&api_key=k9 failed"),
        ("nsec-jwt", "ключ nsec1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqsx3dfc и jwt eyJhbGciOiJFUzI1NiJ9.eyJleHAiOjF9.sig-part"),
        ("cookie", "Cookie: p2p_kanban_refresh=r3fr35h; theme=dark"),
        ("env-style", "NOSTR_SECRET_KEY=" + SK["intruder"] + "\nAPP__PORT=18080\nboard_key: \"b64key==\""),
        ("untouched", "vault secret service ready; device " + PK["laptop"] + "; токен истёк; secretKey не задан"),
        ("false-positive", "tokens: 3 of 5"),
        ("idempotent", 'password=[скрыто] "token":"[скрыто]" Authorization: Bearer [скрыто]'),
    ]
    redact = []
    for name, text in redact_cases:
        out_text, count = c.redact(text)
        redact.append({"name": name, "input": text, "expected": out_text, "redactions": count})
    truncate = [
        {"input": "Импорт остановлен", "limit": 8, "expected": c.truncate("Импорт остановлен", 8)},
        {"input": "ab🙂cd", "limit": 4, "expected": c.truncate("ab🙂cd", 4)},
        {"input": "ровно", "limit": 5, "expected": c.truncate("ровно", 5)},
    ]

    long_comment = "Комментарий длиннее ста двадцати восьми русских букв, который раньше ронял узел. " * 40
    raw_reports = [
        ("web-import-502", "web: «Создать копию» доски получила 502 от шлюза. Узел оборвал соединение, поэтому ни id ошибки, ни заголовка узла нет: это видно, а не скрыто.", {
            "reportId": "er-0000000000000001", "at": "2026-10-06T07:41:12.204Z",
            "software": {"direction": "web", "version": "2.1.0", "build": "8087da08253b", "commit": "520e41cf839e7c386bdd3f07288aa4e1c4fb4705"},
            "platform": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
            "screen": "Импорт доски", "operation": "Создать копию доски", "stage": "создание комментария 2/6",
            "message": "Импорт остановлен на шаге «создание комментария 2/6»: Request failed with 502",
            "error": {"kind": "http", "name": "ApiError", "detail": "Request failed with 502"},
            "http": {"method": "POST", "path": "/api/v1/cards/01a10d38-f920-7000-8000-000000000001/comments", "status": 502,
                     "requestId": None, "errorId": None,
                     "body": "<html>\r\n<head><title>502 Bad Gateway</title></head>\r\n<body>\r\n<center><h1>502 Bad Gateway</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n"},
            "peer": None,
            "logs": [
                "2026-10-06T07:41:11.950Z INFO import: доска «p2pKanban ecosystem», 53 карточки, 24 комментария",
                "2026-10-06T07:41:12.180Z INFO import: создание комментария 2/6 (" + str(len(long_comment.encode())) + " байт)",
                "2026-10-06T07:41:12.203Z WARN api: POST /api/v1/cards/…/comments → 502",
            ],
        }),
        ("web-node-500", "web: узел нового формата отвечает 500 с id ошибки и своей версией; строку журнала узла с тем же id можно найти командой bootstrap.py logs.", {
            "reportId": "er-0000000000000002", "at": "2026-10-07T09:15:00.000Z",
            "software": {"direction": "web", "version": "2.2.0", "build": "3f1c9a2b7d10", "commit": None},
            "platform": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
            "screen": "Сеть и устройства", "operation": "Кольцо устройств", "stage": None,
            "message": "Кольцо не загрузилось: Internal server error",
            "error": {"kind": "http", "name": "ApiError", "detail": "Internal server error"},
            "http": {"method": "GET", "path": "/api/v1/ring", "status": 500, "requestId": None,
                     "errorId": "01a11200-0000-7000-8000-00000000e500",
                     "body": '{"error":{"code":"internal_error","message":"Internal server error","details":null,"errorId":"01a11200-0000-7000-8000-00000000e500"}}'},
            "peer": {"direction": "web", "version": "2.2.0", "build": "3f1c9a2b7d10", "commit": None},
            "logs": ["2026-10-07T09:14:59.990Z INFO ring: запрос состояния кольца"],
        }),
        ("mobile-network", "mobile: старый телефон без сети к узлу. Токен в журнале и nsec в тексте ошибки вырезаны; узел известен по последнему ответу, и видно, что телефон отстаёт от узла.", {
            "reportId": "er-0000000000000003", "at": "2026-10-07T10:02:33.517Z",
            "software": {"direction": "mobile", "version": "2.1.0", "build": "24", "commit": None},
            "platform": "Android 14 (API 34)",
            "screen": "Доска", "operation": "Синхронизация", "stage": "получение событий relay",
            "message": "Не удалось связаться с узлом",
            "error": {"kind": "network", "name": "TypeError", "detail": "Network request failed\nimport key nsec1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqsx3dfc"},
            "http": {"method": "POST", "path": "/api/v1/sync/push?token=abc123", "status": 0, "requestId": None, "errorId": None, "body": None},
            "peer": {"direction": "web", "version": "2.2.0", "build": "3f1c9a2b7d10", "commit": "9d0c6e1b2a3f4c5d6e7f8091a2b3c4d5e6f70819"},
            "logs": ["2026-10-07T10:02:%02d.000Z DEBUG http: Authorization: Bearer tok-%d" % (i % 60, i) for i in range(60)],
        }),
        ("abl-native", "abl: ошибка нативной команды без HTTP. Коммит сборки неизвестен и так и написано; длинная деталь обрезана по буквам, а не по байтам.", {
            "reportId": "er-0000000000000004", "at": "2026-10-07T11:00:00.000Z",
            "software": {"direction": "abl", "version": "A18", "build": "0.1.0-1", "commit": None},
            "platform": "EndeavourOS · WebKitGTK 2.52.6",
            "screen": "Импорт доски", "operation": "import_portable_bundle", "stage": None,
            "message": "Не удалось импортировать доску",
            "error": {"kind": "native", "name": "ImportError", "detail": long_comment},
            "http": None, "peer": None, "logs": [],
        }),
    ]
    reports = []
    for name, description, raw in raw_reports:
        report = c.build_report(raw)
        text = c.render_report(report)
        if c.parse_report_text(text) != report:
            raise ValueError(f"{name}: текст не читается обратно")
        reports.append({"name": name, "description": description, "input": raw, "expectedReport": report, "expectedText": text})

    node = "2.2.0; build=3f1c9a2b7d10; commit=unknown"
    http_errors = [
        {"name": "internal-with-id", "status": 500,
         "headers": {c.ERROR_ID_HEADER: "01a11200-0000-7000-8000-00000000e500", c.NODE_HEADER: node},
         "body": {"error": {"code": "internal_error", "message": "Internal server error", "details": None, "errorId": "01a11200-0000-7000-8000-00000000e500"}},
         "expectedNode": c.parse_node_header(node)},
        {"name": "conflict-without-id", "status": 409,
         "headers": {c.NODE_HEADER: "2.2.0; build=3f1c9a2b7d10; commit=9d0c6e1b2a3f4c5d6e7f8091a2b3c4d5e6f70819"},
         "body": {"error": {"code": "conflict", "message": "Нет досок владельца для подключения", "details": None}},
         "expectedNode": c.parse_node_header("2.2.0; build=3f1c9a2b7d10; commit=9d0c6e1b2a3f4c5d6e7f8091a2b3c4d5e6f70819")},
        {"name": "old-node-no-headers", "status": 500, "headers": {},
         "body": {"error": {"code": "internal_error", "message": "Internal server error", "details": None}},
         "expectedNode": None},
    ]
    return {
        "error-report/1/vectors/redact.json": {
            "contract": c.ERROR_REPORT,
            "description": "Вырезание секретов из строк отчёта и обрезка по кодовым точкам. Публичные ключи, русский текст и уже вырезанное не трогаются.",
            "note": TEST_NOTE,
            "cases": redact,
            "truncate": truncate,
        },
        "error-report/1/vectors/reports.json": {
            "contract": c.ERROR_REPORT,
            "description": "Сырые отчёты четырёх ошибок, их нормализованный вид и текст кнопки «Скопировать подробности» байт в байт.",
            "cases": reports,
        },
        "error-report/1/vectors/http-error.json": {
            "contract": c.ERROR_REPORT,
            "description": "Ответы web-узла с ошибкой: id ошибки в теле и заголовке для 5xx, заголовок версии узла на каждом ответе; у старого узла заголовков нет.",
            "cases": http_errors,
        },
    }


def build() -> dict:
    out = {}
    for part in (keys_vector, ring_scenarios, sealed_vectors, keyring_vectors, rendezvous_vectors, error_report_vectors):
        out.update(part())
    return out
