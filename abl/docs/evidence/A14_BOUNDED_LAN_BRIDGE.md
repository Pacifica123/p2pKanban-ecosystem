# A14 — optional bounded LAN compatibility bridge

## Status

Implemented at source/deterministic-check level. Canonical frontend/Cargo/real-binary UTS is the acceptance gate.

## Decision boundary

A14 closes the remaining legacy LAN pairing/migration compatibility gap without restoring an always-on HTTP backend.

Normal p2pKanban Arch-native operation has **no TCP listener**. The bridge exists only after explicit user action and is constrained to a detected RFC1918/link-local IPv4 address, a random high port and a short TTL (30–600 seconds; UI default 300). Production never binds wildcard, public IPv4, IPv6 or loopback addresses. A loopback adapter exists only behind the dedicated UserTestSpace host-probe flag.

The only endpoint is `POST /v1/p2pkanban/pair`. It accepts one versioned encrypted `p2p-kanban-lan-bridge/1` envelope. The 256-bit one-time capability is used directly as the XChaCha20-Poly1305 key with fixed method/path AAD; it is not a cookie/Bearer/session credential. The listener closes after the first authenticated request whether destination provisioning succeeds or fails. Invalid unauthenticated attempts are capped.

## Identity / secret boundary

Starting the bridge creates a fresh native secp256k1/BIP340 device identity locally. Only the x-only public key is returned with the explicit pairing descriptor. The private key never crosses Tauri IPC or LAN transport and is consumed into the existing A11 `DeviceIdentityMaterial`/`SecretVault` path only after an authenticated provisioning capsule is received.

The peer capsule `p2p-kanban-lan-provision/1` carries the existing device-link/2 grant, portable bundle, board id and board capability. `devicePrivateKey`/`devicePublicKey` fields are rejected as unknown input. A durable vault is mandatory before the bridge may start; session-only secret storage fails closed.

## HTTP hardening

The compatibility listener is deliberately not a general REST server:

- exact HTTP/1.1 `POST` and exact path only;
- direct-IP Host must equal the selected bound socket;
- exact `application/json` and bounded `Content-Length` required;
- `Origin`, cookies, Authorization, Proxy-Authorization and transfer encoding rejected;
- headers/body/read time are bounded;
- max 8 attempts, max 8 MiB plaintext / 12 MiB envelope, max 8 KiB headers;
- no CORS, generic browser auth, files, shell, updates, planner CRUD or arbitrary routes;
- no mDNS/discovery and no firewall/polkit/systemd mutation.

WebView still has `connect-src 'none'` and zero generic Tauri permissions. It receives only typed start/status/stop/address commands and the explicit one-time pairing descriptor.

## Protocol compatibility

A14 introduces only the compatibility transport wrapper `p2p-kanban-lan-bridge/1` / `p2p-kanban-lan-provision/1`. Destination semantics remain A11 device-link/2 + portable-bundle semantics; A10 roaming and A12 parity protocols are unchanged.

`fixtures/protocol/lan-bridge-v1-golden.json` freezes the XChaCha20-Poly1305 envelope/AAD representation. Unknown transport versions fail closed. Future clients may implement this wrapper while old device-link/2 semantics remain the authenticated inner contract; no downgrade to unauthenticated legacy HTTP is allowed.

## Acceptance

Deterministic A14 checks cover off-by-default composition, bind/TTL/size/rate/header rules, local identity ownership, SecretVault requirement, golden vector/version rejection, typed UI boundary and absence of firewall/background-service behavior.

Canonical UTS adds:

- `cargo test ... a14_`;
- `tools/a14_host_lan_bridge_probe.py`, which uses the built binary, starts only the explicitly gated loopback test adapter, posts the pre-sealed authenticated envelope and proves one-shot auto-close;
- normal runtime launch/socket evidence remains A01/A13 plus manual `ss` observation for the production listener while explicitly started.

## Explicit non-claims

A14 is not relay orchestration, generic LAN sync, discovery, mDNS, a permanent node API, close-to-tray/background service, firewall automation or replacement for device-link/2. Physical Android/web legacy-client interop remains cross-client evidence; the native destination and bounded transport are what this stage implements.
