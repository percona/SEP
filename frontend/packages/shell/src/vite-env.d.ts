/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PMM_URL?: string;
  readonly VITE_CASDOOR_USER_PROFILE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
