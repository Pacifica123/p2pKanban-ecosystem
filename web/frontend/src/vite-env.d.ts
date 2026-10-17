/// <reference types="vite/client" />

declare const __P2PKANBAN_WEB_VERSION__: string;
declare const __P2PKANBAN_BUILD_PATCH__: { patchId: string; boardRevision: number | null } | null;

interface ImportMetaEnv {
  readonly VITE_SOURCE_REVISION?: string;
  readonly VITE_BUILD_ID?: string;
}
