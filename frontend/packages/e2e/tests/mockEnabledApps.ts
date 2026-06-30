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
  group: string | null;
  nav_order: number | null;
}

// Registry-driven nav app keys from shell/src/appNavConfig.ts — all enabled so
// the full sidebar renders. ``display_name`` values mirror backend registry labels.
// ``custom_ui`` is forced false here — the derived sidebar tree does not branch on
// it. ``group`` / ``nav_order`` mirror the backend nav_order scale that drives the
// derived tree.
const NAV_APP_METADATA = {
  tasks: { display_name: 'Task Manager', uri_path: '/tasks', group: null, nav_order: 1 },
  snippets: {
    display_name: 'Snippet Manager',
    uri_path: '/snippets',
    group: null,
    nav_order: 2,
  },
  atw: {
    display_name: 'Collect Diagnostic Data',
    uri_path: '/atw',
    group: 'diagnostics',
    nav_order: 3,
  },
  alerts: { display_name: 'Alert Templates', uri_path: '/alerts', group: 'alerts', nav_order: 4 },
  alert_troubleshooting: {
    display_name: 'Alert Troubleshooting',
    uri_path: '/alert-troubleshooting',
    group: 'alerts',
    nav_order: 5,
  },
  alters: { display_name: 'Alters', uri_path: '/alters', group: null, nav_order: 6 },
  checksums: { display_name: 'Checksums', uri_path: '/checksums', group: null, nav_order: 7 },
  mysql_backups: {
    display_name: 'MySQL Backups',
    uri_path: '/mysql_backups',
    group: 'backups',
    nav_order: 8,
  },
  backup_mongo: {
    display_name: 'MongoDB Backups',
    uri_path: '/backup_mongo',
    group: 'backups',
    nav_order: 9,
  },
  backup_pg: {
    display_name: 'PostgreSQL Backups',
    uri_path: '/backups/postgresql',
    group: 'backups',
    nav_order: 10,
  },
  archives: { display_name: 'Archives', uri_path: '/archives', group: null, nav_order: 11 },
  dipper: {
    display_name: 'Dipper Data Collection',
    uri_path: '/dipper',
    group: 'diagnostics',
    nav_order: 12,
  },
  report: {
    display_name: 'Health & Security Report',
    uri_path: '/report',
    group: 'diagnostics',
    nav_order: 13,
  },
} as const satisfies Record<
  string,
  { display_name: string; uri_path: string; group: string | null; nav_order: number }
>;

export const NAV_APP_KEYS = Object.keys(NAV_APP_METADATA) as (keyof typeof NAV_APP_METADATA)[];

export const MOCK_ENABLED_APPS: MockEnabledApp[] = NAV_APP_KEYS.map((app_key) => ({
  app_key,
  enabled: true,
  sidebar: true,
  custom_ui: false,
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
