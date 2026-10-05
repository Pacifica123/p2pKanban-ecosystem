import { fetchFromRelays } from '../roaming/nostrRelay';
import { pullRoamingBoard } from '../roaming/service';
import { normalizeNodeOrigin, isPrivateNodeOrigin } from '../connection/connection';
import {
  finalizeEvent,
  getPublicKey,
  generateSecretKey,
  type Event,
} from 'nostr-tools/pure';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { apiRequest, isNetworkError } from '../../shared/api/client';
import {
  readSessionJson,
  loadCachedWorkspaces,
  sessionStorageKey,
  writeSessionJson,
} from '../../shared/storage/storage';
import {
  getOrCreateRoamingDeviceSecret,
  listRoamingCapabilities,
  loadRoamingApplyState,
  loadRoamingCapability,
} from '../roaming/storage';
import {
  loadBoardSnapshot,
  loadOperationQueue,
} from '../localFirst/repository';
import { overlayBoard } from './snapshot';
import {
  checkRequest,
  decryptPack,
  encryptPack,
  extendChain,
  LINK_PROTOCOL,
  RESPONSE_KIND,
  verifyChain,
} from './protocol';
const CACHE = 'device-link/prepared';
const secret = () => getOrCreateRoamingDeviceSecret(generateSecretKey);
export async function prepareDeviceLink(options: { refresh?: boolean } = {}) {
  const scope = sessionStorageKey(CACHE);
  if (!options.refresh) {
    const info = await preparationInfo().catch(() => null);
    if (info) return info.exportedAt;
  }
  const k = await secret();
  let response: Event;
  try { response = await apiRequest<Event>(
    '/auth/device-link/prepare',
    {
      method: 'POST',
      body: JSON.stringify({ authorPublicKey: getPublicKey(k) }),
    },
    { timeoutMs: 30000 },
  );
  } catch (error) {
    if (!isNetworkError(error)) throw error;
    const info = await preparationInfo().catch(() => null);
    throw new Error(info
      ? 'ПК недоступен: обновление не выполнено. Сохранённое разрешение действует; можно проверить запрос ноутбука и разрешить подключение.'
      : 'ПК недоступен и действующего разрешения нет. Получите его у доступного доверенного узла; мобильный интернет не делает LAN-адрес ПК доступным.');
  }
  const data = decryptPack(k, response);
  for (const c of Object.values(data.chains))
    verifyChain(c as Event[], getPublicKey(k));
  if (!Object.keys(data.chains).length) throw new Error('В разрешении нет досок.');
  if (scope !== sessionStorageKey(CACHE)) throw new Error('Сессия изменилась; повторите подготовку.');
  await writeSessionJson(CACHE, response);
  return data.snapshot.exportedAt as string;
}
export async function preparationInfo() {
  const cached = await readSessionJson<Event | null>(CACHE, null);
  if (!cached) return null;
  const k = await secret(),
    data = decryptPack(k, cached),
    grants = Object.values(data.chains).map((c) =>
      verifyChain(c as Event[], getPublicKey(k)),
    );
  if (!grants.length) return null;
  return {
    exportedAt: data.snapshot.exportedAt as string,
    boards: grants.length,
    expiresAt: Math.min(...grants.map((g) => g.grant.expiresAt)),
  };
}
export async function deviceFingerprint() {
  return getPublicKey(await secret());
}
export async function approveDevice(raw: string, userId: string, deliver?: (signed: Event) => Promise<void>) {
  if (raw.length > 10000) throw new Error('Слишком большой запрос.');
  const request = JSON.parse(raw) as Event,
    { recipient, id, expiresAt } = checkRequest(request),
    k = await secret();
  const saved = await readSessionJson<Event | null>(
    `device-link/issued/${id}`,
    null,
  );
  if (saved) return deliver ? deliver(saved) : shareApproval(saved);
  const cached = await readSessionJson<Event | null>(CACHE, null);
  if (!cached)
    throw new Error(
      'Сначала подготовьте подключение при доступном исходном узле.',
    );
  const data = decryptPack(k, cached);
  if (data.snapshot.user.id !== userId)
    throw new Error('Снимок принадлежит другому аккаунту.');
  // Capabilities may arrive through the relay after the original preparation.
  // Add them to this one-time approval so Android can admit a new peer while
  // the PC that created the board is offline.
  for (const capability of await listRoamingCapabilities()) {
    if (!capability.delegationChain?.length || data.chains[capability.boardId]) continue;
    let local = await loadBoardSnapshot(capability.boardId);
    if (!local) {
      try { local = (await pullRoamingBoard(capability, null)).snapshot; }
      catch { /* Missing board baseline: cannot honestly grant board data. */ }
    }
    if (!local || local.workspaceId !== capability.workspaceId) continue;
    const verified = verifyChain(capability.delegationChain, getPublicKey(k));
    if (verified.grant.boardId !== capability.boardId
      || verified.grant.workspaceId !== capability.workspaceId) continue;
    let workspace = data.snapshot.workspaces.find(
      (w: any) => w.bundle['manifest.json'].workspaceId === capability.workspaceId,
    );
    if (!workspace) {
      const metadata = (await loadCachedWorkspaces()).find(w => w.id === capability.workspaceId
        && w.ownerUserId === userId);
      const template = data.snapshot.workspaces[0];
      if (!metadata || !template) continue;
      const bundle = JSON.parse(JSON.stringify(template.bundle));
      bundle['manifest.json'].workspaceId = capability.workspaceId;
      bundle.scope.workspaceId = capability.workspaceId;
      for (const key of Object.keys(bundle.payload)) bundle.payload[key] = [];
      bundle.payload.workspaces = [{
        id:metadata.id,ownerUserId:userId,name:metadata.name,slug:null,
        description:metadata.description || null,visibility:metadata.visibility,
        createdAt:metadata.createdAt,updatedAt:metadata.updatedAt,
        archivedAt:metadata.archivedAt || null,
      }];
      workspace = {membershipRole:'owner',bundle};
      data.snapshot.workspaces.push(workspace);
    }
    data.chains[capability.boardId] = capability.delegationChain;
    if (!data.snapshot.boardCapabilities.some((item: any) => item.boardId === capability.boardId)) {
      data.snapshot.boardCapabilities.push({
        boardId: capability.boardId,
        boardTag: capability.boardTag,
        boardKey: capability.boardKey,
      });
    }
    overlayBoard(workspace.bundle.payload, local, new Set());
  }
  for (const [boardId, rawChain] of Object.entries(data.chains)) {
    const chain = rawChain as Event[],
      { grant } = verifyChain(chain, getPublicKey(k)),
      current = await loadRoamingCapability(boardId);
    if (
      current &&
      (current.capabilityEpoch !== grant.epoch || !current.canWrite)
    )
      throw new Error('Права изменились; обновите подготовку.');
    data.chains[boardId] = extendChain(k, chain, recipient);
    const local = await loadBoardSnapshot(boardId);
    if (!local) continue;
    const workspace = data.snapshot.workspaces.find(
      (w: any) => w.bundle['manifest.json'].workspaceId === grant.workspaceId,
    );
    if (!workspace) throw new Error('Scope снимка повреждён.');
    const state = await loadRoamingApplyState(boardId),
      operations = await loadOperationQueue();
    const deleted = new Set([
      ...Object.keys(state.tombstones),
      ...operations
        .filter((op) => op.boardId === boardId && op.kind === 'card.delete')
        .map((op) => op.entityId),
    ]);
    overlayBoard(workspace.bundle.payload, local, deleted);
    for (const cardId of deleted)
      if (!data.snapshot.cardTombstones.some((t: any) => t.cardId === cardId))
        data.snapshot.cardTombstones.push({
          workspaceId: grant.workspaceId,
          boardId,
          cardId,
          deletedAt: new Date().toISOString(),
        });
  }
  const response = finalizeEvent(
    {
      kind: RESPONSE_KIND,
      created_at: Math.floor(Date.now() / 1000),
      tags: [],
      content: JSON.stringify({
        protocol: LINK_PROTOCOL,
        recipient,
        requestId: id,
        expiresAt,
        parts: encryptPack(k, recipient, data),
      }),
    },
    k,
  );
  await writeSessionJson(`device-link/issued/${id}`, response);
  if (deliver) await deliver(response); else await shareApproval(response);
}
async function shareApproval(e: Event) {
  const f = new File(
    Paths.cache,
    `p2pkanban-pairing-${e.id.slice(0, 12)}.json`,
  );
  f.write(JSON.stringify(e));
  await Sharing.shareAsync(f.uri, {
    mimeType: 'application/json',
    dialogTitle: 'Передать зашифрованное разрешение ноутбуку',
  });
}

