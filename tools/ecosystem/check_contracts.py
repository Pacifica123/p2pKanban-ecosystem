#!/usr/bin/env python3
"""Проверка общих контрактов в contracts/ (только стандартная библиотека).

    python -B tools/ecosystem/check_contracts.py

Что проверяется:

1. эталонная криптография совпадает с опубликованными векторами BIP-340 и NIP-44;
2. каждый контракт в contracts/compatibility.json имеет SPEC.md, schema/ и vectors/;
3. векторы проходят свои JSON Schema;
4. векторы проверяются заново: подписи, свёртка журнала, слияние связки,
   расшифровка конвертов и сообщений встречи, отставание версий;
5. векторы в репозитории байт-в-байт равны тому, что даёт
   tools/ecosystem/contract_vectors.py: правка руками без генератора видна сразу.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import contract_ref as c  # noqa: E402
import contract_vectors  # noqa: E402

ROOT = c.ROOT
CONTRACTS = c.CONTRACTS


class CheckError(Exception):
    pass


def fail(message: str) -> None:
    raise CheckError(message)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"{path.relative_to(ROOT)}: не читается как JSON UTF-8: {error}")


# ---------------------------------------------------------------- JSON Schema (подмножество)

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_SCHEMAS: dict[Path, dict] = {}


def _schema_file(path: Path) -> dict:
    path = path.resolve()
    if path not in _SCHEMAS:
        _SCHEMAS[path] = load(path)
    return _SCHEMAS[path]


def _resolve(ref: str, base: Path) -> tuple[dict, Path]:
    file_part, _, pointer = ref.partition("#")
    target = (base.parent / file_part).resolve() if file_part else base
    node = _schema_file(target)
    for token in [t for t in pointer.split("/") if t]:
        node = node[token]
    return node, target


def errors(value, schema: dict, base: Path, where: str = "$") -> list[str]:
    out: list[str] = []
    if "$ref" in schema:
        node, target = _resolve(schema["$ref"], base)
        out += errors(value, node, target, where)
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[k](value) for k in kinds):
            return out + [f"{where}: ожидается {'/'.join(kinds)}"]
    if "const" in schema and value != schema["const"]:
        out.append(f"{where}: ожидается {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: {value!r} не из {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{where}: не подходит под {schema['pattern']}")
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 1 << 30):
            out.append(f"{where}: длина {len(value)} вне границ")
    if _TYPES["number"](value):
        if value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")):
            out.append(f"{where}: {value} вне границ")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{where}: нет поля {key}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                out += errors(value[key], sub, base, f"{where}.{key}")
        extra = schema.get("additionalProperties", True)
        if extra is not True:
            for key in value:
                if key not in schema.get("properties", {}):
                    out += [f"{where}: лишнее поле {key}"] if extra is False else errors(value[key], extra, base, f"{where}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 1 << 30):
            out.append(f"{where}: элементов {len(value)} вне границ")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            out.append(f"{where}: элементы повторяются")
        if "items" in schema:
            for i, item in enumerate(value):
                out += errors(item, schema["items"], base, f"{where}[{i}]")
    for sub in schema.get("allOf", []):
        out += errors(value, sub, base, where)
    if "anyOf" in schema and all(errors(value, s, base, where) for s in schema["anyOf"]):
        out.append(f"{where}: не подходит ни под один вариант anyOf")
    if "oneOf" in schema and sum(not errors(value, s, base, where) for s in schema["oneOf"]) != 1:
        out.append(f"{where}: должен подходить ровно под один вариант oneOf")
    if "not" in schema and not errors(value, schema["not"], base, where):
        out.append(f"{where}: подходит под запрещённую схему")
    if "if" in schema:
        branch = "then" if not errors(value, schema["if"], base, where) else "else"
        if branch in schema:
            out += errors(value, schema[branch], base, where)
    return out


def require_schema(value, schema_rel: str, label: str) -> None:
    path = CONTRACTS / schema_rel.split("#")[0]
    schema = _schema_file(path)
    if "#" in schema_rel:
        schema, path = _resolve("#" + schema_rel.split("#", 1)[1], path)
    found = errors(value, schema, path.resolve())
    if found:
        fail(f"{label} не проходит {schema_rel}: " + "; ".join(found[:5]))


# ---------------------------------------------------------------- проверки

def check_crypto() -> None:
    # BIP-340, вектор 1 из bitcoin/bips bip-0340/test-vectors.csv
    sk = "B7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF"
    msg = bytes.fromhex("243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89")
    sig = "6896BD60EEAE296DB48A229FF71DFE071BDE413E6D43F917DC8DCF8C78DE33418906D11AC976ABCCB20B091292BFF4EA897EFCB639EA871CFA95F6DE339E4B0A"
    if c.public_key(sk).upper() != "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659":
        fail("BIP-340: неверный публичный ключ")
    if c.schnorr_sign(msg, sk, (1).to_bytes(32, "big")).hex().upper() != sig:
        fail("BIP-340: неверная подпись")
    if not c.schnorr_verify(msg, bytes.fromhex(c.public_key(sk)), bytes.fromhex(sig)):
        fail("BIP-340: подпись не проверяется")
    # NIP-44 v2, первый вектор encrypt_decrypt из paulmillr/nip44
    conv = c.nip44_conversation_key("0" * 63 + "1", c.public_key("0" * 63 + "2"))
    if conv.hex() != "c41c775356fd92eadc63ff5a0dc1da211b268cbea22316767095b2871ea1412d":
        fail("NIP-44: неверный conversation key")
    payload = "AgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABee0G5VSK0/9YypIObAtDKfYEAjD35uVkHyB0F4DwrcNaCXlCWZKaArsGrY6M9wnuTMxWfp1RTN9Xga8no+kF5Vsb"
    if c.nip44_encrypt(conv, "a", (1).to_bytes(32, "big")) != payload or c.nip44_decrypt(conv, payload) != "a":
        fail("NIP-44: шифрование расходится с эталоном")
    # XChaCha20-Poly1305: подмена одного байта должна ломать тег.
    key, nonce = bytes(range(32)), bytes(range(24))
    sealed = c.xchacha_seal(key, nonce, "кольцо".encode(), b"aad")
    if c.xchacha_open(key, nonce, sealed, b"aad").decode() != "кольцо":
        fail("XChaCha20-Poly1305: не расшифровывается")
    try:
        c.xchacha_open(key, nonce, sealed[:-1] + bytes([sealed[-1] ^ 1]), b"aad")
        fail("XChaCha20-Poly1305: подмена не обнаружена")
    except ValueError:
        pass


def check_layout() -> dict:
    compat = load(CONTRACTS / "compatibility.json")
    if compat.get("schemaVersion") != 1 or compat.get("updateOrder") != ["web", "mobile", "abl"]:
        fail("compatibility.json: ожидаются schemaVersion 1 и updateOrder web → mobile → abl")
    ids = set()
    for row in compat.get("contracts", []):
        cid = row.get("id")
        if not isinstance(cid, str) or not re.match(r"^p2p-kanban-[a-z0-9-]+/[1-9][0-9]*$", cid) or cid in ids:
            fail(f"compatibility.json: неверный или повторный id {cid!r}")
        ids.add(cid)
        directory = CONTRACTS / row.get("dir", "")
        for part in ("SPEC.md", "schema", "vectors"):
            if not (directory / part).exists():
                fail(f"{cid}: нет {row.get('dir')}/{part}")
        for need in row.get("requires", []):
            if need not in {r.get("id") for r in compat["contracts"]}:
                fail(f"{cid}: требует неизвестный контракт {need}")
        impl = row.get("implementations")
        if not isinstance(impl, dict) or set(impl) != {"web", "mobile", "abl"}:
            fail(f"{cid}: implementations должен перечислять web, mobile, abl")
        for direction, state in impl.items():
            if state is None:
                continue
            if not isinstance(state, dict) or not isinstance(state.get("since"), str) or not isinstance(state.get("hostAccepted"), bool):
                fail(f"{cid}: implementations.{direction} — null или {{since, stage, hostAccepted}}")
    for legacy in compat.get("legacy", []):
        if not isinstance(legacy.get("id"), str) or not isinstance(legacy.get("rule"), str):
            fail("compatibility.json: legacy — {id, rule}")
    return compat


def _event_schema(event: dict, label: str) -> None:
    schema = {27790: "account-ring/1/schema/entry.schema.json", 1991: "rendezvous/1/schema/envelope.schema.json"}.get(
        event.get("kind"), "account-ring/1/schema/sealed-event.schema.json")
    require_schema(event, schema, label)


def check_ring_vector(name: str, data: dict) -> None:
    for i, event in enumerate(data["entries"]):
        _event_schema(event, f"{name}: entries[{i}]")
    state = c.fold_ring(data["entries"], data["accountId"])
    rejected = {r["id"] for r in data["expected"]["rejected"]}
    for event in data["entries"]:
        if event["id"] in rejected or event["id"] in {p["id"] for p in data["expected"]["pending"]}:
            continue
        content = json.loads(event["content"])
        require_schema(content, "account-ring/1/schema/entry-content.schema.json", f"{name}: content {event['id'][:12]}")
    for key, expected in data["expected"].items():
        if state[key] != expected:
            fail(f"{name}: свёртка журнала расходится с ожиданием в поле {key}")
    # Порядок входа не важен.
    if c.fold_ring(list(reversed(data["entries"])), data["accountId"])["members"] != state["members"]:
        fail(f"{name}: результат зависит от порядка записей")


def check_sealed(name: str, data: dict) -> None:
    events = [data["event"]] if "event" in data else data["events"]
    plains = [data["expectedPlaintext"]] if "event" in data else data["expectedPlaintexts"]
    for event, expected in zip(events, plains):
        if c.verify_event(event):
            fail(f"{name}: подпись события не проходит")
        _event_schema(event, name)
        if ["d", data["accountTag"]] not in event["tags"]:
            fail(f"{name}: тег d не равен тегу аккаунта")
        sealed = json.loads(event["content"])
        require_schema(sealed, "account-ring/1/schema/sealed-record.schema.json", name)
        if event["kind"] != c.KIND_SEALED[sealed["type"]]:
            fail(f"{name}: kind не соответствует типу записи")
        got = c.unseal(data["recipient"]["secretKey"], event["pubkey"], data["accountTag"], sealed)
        if got != expected:
            fail(f"{name}: расшифровка расходится с ожиданием")
        schema = {"ring-log": "account-ring/1/schema/ring-log.schema.json", "presence": "account-ring/1/schema/presence.schema.json",
                  "keyring": "keyring/1/schema/keyring.schema.json"}[sealed["type"]]
        require_schema(got, schema, f"{name}: открытое содержимое")
        if sealed["type"] == "presence" and got["publicKey"] != event["pubkey"]:
            fail(f"{name}: отметку присутствия публикует не её устройство")
        if "outsider" in data:
            try:
                c.unseal(data["outsider"]["secretKey"], event["pubkey"], data["accountTag"], sealed)
                fail(f"{name}: посторонний открыл конверт")
            except ValueError:
                pass
    if "expectedSkew" in data and c.presence_skew(plains, data["ringHeads"]) != data["expectedSkew"]:
        fail(f"{name}: отставание версий считается иначе")


def check_keyring_merge(name: str, data: dict) -> None:
    for i, copy in enumerate(data["copies"]):
        require_schema(copy, "keyring/1/schema/keyring.schema.json", f"{name}: copies[{i}]")
    merged = c.merge_keyrings(data["copies"])
    if merged != data["expected"]["items"] or c.keyring_digest(merged) != data["expected"]["digest"]:
        fail(f"{name}: слияние связки расходится с ожиданием")
    if c.merge_keyrings(list(reversed(data["copies"]))) != merged:
        fail(f"{name}: слияние зависит от порядка копий")


def check_rendezvous(name: str, data: dict) -> None:
    require_schema(data["qr"], "rendezvous/1/schema/qr.schema.json", f"{name}: qr")
    if c.qr_decode(data["qrText"]) != data["qr"] or c.qr_encode(data["qr"]) != data["qrText"]:
        fail(f"{name}: текст QR не совпадает")
    secret = c.unb64url(data["qr"]["s"])
    derived = {"sessionId": c.session_id(secret), "sessionKey": c.session_key(secret).hex(),
               "confirmCode": c.confirm_code(c.session_id(secret), data["roles"]["joiner"])}
    if derived != data["derived"]:
        fail(f"{name}: производные встречи расходятся")
    k = data["qr"]["k"]
    shower = data["roles"]["sponsor"] if data["qr"]["m"] == "invite" else data["roles"]["joiner"]
    if k != shower:
        fail(f"{name}: ключ в QR не принадлежит показавшему устройству")
    for i, (event, expected) in enumerate(zip(data["events"], data["expectedMessages"])):
        if c.verify_event(event, c.KIND_RENDEZVOUS):
            fail(f"{name}: events[{i}] не проходит подпись")
        _event_schema(event, f"{name}: events[{i}]")
        require_schema(json.loads(event["content"]), "rendezvous/1/schema/envelope.schema.json#/$defs/content", f"{name}: events[{i}].content")
        message = c.rendezvous_open(event, secret)
        if message != expected:
            fail(f"{name}: events[{i}] расшифровывается иначе")
        require_schema(message, "rendezvous/1/schema/message.schema.json", f"{name}: сообщение {i}")
        sender = event["pubkey"]
        if message["type"] in ("hello", "ack") and sender != data["roles"]["joiner"]:
            fail(f"{name}: {message['type']} шлёт не входящее устройство")
        if message["type"] in ("welcome", "refuse") and sender != data["roles"]["sponsor"]:
            fail(f"{name}: {message['type']} шлёт не поручитель")
        if message["type"] == "hello" and message["device"]["publicKey"] != sender:
            fail(f"{name}: hello описывает чужой ключ")
        if message["type"] == "welcome":
            state = c.fold_ring(message["entries"], message["accountId"])
            if data["roles"]["joiner"] not in {m["publicKey"] for m in state["members"]}:
                fail(f"{name}: после welcome входящее устройство не в кольце")
            if message["keyring"]["ringHeads"] != state["heads"] or message["keyring"]["accountId"] != state["accountId"]:
                fail(f"{name}: связка в welcome не согласована с журналом (sponsor-stale)")
            if sender not in {m["publicKey"] for m in state["members"] if m["role"] == "admin"}:
                fail(f"{name}: welcome от устройства без прав admin")
            expected_ring = data.get("expectedRingAfter")
            if expected_ring and {key: state[key] for key in expected_ring} != expected_ring:
                fail(f"{name}: кольцо после встречи расходится с ожиданием")


def check_vectors() -> int:
    generated = contract_vectors.build()
    on_disk = {p.relative_to(CONTRACTS).as_posix() for p in CONTRACTS.glob("*/*/vectors/*.json")}
    if set(generated) != on_disk:
        fail(f"векторы: лишние или недостающие файлы: {sorted(set(generated) ^ on_disk)}")
    for rel, data in sorted(generated.items()):
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if (CONTRACTS / rel).read_text(encoding="utf-8") != text:
            fail(f"{rel}: не совпадает с генератором; запусти python -B tools/ecosystem/contract_ref.py generate")
        stored = load(CONTRACTS / rel)
        name = Path(rel).name
        if name.startswith("ring-"):
            check_ring_vector(rel, stored)
        elif name.startswith("sealed-") or name == "presence.json":
            check_sealed(rel, stored)
        elif name == "merge.json":
            check_keyring_merge(rel, stored)
        elif "qr" in stored:
            check_rendezvous(rel, stored)
        elif name == "keys.json":
            for key in stored["keys"]:
                if c.public_key(key["secretKey"]) != key["publicKey"]:
                    fail(f"{rel}: ключ {key['name']} не сходится")
        else:
            fail(f"{rel}: неизвестный вид вектора")
    return len(generated)


def main() -> int:
    try:
        check_crypto()
        compat = check_layout()
        count = check_vectors()
    except CheckError as error:
        print(f"contracts: ОШИБКА: {error}", file=sys.stderr)
        return 1
    print(f"contracts: OK: {len(compat['contracts'])} контракта, {count} векторов, криптография сходится с BIP-340 и NIP-44")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
