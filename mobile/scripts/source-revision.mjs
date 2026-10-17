// Monorepo commit for the APK (contracts/error-report/1: «коммит» in every report).
// Expo inlines EXPO_PUBLIC_* into the JS bundle at build time, so the commit
// travels inside the APK and the copied report names it.
import { spawnSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildPatch, patchEnvironment, patchLabel } from './build-patch.mjs';

const HEX = /^[0-9a-f]{40}$/;

export function sourceRevision(cwd, env = process.env) {
  for (const value of [env.EXPO_PUBLIC_SOURCE_REVISION, env.P2PKANBAN_SOURCE_REVISION, env.EAS_BUILD_GIT_COMMIT_HASH]) {
    const text = value?.trim().toLowerCase();
    if (text && HEX.test(text)) return text;
  }
  const git = spawnSync('git', ['rev-parse', 'HEAD'], { cwd, encoding: 'utf8', shell: false });
  const head = git.status === 0 ? git.stdout.trim().toLowerCase() : '';
  return HEX.test(head) ? head : null;
}

// `node scripts/source-revision.mjs --env-file`: for EAS (eas-build-post-install),
// where only files reach the bundler. .env.* is git-ignored.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const revision = sourceRevision(root);
  if (process.argv.includes('--env-file')) {
    const values = { ...(revision ? { EXPO_PUBLIC_SOURCE_REVISION: revision } : {}), ...patchEnvironment(buildPatch(root)) };
    const lines = Object.entries(values).map(([key, value]) => `${key}=${value}\n`);
    if (lines.length) writeFileSync(join(root, '.env.local'), lines.join(''));
    console.log(revision ? `.env.local: EXPO_PUBLIC_SOURCE_REVISION=${revision}` : 'коммит неизвестен');
    console.log(`.env.local: ${patchLabel(buildPatch(root))}`);
  } else {
    console.log(revision ?? 'unknown');
  }
}
