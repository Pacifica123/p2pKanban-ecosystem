import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { spawnSync } from "node:child_process";

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

export default defineConfig({
  plugins: [react()],
  define: {
    __ABL_BUILD__: JSON.stringify(build),
    __ABL_SOURCE_REVISION__: JSON.stringify(sourceRevision()),
  },
  clearScreen: false,
  build: {
    target: "es2022",
    sourcemap: false,
    emptyOutDir: true,
  },
});
