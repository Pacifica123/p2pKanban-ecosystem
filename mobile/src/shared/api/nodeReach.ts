// Whether a request to the node is worth sending (docs/architecture/stall-watch-20261020.md).
// A node that cannot answer must cost nothing: every request to it used to wait
// the full 12 s deadline, and the 2026-10-20 journal shows every JS-thread stall
// while several such requests were in flight. Two rules:
// 1. A node in a private network is not reachable from mobile data (a VPN shows
//    as network type `vpn`, not `cellular`): nothing is sent until the network changes.
// 2. A node that did not answer at all is not asked again for a cool-down;
//    the first request after it goes through and decides.

/** First pause after a node stayed silent. */
export const COOL_DOWN_MS = 30_000;
/** Longest pause between attempts while the node keeps silent. */
export const MAX_COOL_DOWN_MS = 120_000;

export function isPrivateNodeOrigin(origin: string | null) {
  if (!origin) return false;
  let hostname: string;
  try {
    hostname = new URL(origin).hostname.toLowerCase().replace(/^\[|\]$/g, '');
  } catch {
    return false;
  }
  if (hostname === 'localhost' || hostname.endsWith('.local')) return true;
  if (hostname === '::1' || hostname.startsWith('fc') || hostname.startsWith('fd')) return true;
  const octets = hostname.split('.').map(Number);
  if (octets.length !== 4 || octets.some((value) => !Number.isInteger(value))) return false;
  const [first = -1, second = -1] = octets;
  return first === 10
    || first === 127
    || (first === 172 && second >= 16 && second <= 31)
    || (first === 192 && second === 168)
    || (first === 169 && second === 254);
}

let networkType = 'unknown';
let silentSince = 0;
let silentUntil = 0;
let silentCount = 0;

/** NetworkProvider reports every change; a new network forgets the silence. */
export function setApiNetworkType(type: string) {
  if (type === networkType) return false;
  networkType = type;
  resetNodeReach();
  return true;
}

export function resetNodeReach() {
  silentSince = 0;
  silentUntil = 0;
  silentCount = 0;
}

export type NodeBlock = { reason: 'lan-from-cellular' | 'silent'; message: string; retryInMs: number };

/** Why a request to `origin` should fail right away, or null to send it. */
export function nodeBlock(origin: string, now = Date.now()): NodeBlock | null {
  if (networkType === 'cellular' && isPrivateNodeOrigin(origin)) {
    return {
      reason: 'lan-from-cellular',
      message: 'Узел в локальной сети, а телефон в мобильной: запрос не отправлен.',
      retryInMs: 0,
    };
  }
  if (now < silentUntil) {
    const retryInMs = silentUntil - now;
    return {
      reason: 'silent',
      message: `Узел не ответил ${Math.round((now - silentSince) / 1000)} с назад; следующая попытка через ${Math.ceil(retryInMs / 1000)} с.`,
      retryInMs,
    };
  }
  return null;
}

/** The node gave no answer at all (timeout or connection error). Returns a new pause, or 0. */
export function noteNodeSilent(now = Date.now()) {
  // Requests sent together fail together: one silence, not several.
  if (now < silentUntil) return 0;
  if (!silentCount) silentSince = now;
  silentCount += 1;
  const pause = Math.min(COOL_DOWN_MS * 2 ** (silentCount - 1), MAX_COOL_DOWN_MS);
  silentUntil = now + pause;
  return pause;
}

/** Any HTTP answer, even an error status, means the node is there. */
export function noteNodeAnswered() {
  const wasSilent = silentCount > 0;
  resetNodeReach();
  return wasSilent;
}
