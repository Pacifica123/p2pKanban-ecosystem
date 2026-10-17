// The devctl patch this package was built from (board/README.md «Номер патча в версии клиентов»).
// vite.config.mjs bakes it in at build time.
declare const __ABL_BUILD_PATCH__: { patchId: string; boardRevision: number | null } | null;

export type BuildPatch = { patchId: string; boardRevision: number | null };

export const ablBuildPatch: BuildPatch | null =
  typeof __ABL_BUILD_PATCH__ === 'undefined' ? null : __ABL_BUILD_PATCH__;

export function buildPatchLabel(patch: BuildPatch | null): string {
  if (!patch) return 'патч неизвестен';
  return patch.boardRevision ? `патч ${patch.boardRevision} · ${patch.patchId}` : `патч ${patch.patchId}`;
}
