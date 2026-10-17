// The devctl patch this APK was built from (board/README.md «Номер патча в версии клиентов»).
// scripts/build-apk.mjs or EAS (scripts/source-revision.mjs --env-file) inline EXPO_PUBLIC_PATCH_*.
export type BuildPatch = { patchId: string; boardRevision: number | null };

const PATCH_ID = /^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$/;

export function parseBuildPatch(patchId: string | undefined, revision: string | undefined): BuildPatch | null {
  const id = patchId?.trim() ?? '';
  if (!PATCH_ID.test(id)) return null;
  const number = revision && /^\d+$/.test(revision.trim()) ? Number(revision.trim()) : NaN;
  return { patchId: id, boardRevision: Number.isInteger(number) && number >= 1 ? number : null };
}

export function mobileBuildPatch(): BuildPatch | null {
  return parseBuildPatch(process.env.EXPO_PUBLIC_PATCH_ID, process.env.EXPO_PUBLIC_PATCH_REVISION);
}

export function buildPatchLabel(patch: BuildPatch | null): string {
  if (!patch) return 'патч неизвестен';
  return patch.boardRevision ? `патч ${patch.boardRevision} · ${patch.patchId}` : `патч ${patch.patchId}`;
}
