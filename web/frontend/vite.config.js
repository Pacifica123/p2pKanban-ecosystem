import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
var packageVersion = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));
// board/README.md «Номер патча в версии клиентов». The Docker build passes
// VITE_PATCH_*; a checkout reads the monorepo board right above web/.
var PATCH_ID = /^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$/;
function buildPatch() {
    var _a, _b, _c;
    var fromEnv = (_a = process.env.VITE_PATCH_ID) === null || _a === void 0 ? void 0 : _a.trim();
    var patchId = fromEnv && fromEnv !== 'unknown' ? fromEnv : undefined;
    var revision = (_b = process.env.VITE_PATCH_REVISION) === null || _b === void 0 ? void 0 : _b.trim();
    if (!patchId) {
        var root = path.resolve(__dirname, '..', '..');
        try {
            if (!existsSync(path.join(root, 'ecosystem.json')))
                return null;
            var origin_1 = (_c = JSON.parse(readFileSync(path.join(root, 'board', 'board.json'), 'utf8'))) === null || _c === void 0 ? void 0 : _c.origin;
            patchId = typeof (origin_1 === null || origin_1 === void 0 ? void 0 : origin_1.lastPatchId) === 'string' ? origin_1.lastPatchId : undefined;
            revision = origin_1 === null || origin_1 === void 0 ? void 0 : origin_1.boardRevision;
        }
        catch (_d) {
            return null;
        }
    }
    if (!patchId || !PATCH_ID.test(patchId))
        return null;
    var number = typeof revision === 'string' && /^\d+$/.test(revision) ? Number(revision) : revision;
    return { patchId: patchId, boardRevision: Number.isInteger(number) && number >= 1 ? number : null };
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