export async function probePreparedRelays() {
  const cached = await readSessionJson<Event | null>(CACHE, null);
  if (!cached) throw new Error('Нет подготовленного доступа. Получите его при доступном доверенном узле.');
  const data = decryptPack(await secret(), cached);
  const reports: string[] = [];
  for (const boardId of Object.keys(data.chains)) {
    const capability = await loadRoamingCapability(boardId);
    if (!capability) { reports.push(`${boardId}: нет локальной relay-capability; откройте список досок при доступном ПК.`); continue; }
    try {
      const result = await fetchFromRelays({ relays: capability.relays, kind: capability.eventKind, boardTag: capability.boardTag });
      reports.push(`${boardId}: ответили ${result.relayCount}/${capability.relays.length} relay; получено ${result.events.length} подписанных событий. Проверка чтения не подтверждает доставку изменений.`);
    } catch (error) { reports.push(`${boardId}: ${error instanceof Error ? error.message : String(error)}`); }
  }
  return reports.join('\n') || 'В разрешении нет досок.';
}

/** Android initiates the LAN connection; the phone never needs an HTTP server. */
export function nearbyWebOrigin(value: string) {
  const origin = normalizeNodeOrigin(value);
  if (!isPrivateNodeOrigin(origin) || !/^http:\/\/(?:\d{1,3}\.){3}\d{1,3}:\d+$/.test(origin))
    throw new Error('Укажите числовой IPv4:порт ноутбука в локальной сети.');
  return origin;
}
export async function fetchNearbyRequest(address: string): Promise<Event> {
  const origin = nearbyWebOrigin(address);
  const response = await fetch(`${origin}/api/v1/auth/device-link/lan/pending-request`);
  if (!response.ok) throw new Error('Ноутбук не отвечает. Откройте p2pKanban и «Ожидать ответ Android».');
  const json = await response.json() as {data:{request:Event|null}};
  if (!json.data?.request) throw new Error('На ноутбуке сначала нажмите «Ожидать ответ Android».');
  checkRequest(json.data.request);
  return json.data.request;
}
export async function approveNearbyDevice(raw: string, userId: string, address: string) {
  const origin = nearbyWebOrigin(address);
  await approveDevice(raw,userId,async signed => {
    const response = await fetch(`${origin}/api/v1/auth/device-link/lan/mobile-result`, {
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(signed),
    });
    if (!response.ok) throw new Error('Ноутбук отклонил разрешение. Повторите запрос до истечения 10 минут.');
  });
}
