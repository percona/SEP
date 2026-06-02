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

import type { Route } from '@playwright/test';

/**
 * Shared mock for the shell's ``GET /api/apps/`` endpoint (consumed by the
 * `useEnabledApps` hook on every page to filter the sidebar). Every spec that
 * installs a ``**\/api/**`` catch-all and renders the shell must answer this
 * request: a 404 surfaces as a console.error (failing console-clean assertions)
 * and an empty array collapses the sidebar to Dashboard + Inventory.
 */

/** Shape of one entry in the ``GET /api/apps/`` response (mirrors `@sep/api`'s `EnabledApp`). */
export interface MockEnabledApp {
  app_key: string;
  enabled: boolean;
  sidebar: boolean;
  uri_path: string;
}

// Every navigation `appKey` from packages/shell/.../navigation.tsx, all enabled,
// so the full sidebar renders. Keep in sync with `defaultNavItems`.
const NAV_APP_KEYS = [
  'tasks',
  'snippets',
  'atw',
  'alerts',
  'alert_troubleshooting',
  'alters',
  'checksums',
  'mysql_backups',
  'backup_mongo',
  'backup_pg',
  'archives',
  'dipper',
  'report',
] as const;

export const MOCK_ENABLED_APPS: MockEnabledApp[] = NAV_APP_KEYS.map((app_key) => ({
  app_key,
  enabled: true,
  sidebar: true,
  uri_path: `/${app_key}`,
}));

/** True when the request targets the shell's ``GET /api/apps/`` endpoint. */
export function isEnabledAppsPath(pathname: string): boolean {
  return pathname === '/api/apps/';
}

/** Fulfill a matched ``/api/apps/`` request with every nav app enabled. */
export function fulfillEnabledApps(route: Route): Promise<void> {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(MOCK_ENABLED_APPS),
  });
}
