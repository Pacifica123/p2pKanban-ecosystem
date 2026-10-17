// The devctl patch the APK is built from (board/README.md «Номер патча в версии клиентов»).
// Expo inlines EXPO_PUBLIC_* into the JS bundle, so the APK keeps naming its own patch.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const PATCH_ID = /^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$/;

export function normalizedPatch(patchId, revision) {
  const id = typeof patchId === 'string' ? patchId.trim() : '';
  if (!PATCH_ID.test(id)) return null;
  const text = typeof revision === 'string' ? revision.trim() : revision;
  const number = typeof text === 'string' && /^\d+$/.test(text) ? Number(text) : text;
  return { patchId: id, boardRevision: Number.isInteger(number) && number >= 1 && number <= 1e9 ? number : null };
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

// Explicit variables, then BUILD_PATCH.json in mobile/, then the board right
// above mobile/ (EAS uploads the whole monorepo, so it is there too).
export function buildPatch(mobileRoot, env = process.env) {
  const explicit = normalizedPatch(env.EXPO_PUBLIC_PATCH_ID ?? env.P2PKANBAN_PATCH_ID,
    env.EXPO_PUBLIC_PATCH_REVISION ?? env.P2PKANBAN_PATCH_REVISION);
  if (explicit) return explicit;
  const recorded = readJson(join(mobileRoot, 'BUILD_PATCH.json'));
  const fromFile = recorded && normalizedPatch(recorded.patchId, recorded.boardRevision);
  if (fromFile) return fromFile;
  const root = dirname(mobileRoot);
  if (!existsSync(join(root, 'ecosystem.json'))) return null;
  const origin = readJson(join(root, 'board', 'board.json'))?.origin;
  return origin ? normalizedPatch(origin.lastPatchId, origin.boardRevision) : null;
}

export function patchEnvironment(patch) {
  return patch
    ? { EXPO_PUBLIC_PATCH_ID: patch.patchId, ...(patch.boardRevision ? { EXPO_PUBLIC_PATCH_REVISION: String(patch.boardRevision) } : {}) }
    : {};
}

export function patchLabel(patch) {
  if (!patch) return 'патч неизвестен';
  return patch.boardRevision ? `патч ${patch.boardRevision} · ${patch.patchId}` : `патч ${patch.patchId}`;
}
