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

import { describe, expect, it } from 'vitest';
import CodeIcon from '@mui/icons-material/Code';
import ExtensionIcon from '@mui/icons-material/Extension';
import type { EnabledApp } from '@sep/api';
import { buildNavigationItems } from './appNavConfig';

function mockApp(overrides: Partial<EnabledApp> & Pick<EnabledApp, 'app_key'>): EnabledApp {
  const { app_key, display_name, uri_path, react_route, ...rest } = overrides;
  return {
    enabled: true,
    sidebar: true,
    custom_ui: false,
    group: null,
    nav_order: null,
    nav_icon: null,
    ...rest,
    app_key,
    uri_path: uri_path ?? `/${app_key}`,
    display_name: display_name ?? app_key,
    react_route: react_route ?? `/apps/${app_key}`,
  };
}

/** The full registry-driven nav set, mirroring the backend nav_order scale. */
const FULL_APP_SET: EnabledApp[] = [
  mockApp({ app_key: 'tasks', nav_order: 1 }),
  mockApp({ app_key: 'snippets', nav_order: 2 }),
  mockApp({ app_key: 'atw', group: 'diagnostics', nav_order: 3 }),
  mockApp({ app_key: 'alerts', group: 'alerts', nav_order: 4 }),
  mockApp({ app_key: 'alert_troubleshooting', group: 'alerts', nav_order: 5 }),
  mockApp({ app_key: 'alters', nav_order: 6 }),
  mockApp({ app_key: 'checksums', nav_order: 7 }),
  mockApp({ app_key: 'mysql_backups', group: 'backups', nav_order: 8 }),
  mockApp({ app_key: 'backup_mongo', group: 'backups', nav_order: 9 }),
  mockApp({ app_key: 'backup_pg', group: 'backups', nav_order: 10 }),
  mockApp({ app_key: 'archives', nav_order: 11 }),
  mockApp({ app_key: 'dipper', group: 'diagnostics', nav_order: 12 }),
  mockApp({ app_key: 'report', group: 'diagnostics', nav_order: 13 }),
];

function findLeaf(items: ReturnType<typeof buildNavigationItems>, appKey: string) {
  for (const item of items) {
    if (item.appKey === appKey) {
      return item;
    }
    if (item.children) {
      const child = item.children.find((entry) => entry.appKey === appKey);
      if (child) {
        return child;
      }
    }
  }
  return undefined;
}

