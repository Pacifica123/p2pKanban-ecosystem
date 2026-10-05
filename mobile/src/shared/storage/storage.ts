import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

import type {
  Board,
  NativeAuthSuccessResponse,
  Workspace,
} from '../types/api';

const ROOT = '@p2pkanban/mobile/v1';
const NODE_KEY = `${ROOT}/config/node-origin`;
const NODE_VERSION_PREFIX = `${ROOT}/config/backend-version/`;
const SESSION_PREFIX = `${ROOT}/session/`;
const SESSION_KEY = 'p2pkanban.mobile.native-session.v1';

export interface StoredNativeSession extends NativeAuthSuccessResponse {
  nodeOrigin: string;
  storedAt: string;
}

export async function loadNodeOrigin() {
  return AsyncStorage.getItem(NODE_KEY);
}

export async function saveNodeOrigin(origin: string) {
  await AsyncStorage.setItem(NODE_KEY, origin);
}

export async function forgetNodeOrigin() {
  await AsyncStorage.removeItem(NODE_KEY);
}

function backendVersionKey(origin: string) {
  return `${NODE_VERSION_PREFIX}${encodeURIComponent(origin)}`;
}

export async function loadKnownBackendVersion(origin: string) {
  return AsyncStorage.getItem(backendVersionKey(origin));
}

export async function saveKnownBackendVersion(origin: string, version: string) {
  await AsyncStorage.setItem(backendVersionKey(origin), version);
}

export async function loadStoredSession() {
  const raw = await SecureStore.getItemAsync(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredNativeSession;
  } catch {
    await SecureStore.deleteItemAsync(SESSION_KEY);
    return null;
  }
}

export async function saveStoredSession(nodeOrigin: string, response: NativeAuthSuccessResponse) {
  const value: StoredNativeSession = {
    ...response,
    nodeOrigin,
    storedAt: new Date().toISOString(),
  };
  await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(value));
  return value;
}

export async function clearStoredSession() {
  await SecureStore.deleteItemAsync(SESSION_KEY);
}

export function sessionStorageKey(suffix: string) {
  return `${SESSION_PREFIX}${suffix}`;
}

export async function readSessionJson<T>(suffix: string, fallback: T): Promise<T> {
  const raw = await AsyncStorage.getItem(sessionStorageKey(suffix));
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export async function writeSessionJson<T>(suffix: string, value: T) {
  await AsyncStorage.setItem(sessionStorageKey(suffix), JSON.stringify(value));
}

export async function removeSessionValue(suffix: string) {
  await AsyncStorage.removeItem(sessionStorageKey(suffix));
}

export async function clearSessionBoundStorage() {
  const keys = await AsyncStorage.getAllKeys();
  const sessionKeys = keys.filter((key) => key.startsWith(SESSION_PREFIX));
  if (sessionKeys.length) await AsyncStorage.multiRemove(sessionKeys);
  await clearStoredSession();
}

export async function loadCachedWorkspaces() {
  return readSessionJson<Workspace[]>('workspaces', []);
}

export async function saveCachedWorkspaces(items: Workspace[]) {
  await writeSessionJson('workspaces', items);
}

export async function loadCachedBoards(workspaceId: string) {
  return readSessionJson<Board[]>(`boards/${workspaceId}`, []);
}

export async function saveCachedBoards(workspaceId: string, items: Board[]) {
  await writeSessionJson(`boards/${workspaceId}`, items);
}
