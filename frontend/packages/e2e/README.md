# @sep/e2e — Playwright E2E smoke tests

End-to-end smoke tests for the SEP React shell and schema-driven plugins, powered by [Playwright](https://playwright.dev/).

## Quick start

```bash
# From the repo root's frontend/ directory:
pnpm test:e2e                  # run all E2E tests (headless)
pnpm --filter @sep/e2e test:e2e:ui   # open Playwright UI mode for debugging
```

> **Note:** The tests use the Vite dev server (`pnpm dev`) as the test target, so no prior build is needed. The first run starts the dev server automatically.

## How it works

`playwright.config.ts` spins up `pnpm --filter @sep/shell dev` (the Vite dev server on port 5174) as the `webServer`. All API calls are intercepted inside each spec via `page.route('**/api/**', …)` so no real backend is required.

Using the Vite **dev** server (not `preview`) is intentional: `import.meta.env.DEV = true` enables the mock-data fallbacks inside `usePluginTasks`, so the schema-driven plugin list pages render without a live `/api/plugins/*` endpoint.

## Adding a smoke test for a new plugin

1. **Copy the template:**

   ```bash
   cp tests/_template.spec.ts tests/<plugin-name>.spec.ts
   ```

2. **Update the two constants at the top of the file:**

   ```ts
   const PLUGIN_ROUTE = '/your-plugin-path'; // React Router path
   const PLUGIN_DISPLAY_NAME = 'Your Plugin'; // schema.displayName
   ```

3. **Run and iterate:**

   ```bash
   pnpm --filter @sep/e2e test:e2e:ui
   ```

   Playwright UI mode lets you step through actions, inspect locators, and record new steps.

4. **Locator conventions:** Prefer ARIA roles (`getByRole`) over CSS selectors. For schema-driven list pages the key landmarks are:

   | Element        | Locator                                                    |
   | -------------- | ---------------------------------------------------------- |
   | Plugin heading | `page.getByRole('heading', { name: PLUGIN_DISPLAY_NAME })` |
   | Create button  | `page.getByRole('button', { name: /new .+/i })`            |
   | Task row       | `page.getByRole('row', { name: /row-text/i })`             |
   | Form field     | `page.getByLabel('Field Label')`                           |

5. **If your plugin needs a real backend:** replace the `mockAuthenticatedApis` helper with a Playwright `webServer` that spins up `docker-compose.yml` with a known seed. See `playwright.config.ts` `webServer` docs for the pattern.

## Page-object pattern

For plugins with multi-step flows (create → detail → action), extract locators into a page-object class:

```ts
class MyPluginPage {
  readonly heading = this.page.getByRole('heading', { name: 'My Plugin' });
  readonly newButton = this.page.getByRole('button', { name: /new my plugin/i });

  constructor(private readonly page: Page) {}

  async goto() {
    await this.page.goto('/my-plugin');
  }
}
```

Keep page objects co-located in `tests/` or under `tests/pages/`. Don't create a shared library until at least three specs need the same object.

## CI integration

The `e2e` job in `.github/workflows/frontend.yaml` runs after the `checks` job. It caches the Playwright Chromium binary keyed on `packages/e2e/package.json` so subsequent runs only pay the apt-get system-deps cost (~10 s) rather than re-downloading Chromium (~150 MB).

If the job fails, a `playwright-report` artifact is uploaded (7-day retention) containing HTML traces and failure screenshots.
