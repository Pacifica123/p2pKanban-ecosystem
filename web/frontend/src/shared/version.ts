export const webClientVersion = __P2PKANBAN_WEB_VERSION__;

export type BuildPatch = { patchId: string; boardRevision: number | null };

/** The devctl patch this build came from (board/README.md «Номер патча в версии клиентов»). */
export const webBuildPatch: BuildPatch | null =
  typeof __P2PKANBAN_BUILD_PATCH__ === 'undefined' ? null : __P2PKANBAN_BUILD_PATCH__;

export function buildPatchLabel(patch: BuildPatch | null): string {
  if (!patch) return 'патч неизвестен';
  return patch.boardRevision ? `патч ${patch.boardRevision} · ${patch.patchId}` : `патч ${patch.patchId}`;
}
