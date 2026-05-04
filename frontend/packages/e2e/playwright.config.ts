/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import { defineConfig, devices } from '@playwright/test';

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: './tests',
  testIgnore: ['**/_template.spec.ts'],
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
