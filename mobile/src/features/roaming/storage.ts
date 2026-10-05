import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

import { sessionStorageKey } from '../../shared/storage/storage';
import {
  EMPTY_ROAMING_APPLY_STATE,
} from './merge';
import type {
  RoamingApplyState,
  RoamingCapability,
} from './types';

const CAPABILITY_INDEX_KEY = sessionStorageKey('roaming/capability-index');
const CAPABILITY_SECRET_PREFIX = 'p2pkanban.mobile.roaming-capability.v1';
const DEVICE_SECRET_KEY = 'p2pkanban.mobile.roaming-device-key.v1';
const CATALOG_CHANNEL_KEY = 'p2pkanban.mobile.roaming-catalog-channel.v1';
export interface RoamingCatalogChannel {
  relays: string[];
  eventKind: number;
  trustedPublishers: string[];
}

function metadataKey(boardId: string) {
  return sessionStorageKey(`roaming/capability/${boardId}`);
}

function applyStateKey(boardId: string) {
  return sessionStorageKey(`roaming/apply-state/${boardId}`);
}

async function writeRoamingCapability(capability: RoamingCapability) {
  const previous = await loadRoamingCapability(capability.boardId);
  if (previous && capability.capabilityEpoch < previous.capabilityEpoch) {
    throw new Error('Каталог содержит устаревшее поколение доступа к доске.');
  }
  if (previous && capability.capabilityEpoch === previous.capabilityEpoch
      && (capability.boardKey !== previous.boardKey || capability.boardTag !== previous.boardTag)) {
    throw new Error('Ключ доски изменился без нового поколения доступа.');
  }
  const previousChannel = await loadRoamingCatalogChannel();
  const channel: RoamingCatalogChannel = {
    relays: [...new Set([...(previousChannel?.relays || []), ...(capability.relays || [])])],
    eventKind: (capability.eventKind || 0) + 1,
    trustedPublishers: [...new Set([
      ...(previousChannel?.trustedPublishers || []),
      ...(capability.writerPublicKeys || []).map(key => key.toLowerCase()),
      ...(capability.delegationRoots || []).map(key => key.toLowerCase()),
    ])],
  };
  const { boardKey, ...metadata } = capability;
  const rawIndex = await AsyncStorage.getItem(CAPABILITY_INDEX_KEY);
  let boardIds: string[] = [];
  try {
    boardIds = rawIndex ? JSON.parse(rawIndex) : [];
  } catch {
    boardIds = [];
  }
  await Promise.all([
    SecureStore.setItemAsync(
      `${CAPABILITY_SECRET_PREFIX}.${capability.boardId}`,
      boardKey,
    ),
    AsyncStorage.setItem(metadataKey(capability.boardId), JSON.stringify(metadata)),
    AsyncStorage.setItem(
      CAPABILITY_INDEX_KEY,
      JSON.stringify([...new Set([...boardIds, capability.boardId])]),
    ),
    SecureStore.setItemAsync(CATALOG_CHANNEL_KEY, JSON.stringify(channel)),
  ]);
}

export async function loadRoamingCapability(boardId: string) {
  const [raw, boardKey] = await Promise.all([
    AsyncStorage.getItem(metadataKey(boardId)),
    SecureStore.getItemAsync(`${CAPABILITY_SECRET_PREFIX}.${boardId}`),
  ]);
  if (!raw || !boardKey) return null;
  try {
    const metadata = JSON.parse(raw) as Partial<RoamingCapability>;
    return {
      ...metadata,
      capabilityEpoch: metadata.capabilityEpoch || 1,
      canWrite: metadata.canWrite ?? true,
      writerPublicKeys: metadata.writerPublicKeys || [],
      boardKey,
    } as RoamingCapability;
  } catch {
    return null;
  }
}

export async function loadRoamingApplyState(boardId: string) {
  const raw = await AsyncStorage.getItem(applyStateKey(boardId));
  if (!raw) return EMPTY_ROAMING_APPLY_STATE;
  try {
    return { ...EMPTY_ROAMING_APPLY_STATE, ...JSON.parse(raw) } as RoamingApplyState;
  } catch {
    return EMPTY_ROAMING_APPLY_STATE;
  }
}

export async function resetRoamingApplyState(boardId: string) {
  await AsyncStorage.removeItem(applyStateKey(boardId));
}

export async function saveRoamingApplyState(boardId: string, state: RoamingApplyState) {
  await AsyncStorage.setItem(applyStateKey(boardId), JSON.stringify(state));
}

async function readOrCreateDeviceSecret(create: () => Uint8Array) {
  const current = await SecureStore.getItemAsync(DEVICE_SECRET_KEY);
  if (current) {
    const bytes = Uint8Array.from(current.match(/.{1,2}/g) || [], (pair) => Number.parseInt(pair, 16));
    if (bytes.length === 32) return bytes;
  }
  const created = create();
  const encoded = [...created].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  await SecureStore.setItemAsync(DEVICE_SECRET_KEY, encoded);
  return created;
}

let deviceSecretInFlight: Promise<Uint8Array> | null = null;
export function getOrCreateRoamingDeviceSecret(create: () => Uint8Array) {
  deviceSecretInFlight ??= readOrCreateDeviceSecret(create).finally(() => { deviceSecretInFlight = null; });
  return deviceSecretInFlight;
}
let capabilityWrites = Promise.resolve();
export function saveRoamingCapability(capability: RoamingCapability) {
  const run = capabilityWrites.then(() => writeRoamingCapability(capability));
  capabilityWrites = run.catch(() => undefined);
  return run;
}

export async function loadRoamingCatalogChannel(): Promise<RoamingCatalogChannel | null> {
  const raw = await SecureStore.getItemAsync(CATALOG_CHANNEL_KEY);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<RoamingCatalogChannel>;
    if (!Array.isArray(value.relays) || !Number.isInteger(value.eventKind)
      || !Array.isArray(value.trustedPublishers)) return null;
    return value as RoamingCatalogChannel;
  } catch { return null; }
}

export async function listRoamingCapabilities() {
  const raw = await AsyncStorage.getItem(CAPABILITY_INDEX_KEY);
  let ids: string[] = [];
  try { ids = raw ? JSON.parse(raw) : []; } catch { ids = []; }
  const values = await Promise.all(ids.map(loadRoamingCapability));
  return values.filter((value): value is RoamingCapability => Boolean(value));
}
