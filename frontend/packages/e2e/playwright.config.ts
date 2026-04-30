import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for SEP frontend smoke tests.
 *
 * - Runs against Vite preview server (pnpm --filter @sep/shell preview)
 * - Uses mock data from @sep/checksums for sanity smoke tests
 * - Single Chromium project baseline (cross-browser matrix deferred to future ticket)
 * - HTML reports for local debugging, GitHub reporter for CI
 * - forbidOnly enabled on CI to catch accidental .only() calls
 *
 * Read more: https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,

  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,

  /* Retry strategy:
   * - 0 retries locally (surface flakes immediately)
   * - 0 retries on CI initially (report real flakes; add 1 retry only after ~2 weeks of stability)
   */
  retries: 0,

  /* Opt out of parallel execution to keep startup cost low for the sanity smoke. */
  workers: 1,

  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: [
    ['html'], // Local debugging: playwright show-report
    process.env.CI ? ['github'] : ['list'],
  ],

  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: 'http://localhost:4173',

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  /* Run your local dev server before starting the tests */
  webServer: {
    command: 'pnpm --filter @sep/shell preview --port 4173',
    url: 'http://localhost:4173',
    timeout: 120000,
    reuseExistingServer: process.env.CI ? false : true,
  },
});
