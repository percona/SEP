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
import type { EnabledApp } from '@sep/api';
import { buildNavigationItems } from './appNavConfig';

function mockApp(overrides: Partial<EnabledApp> & Pick<EnabledApp, 'app_key'>): EnabledApp {
  const { app_key, display_name, uri_path, ...rest } = overrides;
  return {
    enabled: true,
    sidebar: true,
    custom_ui: false,
    ...rest,
    app_key,
    uri_path: uri_path ?? `/${app_key}`,
    display_name: display_name ?? app_key,
  };
}

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
  it('renders optimistic fallback titles before apps load', () => {
    const items = buildNavigationItems(undefined);
    expect(findLeaf(items, 'snippets')?.title).toBe('Snippets');
    expect(findLeaf(items, 'archives')?.title).toBe('Archive');
  });

  it('overlays registry display_name on leaf items', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'snippets', display_name: 'Snippet Manager' }),
      mockApp({ app_key: 'archives', display_name: 'Archives' }),
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
      mockApp({ app_key: 'alerts', enabled: false }),
      mockApp({ app_key: 'alert_troubleshooting', enabled: false }),
    ]);
    expect(items.some((item) => item.title === 'Alerts')).toBe(false);
  });

  it('keeps a parent group with only its visible children', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'alerts', display_name: 'Alert Templates' }),
      mockApp({ app_key: 'alert_troubleshooting', enabled: false }),
    ]);
    const alerts = items.find((item) => item.title === 'Alerts');
    expect(alerts?.children?.map((child) => child.title)).toEqual(['Alert Templates']);
  });

  it('always keeps Dashboard and Inventory static entries', () => {
    const items = buildNavigationItems([]);
    expect(items.map((item) => item.title)).toEqual(
      expect.arrayContaining(['Dashboard', 'Inventory']),
    );
  });

  it('preserves react routes from appNavConfig', () => {
    const items = buildNavigationItems([
      mockApp({ app_key: 'mysql_backups', display_name: 'MySQL Backups' }),
    ]);
    expect(findLeaf(items, 'mysql_backups')?.to).toBe('/plugins/mysql_backups');
  });
});
