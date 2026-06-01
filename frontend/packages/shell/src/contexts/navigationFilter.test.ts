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
import DashboardIcon from '@mui/icons-material/Dashboard';
import { filterNavByEnabledApps, type NavItem } from './navigation';

const leaf = (title: string, appKey?: string): NavItem => ({
  title,
  icon: DashboardIcon,
  to: `/${title}`,
  appKey,
});

describe('filterNavByEnabledApps', () => {
  it('keeps an item whose appKey is enabled', () => {
    const items = [leaf('Snippets', 'snippets')];
    const result = filterNavByEnabledApps(items, new Set(['snippets']));
    expect(result.map((i) => i.title)).toEqual(['Snippets']);
  });

  it('drops an item whose appKey is not enabled', () => {
    const items = [leaf('Snippets', 'snippets')];
    const result = filterNavByEnabledApps(items, new Set());
    expect(result).toEqual([]);
  });

  it('always keeps an item without an appKey', () => {
    const items = [leaf('Dashboard'), leaf('Inventory')];
    const result = filterNavByEnabledApps(items, new Set());
    expect(result.map((i) => i.title)).toEqual(['Dashboard', 'Inventory']);
  });

  it('hides a parent group when all its children are disabled', () => {
    const items: NavItem[] = [
      {
        title: 'Alerts',
        icon: DashboardIcon,
        children: [leaf('Templates', 'alerts'), leaf('Troubleshooting', 'alert_troubleshooting')],
      },
    ];
    const result = filterNavByEnabledApps(items, new Set());
    expect(result).toEqual([]);
  });

  it('keeps a parent group with only its enabled children', () => {
    const items: NavItem[] = [
      {
        title: 'Alerts',
        icon: DashboardIcon,
        children: [leaf('Templates', 'alerts'), leaf('Troubleshooting', 'alert_troubleshooting')],
      },
    ];
    const result = filterNavByEnabledApps(items, new Set(['alerts']));
    expect(result).toHaveLength(1);
    expect(result[0].children?.map((c) => c.title)).toEqual(['Templates']);
  });

  it('does not mutate the input items', () => {
    const items: NavItem[] = [
      {
        title: 'Alerts',
        icon: DashboardIcon,
        children: [leaf('Templates', 'alerts'), leaf('Troubleshooting', 'alert_troubleshooting')],
      },
    ];
    filterNavByEnabledApps(items, new Set(['alerts']));
    expect(items[0].children).toHaveLength(2);
  });
});
