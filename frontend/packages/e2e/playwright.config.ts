import { defineConfig, devices } from '@playwright/test';

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  // Fail CI immediately if a test file contains a .only call
  forbidOnly: isCI,
  // Zero retries — surface flakes as real failures rather than hiding them
  retries: 0,
  workers: isCI ? 1 : undefined,
  reporter: isCI
    ? [['github'], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : [['html', { open: 'on-failure', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: 'http://localhost:5174',
    // Capture a trace and screenshot only on failure — useful for debugging
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  outputDir: './test-results',
  webServer: {
    // Run the Vite dev server (IS_DEV=true) so mock-data fallbacks in the
    // schema-driven plugin hooks work without a real backend.
    //
    // pnpm traverses up the directory tree to find pnpm-workspace.yaml, so
    // this filter command works from packages/e2e/ without an explicit cwd.
    command: 'pnpm --filter @sep/shell dev',
    url: 'http://localhost:5174',
    // In CI always start a fresh server; locally reuse one if already running.
    reuseExistingServer: !isCI,
    timeout: 60_000,
  },
});
