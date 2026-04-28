# Storybook for `@sep/framework`

Storybook lives in `packages/framework/.storybook/` and hosts component stories
for the React migration. The instance is shared across the framework package;
shell-app stories are out of scope.

## Run locally

From the repo root (`frontend/`):

```sh
pnpm storybook        # dev server on http://localhost:6006
pnpm build-storybook  # static bundle in packages/framework/storybook-static/
```

Both scripts are passthroughs to `pnpm --filter @sep/framework <script>`.

## Layout

- `.storybook/main.ts` — Vite builder config; mirrors the shell's MUI/percona-ui
  dedupe + `optimizeDeps` so a single React/MUI instance is shared.
- `.storybook/preview.tsx` — global decorators: `QueryClientProvider`,
  percona-ui `ThemeContextProvider` (using `sepThemeOptions`), `MemoryRouter`,
  `CssBaseline`. Also installs the SSE/fetch mocks below and registers per-
  story scripts/responses from `parameters` before each story renders.
- `.storybook/sseMocks.ts` — replaces `globalThis.EventSource` with a
  scriptable stub and routes `fetch` through a registry. The install is
  HMR-safe (flag + original `fetch` live on `globalThis` via `Symbol.for(...)`).

## Mocking SSE / fetch in a story

Declare mock data on the story's `parameters` — the global decorator
registers it before the component mounts.

```tsx
export const Running: Story = {
  args: { taskHistoryId: 'sb-running', taskStatus: 'RUNNING' },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-running': (es) => {
        es.emitMessage({ msg: '…', step: 'setup', type: 'stdout', offset: 1 });
      },
    },
    fetchResponses: { '/execution-events/sb-running': [] },
  },
};
```

The registry is keyed by URL and registered additively, so stories MUST use
unique URLs (in practice, a unique `taskHistoryId` per story). This avoids
cross-story contamination without per-story teardown — important because
Storybook can render multiple stories concurrently in docs / composition mode.

**Unmocked fetch URLs fall through to the host's real `fetch`.** Stories that
must not hit the network must register every URL they touch.

## Stories

- `TaskLogViewer/TaskLogViewer.stories.tsx` — running stream, completed
  success/failed, generic stream error, executor-gone (410), stepless events,
  multi-step unread dots, wrap toggle, plus an interactive smoke test that
  uses a `play` function from `storybook/test`. The play function spies on
  `URL.createObjectURL` / `URL.revokeObjectURL` to verify the download flow.
- `TaskLogViewer/StatusBadge.stories.tsx` — one story per badge variant
  (success, failed, stopped, lost, stream-error, executor-gone).
- `TaskLogViewer/StreamErrorBlock.stories.tsx` — generic + 410 layouts.

## CI

`pnpm build-storybook` runs as a blocking step in `.github/workflows/frontend.yaml`,
so a broken story or build config fails CI.

## Adding stories for other components

Drop a `*.stories.tsx` file alongside the component under `src/`. The glob in
`.storybook/main.ts` picks it up. If the component triggers SSE / fetch,
declare mocks in `parameters.sseScripts` / `parameters.fetchResponses` and
make sure your URLs don't collide with existing stories.
