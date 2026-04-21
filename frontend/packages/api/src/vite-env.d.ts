// Minimal ImportMeta declaration so @sep/api can read `import.meta.env.DEV`
// without depending on Vite directly. Consuming apps (e.g. @sep/shell) pull
// in the full `vite/client` types via their own vite-env.d.ts.
interface ImportMetaEnv {
  readonly DEV: boolean;
  readonly PROD: boolean;
  readonly MODE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
