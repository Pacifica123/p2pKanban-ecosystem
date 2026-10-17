import { existsSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildPatchLabel, webBuildPatch } from '@/shared/version';

describe('build patch label', () => {
  it('names the board revision and the patch id', () => {
    expect(buildPatchLabel({ patchId: '2026-10-17-web-build-patch', boardRevision: 34 })).toBe('патч 34 · 2026-10-17-web-build-patch');
  });

  it('falls back to the id alone, then to «неизвестен»', () => {
    expect(buildPatchLabel({ patchId: '2026-10-17-web-build-patch', boardRevision: null })).toBe('патч 2026-10-17-web-build-patch');
    expect(buildPatchLabel(null)).toBe('патч неизвестен');
  });

  const inMonorepo = existsSync(path.resolve(__dirname, '../../../../../../ecosystem.json'));

  it.runIf(inMonorepo)('is baked in at build time from the monorepo board in a checkout', () => {
    expect(webBuildPatch?.patchId).toMatch(/^[0-9A-Za-z][0-9A-Za-z._-]*$/);
    expect(webBuildPatch?.boardRevision).toBeGreaterThan(0);
  });
});
