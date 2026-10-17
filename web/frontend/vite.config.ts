import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { existsSync, readFileSync } from 'node:fs';

const packageVersion = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf8'),
) as { version: string };

// board/README.md «Номер патча в версии клиентов». The Docker build passes
// VITE_PATCH_*; a checkout reads the monorepo board right above web/.
const PATCH_ID = /^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$/;

function buildPatch(): { patchId: string; boardRevision: number | null } | null {
  const fromEnv = process.env.VITE_PATCH_ID?.trim();
  let patchId = fromEnv && fromEnv !== 'unknown' ? fromEnv : undefined;
  let revision: unknown = process.env.VITE_PATCH_REVISION?.trim();
  if (!patchId) {
    const root = path.resolve(__dirname, '..', '..');
    try {
      if (!existsSync(path.join(root, 'ecosystem.json'))) return null;
      const origin = JSON.parse(readFileSync(path.join(root, 'board', 'board.json'), 'utf8'))?.origin;
      patchId = typeof origin?.lastPatchId === 'string' ? origin.lastPatchId : undefined;
      revision = origin?.boardRevision;
    } catch {
      return null;
    }
  }
  if (!patchId || !PATCH_ID.test(patchId)) return null;
  const number = typeof revision === 'string' && /^\d+$/.test(revision) ? Number(revision) : revision;
  return { patchId, boardRevision: Number.isInteger(number) && (number as number) >= 1 ? (number as number) : null };
}

export default defineConfig({
  plugins: [react()],
  define: {
    __P2PKANBAN_WEB_VERSION__: JSON.stringify(packageVersion.version),
    __P2PKANBAN_BUILD_PATCH__: JSON.stringify(buildPatch()),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    include: ['src/test/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
});