describe('buildNavigationItems', () => {
  it('derives the full top-level order from group/nav_order regardless of input order', () => {
    const items = buildNavigationItems([...FULL_APP_SET].reverse());
    expect(items.map((item) => item.title)).toEqual([
      'Dashboard',
      'Inventory',
      'tasks',
      'snippets',
      'Diagnostics',
      'Alerts',
      'alters',
      'checksums',
      'Backups',
      'archives',
    ]);
  });

  it('orders children within a group by nav_order', () => {
    const items = buildNavigationItems(FULL_APP_SET);
    const diagnostics = items.find((item) => item.title === 'Diagnostics');
    expect(diagnostics?.children?.map((child) => child.appKey)).toEqual([
      'atw',
      'dipper',
      'report',
    ]);
    const alerts = items.find((item) => item.title === 'Alerts');
    expect(alerts?.children?.map((child) => child.appKey)).toEqual([
      'alerts',
      'alert_troubleshooting',
    ]);
    const backups = items.find((item) => item.title === 'Backups');
    expect(backups?.children?.map((child) => child.appKey)).toEqual([
      'mysql_backups',
      'backup_mongo',
      'backup_pg',
    ]);
  });

  it('positions a group by its lowest child nav_order', () => {
    const items = buildNavigationItems(FULL_APP_SET);
    const titles = items.map((item) => item.title);
    expect(titles.indexOf('Diagnostics')).toBeLessThan(titles.indexOf('Backups'));
  });

  it('overlays registry display_name on leaf items', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'snippets', display_name: 'Snippet Manager', nav_order: 2 }),
      mockApp({ app_key: 'archives', display_name: 'Archives', nav_order: 11 }),
    ]);
    expect(findLeaf(items, 'snippets')?.title).toBe('Snippet Manager');
    expect(findLeaf(items, 'archives')?.title).toBe('Archives');
  });

  it('hides apps that are disabled', () => {
    const items = buildNavigationItems([mockApp({ app_key: 'snippets', enabled: false })]);
    expect(findLeaf(items, 'snippets')).toBeUndefined();
  });

  it('hides apps with sidebar false', () => {
    const items = buildNavigationItems([mockApp({ app_key: 'snippets', sidebar: false })]);
    expect(findLeaf(items, 'snippets')).toBeUndefined();
  });

  it('hides a parent group when every child is filtered out', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'alerts', group: 'alerts', nav_order: 4, enabled: false }),
      mockApp({
        app_key: 'alert_troubleshooting',
        group: 'alerts',
        nav_order: 5,
        enabled: false,
      }),
    ]);
    expect(items.some((item) => item.title === 'Alerts')).toBe(false);
  });

  it('keeps a parent group with only its visible children', () => {
    const items = buildNavigationItems([
      mockApp({
        app_key: 'alerts',
        group: 'alerts',
        nav_order: 4,
        display_name: 'Alert Templates',
      }),
      mockApp({
        app_key: 'alert_troubleshooting',
        group: 'alerts',
        nav_order: 5,
        enabled: false,
      }),
    ]);
    const alerts = items.find((item) => item.title === 'Alerts');
    expect(alerts?.children?.map((child) => child.title)).toEqual(['Alert Templates']);
  });

  it('renders an ungrouped app as a top-level item', () => {
    const items = buildNavigationItems([mockApp({ app_key: 'snippets', nav_order: 2 })]);
    expect(items.some((item) => item.appKey === 'snippets')).toBe(true);
  });

  it('falls back to top-level when the group key is unknown', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'archives', group: 'does_not_exist', nav_order: 11 }),
    ]);
    expect(items.some((item) => item.appKey === 'archives')).toBe(true);
  });

  it('renders only the static entries when apps are undefined', () => {
    const items = buildNavigationItems(undefined);
    expect(items.map((item) => item.title)).toEqual(['Dashboard', 'Inventory']);
  });

  it('always keeps Dashboard and Inventory static entries', () => {
    const items = buildNavigationItems([]);
    expect(items.map((item) => item.title)).toEqual(['Dashboard', 'Inventory']);
  });

  it('does not double-render the statically-handled inventory app', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'inventory', display_name: 'Inventory', nav_order: 1 }),
    ]);
    expect(items.filter((item) => item.title === 'Inventory')).toHaveLength(1);
    expect(items.find((item) => item.title === 'Inventory')?.appKey).toBeUndefined();
  });

  it('derives leaf `to` from the payload react_route, not the static map', () => {
    const items = buildNavigationItems([
      mockApp({
        app_key: 'snippets',
        nav_order: 2,
        display_name: 'Snippets',
        react_route: '/snippets/relocated',
      }),
    ]);
    expect(findLeaf(items, 'snippets')?.to).toBe('/snippets/relocated');
  });

  it('renders an app present only in the payload with no static-map entry', () => {
    const items = buildNavigationItems([
      mockApp({
        app_key: 'synthetic',
        display_name: 'Synthetic App',
        react_route: '/apps/synthetic',
        nav_order: 1,
      }),
    ]);
    const leaf = findLeaf(items, 'synthetic');
    expect(leaf?.title).toBe('Synthetic App');
    expect(leaf?.to).toBe('/apps/synthetic');
    expect(leaf?.icon).toBe(ExtensionIcon);
  });

  it('resolves the leaf icon from the payload nav_icon', () => {
    const items = buildNavigationItems([
      mockApp({
        app_key: 'synthetic',
        nav_icon: 'code',
        react_route: '/apps/synthetic',
        nav_order: 1,
      }),
    ]);
    expect(findLeaf(items, 'synthetic')?.icon).toBe(CodeIcon);
  });

  it('falls back to the default icon when nav_icon is null', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'snippets', nav_icon: null, nav_order: 2 }),
    ]);
    expect(findLeaf(items, 'snippets')?.icon).toBe(ExtensionIcon);
  });

  it('excludes a nested app_key from the top-level sidebar', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'mysql_backups', group: 'backups', nav_order: 8 }),
      mockApp({
        app_key: 'mysql_backups/restore',
        react_route: '/apps/mysql_backups/restore',
        nav_order: 8,
      }),
    ]);
    expect(findLeaf(items, 'mysql_backups/restore')).toBeUndefined();
    expect(findLeaf(items, 'mysql_backups')).toBeDefined();
  });
});
