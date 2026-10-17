import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// contracts/error-report/1: «Скопировать подробности» names the exact build.
// P2PKANBAN_BUILD is optional (PKGBUILD does not set it yet); the commit comes from
// P2PKANBAN_SOURCE_REVISION or, in a git checkout, from HEAD.
function sourceRevision() {
  const fromEnv = (process.env.P2PKANBAN_SOURCE_REVISION || "").trim().toLowerCase();
  if (/^[0-9a-f]{40}$/.test(fromEnv)) return fromEnv;
  const git = spawnSync("git", ["rev-parse", "HEAD"], { encoding: "utf8", shell: false });
  const head = git.status === 0 ? git.stdout.trim().toLowerCase() : "";
  return /^[0-9a-f]{40}$/.test(head) ? head : null;
}
const build = (process.env.P2PKANBAN_BUILD || "").trim() || null;

// board/README.md «Номер патча в версии клиентов»: P2PKANBAN_PATCH_*, else
// BUILD_PATCH.json next to this file, else the nearest monorepo board above it.
// makepkg builds inside .uts-reports of the same checkout, so the board is found there too.
const PATCH_ID = /^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$/;
function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}
function normalizedPatch(patchId, revision) {
  const id = typeof patchId === "string" ? patchId.trim() : "";
  if (!PATCH_ID.test(id)) return null;
  const text = typeof revision === "string" ? revision.trim() : revision;
  const number = typeof text === "string" && /^\d+$/.test(text) ? Number(text) : text;
  return { patchId: id, boardRevision: Number.isInteger(number) && number >= 1 && number <= 1e9 ? number : null };
}
function buildPatch() {
  const explicit = normalizedPatch(process.env.P2PKANBAN_PATCH_ID, process.env.P2PKANBAN_PATCH_REVISION);
  if (explicit) return explicit;
  const here = dirname(fileURLToPath(import.meta.url));
  const recorded = readJson(join(here, "BUILD_PATCH.json"));
  const fromFile = recorded && normalizedPatch(recorded.patchId, recorded.boardRevision);
  if (fromFile) return fromFile;
  for (let dir = dirname(here); ; dir = dirname(dir)) {
    if (existsSync(join(dir, "ecosystem.json")) && existsSync(join(dir, "board", "board.json"))) {
      const origin = readJson(join(dir, "board", "board.json"))?.origin;
      return origin ? normalizedPatch(origin.lastPatchId, origin.boardRevision) : null;
    }
    if (dirname(dir) === dir) return null;
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __ABL_BUILD__: JSON.stringify(build),
    __ABL_SOURCE_REVISION__: JSON.stringify(sourceRevision()),
    __ABL_BUILD_PATCH__: JSON.stringify(buildPatch()),
  },
  clearScreen: false,
  build: {
    target: "es2022",
    sourcemap: false,
    emptyOutDir: true,
  },
});
