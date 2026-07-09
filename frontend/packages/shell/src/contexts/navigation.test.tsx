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

import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EnabledApp } from '@sep/api';

const useEnabledApps = vi.hoisted(() => vi.fn());
vi.mock('@sep/api', async (importActual) => {
  const actual = await importActual<typeof import('@sep/api')>();
  return { ...actual, useEnabledApps };
});

import { NavigationProvider, useNavigation, type NavItem } from './navigation';

const app = (app_key: string, enabled: boolean): EnabledApp => ({
  app_key,
  enabled,
  sidebar: true,
  uri_path: `/${app_key}`,
  display_name: app_key.charAt(0).toUpperCase() + app_key.slice(1),
  custom_ui: false,
  group: null,
  nav_order: null,
});

/** Flatten leaf titles (parents + children) for assertion convenience. */
function leafTitles(items: NavItem[]): string[] {
  return items.flatMap((i) => (i.children ? leafTitles(i.children) : [i.title]));
}

function Probe() {
  const { items } = useNavigation();
  return <div data-testid="titles">{leafTitles(items).join(',')}</div>;
}

function renderProvider() {
  render(
    <NavigationProvider>
      <Probe />
    </NavigationProvider>,
  );
  return screen.getByTestId('titles').textContent ?? '';
}

beforeEach(() => {
  // NavigationProvider seeds `sidebarOpen` from matchMedia, absent under jsdom.
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('NavigationProvider', () => {
  it('drops disabled-app items and keeps non-app items', () => {
    // Snippets disabled, Tasks enabled; everything else absent → filtered out
    // except the always-on non-app items (Dashboard, Inventory).
    useEnabledApps.mockReturnValue({ data: [app('tasks', true), app('snippets', false)] });
    const titles = renderProvider();

    expect(titles).toContain('Dashboard');
    expect(titles).toContain('Inventory');
    expect(titles).toContain('Tasks');
    expect(titles).not.toContain('Snippets');
  });

  it('renders only the static entries on a cold load or error', () => {
    useEnabledApps.mockReturnValue({ data: undefined });
    const titles = renderProvider();

    expect(titles).toContain('Dashboard');
    expect(titles).toContain('Inventory');
    expect(titles).not.toContain('Snippets');
    expect(titles).not.toContain('Tasks');
  });
});
