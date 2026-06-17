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
  display_name: string;
  custom_ui: boolean;
}

// Registry-driven nav app keys from shell/src/appNavConfig.ts — all enabled so
// the full sidebar renders. ``display_name`` values mirror backend registry labels.
const NAV_APP_METADATA = {
  tasks: { display_name: 'Task Manager', uri_path: '/tasks', custom_ui: true },
  snippets: { display_name: 'Snippet Manager', uri_path: '/snippets', custom_ui: true },
  atw: { display_name: 'Collect Diagnostic Data', uri_path: '/atw', custom_ui: false },
  alerts: { display_name: 'Alert Templates', uri_path: '/alerts', custom_ui: true },
  alert_troubleshooting: {
    display_name: 'Alert Troubleshooting',
    uri_path: '/alert-troubleshooting',
    custom_ui: true,
  },
  alters: { display_name: 'Alters', uri_path: '/alters', custom_ui: false },
  checksums: { display_name: 'Checksums', uri_path: '/checksums', custom_ui: false },
  mysql_backups: { display_name: 'MySQL Backups', uri_path: '/mysql_backups', custom_ui: false },
  backup_mongo: { display_name: 'MongoDB Backups', uri_path: '/backup_mongo', custom_ui: true },
  backup_pg: {
    display_name: 'PostgreSQL Backups',
    uri_path: '/backups/postgresql',
    custom_ui: false,
  },
  archives: { display_name: 'Archives', uri_path: '/archives', custom_ui: false },
  dipper: { display_name: 'Dipper Data Collection', uri_path: '/dipper', custom_ui: false },
  report: { display_name: 'Health & Security Report', uri_path: '/report', custom_ui: true },
} as const satisfies Record<string, { display_name: string; uri_path: string; custom_ui: boolean }>;

export const NAV_APP_KEYS = Object.keys(NAV_APP_METADATA) as (keyof typeof NAV_APP_METADATA)[];

export const MOCK_ENABLED_APPS: MockEnabledApp[] = NAV_APP_KEYS.map((app_key) => ({
  app_key,
  enabled: true,
  sidebar: true,
  ...NAV_APP_METADATA[app_key],
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
