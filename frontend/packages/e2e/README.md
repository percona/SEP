# @sep/e2e — Playwright E2E smoke tests

End-to-end smoke tests for the SEP React shell and schema-driven apps, powered by [Playwright](https://playwright.dev/).

## Quick start

```bash
# From the repo root's frontend/ directory:
pnpm test:e2e                  # run all E2E tests (headless)
pnpm --filter @sep/e2e test:e2e:ui   # open Playwright UI mode for debugging
```

> **Note:** The first run builds the shell with `VITE_MOCK_API=true` and serves the production bundle via `vite preview` on port 5174. Cold builds take longer than a dev-server start — Playwright's `webServer.timeout` is set to 180 s to accommodate that.

## How it works

`playwright.config.ts` runs `VITE_MOCK_API=true pnpm --filter @sep/shell build && pnpm --filter @sep/shell preview --port 5174 --strictPort` as the `webServer`. All API calls are intercepted inside each spec via `page.route('**/api/**', …)` so no real backend is required.

Testing the **production** bundle (not the dev server) is intentional: it exercises the same code path users get. The mock-data fallbacks inside `useAppTasks` are gated on `import.meta.env.DEV || import.meta.env.VITE_MOCK_API === 'true'`, and Vite statically replaces both expressions at build time. Setting `VITE_MOCK_API=true` for this build lights up the fallback branch in the bundle so the schema-driven app list pages render without a live `/api/apps/*` endpoint, while real production builds (which never set the flag) get the fallback dead-code-eliminated.

## Adding a smoke test for a new app

1. **Copy the template:**

   ```bash
   cp tests/_template.spec.ts tests/<app-name>.spec.ts
   ```

2. **Update the two constants at the top of the file:**

   ```ts
   const APP_ROUTE = '/your-app-path'; // React Router path
   const APP_DISPLAY_NAME = 'Your App'; // schema.displayName
   ```

3. **Run and iterate:**

   ```bash
   pnpm --filter @sep/e2e test:e2e:ui
   ```

   Playwright UI mode lets you step through actions, inspect locators, and record new steps.

4. **Locator conventions:** Prefer ARIA roles (`getByRole`) over CSS selectors. For schema-driven list pages the key landmarks are:

   | Element       | Locator                                                 |
   | ------------- | ------------------------------------------------------- |
   | App heading   | `page.getByRole('heading', { name: APP_DISPLAY_NAME })` |
   | Create button | `page.getByRole('button', { name: /new .+/i })`         |
   | Task row      | `page.getByRole('row', { name: /row-text/i })`          |
   | Form field    | `page.getByLabel('Field Label')`                        |

5. **If your app needs a real backend:** replace the `mockAuthenticatedApis` helper with a Playwright `webServer` that starts a backend with a known seed. See `playwright.config.ts` `webServer` docs for the pattern.

## Page-object pattern

For apps with multi-step flows (create → detail → action), extract locators into a page-object class:

```ts
class MyAppPage {
  readonly heading = this.page.getByRole('heading', { name: 'My App' });
  readonly newButton = this.page.getByRole('button', { name: /new my app/i });

  constructor(private readonly page: Page) {}

  async goto() {
    await this.page.goto('/my-app');
  }
}
```

Keep page objects co-located in `tests/` or under `tests/pages/`. Don't create a shared library until at least three specs need the same object.

## CI integration

The `e2e` job in `.github/workflows/frontend.yaml` runs after the `checks` job. It caches the Playwright Chromium binary keyed on `packages/e2e/package.json` so subsequent runs only pay the apt-get system-deps cost (~10 s) rather than re-downloading Chromium (~150 MB).

If the job fails, a `playwright-report` artifact is uploaded (7-day retention) containing HTML traces and failure screenshots.
