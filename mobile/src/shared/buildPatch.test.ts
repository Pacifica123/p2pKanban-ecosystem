import { buildPatchLabel, mobileBuildPatch, parseBuildPatch } from './buildPatch';

describe('patch the APK was built from', () => {
  it('names the board revision and the patch id', () => {
    expect(buildPatchLabel(parseBuildPatch('2026-10-17-mobile-build-patch', '35'))).toBe('патч 35 · 2026-10-17-mobile-build-patch');
  });

  it('an id without a number, and no id at all, stay honest', () => {
    expect(buildPatchLabel(parseBuildPatch('2026-10-17-mobile-build-patch', undefined))).toBe('патч 2026-10-17-mobile-build-patch');
    expect(parseBuildPatch('../x', '35')).toBeNull();
    expect(buildPatchLabel(null)).toBe('патч неизвестен');
  });

  it('reads the values inlined at bundle time', () => {
    const saved = { id: process.env.EXPO_PUBLIC_PATCH_ID, revision: process.env.EXPO_PUBLIC_PATCH_REVISION };
    process.env.EXPO_PUBLIC_PATCH_ID = '2026-10-17-mobile-build-patch';
    process.env.EXPO_PUBLIC_PATCH_REVISION = '35';
    try {
      expect(mobileBuildPatch()).toEqual({ patchId: '2026-10-17-mobile-build-patch', boardRevision: 35 });
    } finally {
      if (saved.id === undefined) delete process.env.EXPO_PUBLIC_PATCH_ID; else process.env.EXPO_PUBLIC_PATCH_ID = saved.id;
      if (saved.revision === undefined) delete process.env.EXPO_PUBLIC_PATCH_REVISION; else process.env.EXPO_PUBLIC_PATCH_REVISION = saved.revision;
    }
  });
});
