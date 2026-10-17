// Candidates of the project board on the phone: the copy built into the APK,
// the last board saved from a node, and the node itself (contracts/project-board/1).
// The board never enters the replica, roaming or the keyring.
import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  ProjectBoardRejected,
  selectProjectBoard,
  summarizeProjectBoard,
  type ProjectBoardCandidate,
  type ProjectBoardSelection,
  type ProjectBoardSource,
  type ProjectBoardSummary,
} from './model';
import { buildRaw } from './buildCopy';

export { buildRaw };

export const PROJECT_BOARD_CACHE_KEY = '@p2pkanban/mobile/v1/project-board/cache';
const NODE_TIMEOUT_MS = 8_000;

export type NodeState = 'ok' | 'unreachable' | 'http-error' | 'no-node';

export interface LoadedProjectBoard {
  raw: string | null;
  selection: ProjectBoardSelection;
  node: { host: string | null; state: NodeState; sha256: string | null };
}

function candidate(source: ProjectBoardSource, raw: string): { entry: ProjectBoardCandidate; summary: ProjectBoardSummary | null } {
  try {
    const summary = summarizeProjectBoard(raw);
    return { entry: { source, summary }, summary };
  } catch (error) {
    const reason = error instanceof ProjectBoardRejected ? error.reason : 'not-json';
    return { entry: { source, rejected: reason }, summary: null };
  }
}

function hostOf(origin: string | null) {
  if (!origin) return null;
  return origin.replace(/^https?:\/\//, '').replace(/\/+$/, '');
}

async function readCache(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(PROJECT_BOARD_CACHE_KEY);
  } catch {
    return null;
  }
}

/** Build copy and saved copy only: instant, no network. */
export async function loadLocalProjectBoard(): Promise<LoadedProjectBoard> {
  return load(null, false);
}

/** Build copy, saved copy and the node; a newer node board is saved for the next offline start. */
export async function loadProjectBoard(nodeOrigin: string | null, fetchImpl: typeof fetch = fetch): Promise<LoadedProjectBoard> {
  return load(nodeOrigin, true, fetchImpl);
}

async function load(nodeOrigin: string | null, useNode: boolean, fetchImpl: typeof fetch = fetch): Promise<LoadedProjectBoard> {
  const raws = new Map<ProjectBoardSource, string>();
  const entries: ProjectBoardCandidate[] = [];

  const build = buildRaw();
  raws.set('build', build);
  const buildResult = candidate('build', build);
  entries.push(buildResult.entry);

  const cached = await readCache();
  let cacheSummary: ProjectBoardSummary | null = null;
  if (cached) {
    const result = candidate('cache', cached);
    cacheSummary = result.summary;
    entries.push(result.entry);
    if (result.summary) raws.set('cache', cached);
  }

  const node: LoadedProjectBoard['node'] = { host: hostOf(nodeOrigin), state: 'no-node', sha256: null };
  if (useNode && nodeOrigin) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), NODE_TIMEOUT_MS);
    try {
      const headers: Record<string, string> = {};
      if (cacheSummary) headers['If-None-Match'] = `"${cacheSummary.sha256}"`;
      const response = await fetchImpl(`${nodeOrigin.replace(/\/+$/, '')}/api/v1/project-board`, { headers, signal: controller.signal });
      if (response.status === 304 && cacheSummary && cached) {
        node.state = 'ok';
        node.sha256 = cacheSummary.sha256;
        entries.push({ source: 'node', summary: cacheSummary });
        raws.set('node', cached);
      } else if (response.ok) {
        const text = await response.text();
        const result = candidate('node', text);
        entries.push(result.entry);
        if (result.summary) {
          node.state = 'ok';
          node.sha256 = result.summary.sha256;
          raws.set('node', text);
          // Only a board newer than what the phone already has is worth keeping for mobile data.
          const known = Math.max(cacheSummary?.revision ?? 0, buildResult.summary?.revision ?? 0);
          if (result.summary.revision >= known && result.summary.sha256 !== cacheSummary?.sha256) {
            await AsyncStorage.setItem(PROJECT_BOARD_CACHE_KEY, text).catch(() => undefined);
          }
        } else {
          node.state = 'http-error';
        }
      } else {
        node.state = 'http-error';
        entries.push({ source: 'node', rejected: 'http-error' });
      }
    } catch {
      node.state = 'unreachable';
      entries.push({ source: 'node', rejected: 'unreachable' });
    } finally {
      clearTimeout(timer);
    }
  }

  const selection = selectProjectBoard(entries);
  return { raw: selection.chosen ? raws.get(selection.chosen) ?? null : null, selection, node };
}
