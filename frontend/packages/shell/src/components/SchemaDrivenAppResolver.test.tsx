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
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { EnabledApp } from '@sep/api';

const useEnabledApps = vi.hoisted(() => vi.fn());
vi.mock('@sep/api', async (importActual) => {
  const actual = await importActual<typeof import('@sep/api')>();
  return { ...actual, useEnabledApps };
});

// Mock only `SchemaDrivenApp` (the sole framework import the resolver uses) so
// the heavy `@sep/framework` package is never imported by this suite.
vi.mock('@sep/framework', () => ({
  SchemaDrivenApp: ({ pluginName, routeBase }: { pluginName: string; routeBase?: string }) => (
    <div data-testid="schema-app" data-plugin={pluginName} data-routebase={routeBase} />
  ),
}));

vi.mock('../pages/NotFoundPage', () => ({
  default: () => <div data-testid="not-found" />,
}));

vi.mock('../pages/AppDisabledPage', () => ({
  default: () => <div data-testid="app-disabled" />,
}));

import {
  SchemaDrivenAppResolver,
  resolveSchemaApp,
  matchDefaultAppsPath,
} from './SchemaDrivenAppResolver';

function mockApp(overrides: Partial<EnabledApp> & Pick<EnabledApp, 'app_key'>): EnabledApp {
  const { app_key, react_route, ...rest } = overrides;
  return {
    enabled: true,
    sidebar: true,
    custom_ui: false,
    group: null,
    nav_order: null,
    nav_icon: null,
    uri_path: `/${app_key}`,
    display_name: app_key,
    ...rest,
    app_key,
    react_route: react_route ?? `/apps/${app_key}`,
  };
}

const CHECKSUMS = mockApp({ app_key: 'checksums', react_route: '/apps/checksums' });
const BACKUP_PG = mockApp({ app_key: 'backup_pg', react_route: '/backups/postgresql' });
const MYSQL = mockApp({ app_key: 'mysql_backups', react_route: '/apps/mysql_backups' });
const MYSQL_RESTORE = mockApp({
  app_key: 'mysql_backups/restore',
  react_route: '/apps/mysql_backups/restore',
});
const TASKS = mockApp({ app_key: 'tasks', react_route: '/tasks', custom_ui: true });

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <SchemaDrivenAppResolver />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('resolveSchemaApp', () => {
  it('resolves a default /apps/<id> deep link', () => {
    expect(resolveSchemaApp('/apps/checksums', [CHECKSUMS])).toEqual({
      appKey: 'checksums',
      reactRoute: '/apps/checksums',
    });
  });

  it('resolves a deviating deep link', () => {
    expect(resolveSchemaApp('/backups/postgresql', [BACKUP_PG])).toEqual({
      appKey: 'backup_pg',
      reactRoute: '/backups/postgresql',
    });
  });

  it('matches a sub-path via the app react_route prefix', () => {
    expect(resolveSchemaApp('/apps/checksums/123', [CHECKSUMS])).toEqual({
      appKey: 'checksums',
      reactRoute: '/apps/checksums',
    });
  });

  it('resolves a nested URL to the parent app, not the nested key', () => {
    expect(resolveSchemaApp('/apps/mysql_backups/restore', [MYSQL, MYSQL_RESTORE])).toEqual({
      appKey: 'mysql_backups',
      reactRoute: '/apps/mysql_backups',
    });
  });

  it('picks the longest matching prefix', () => {
    const parent = mockApp({ app_key: 'parent', react_route: '/backups' });
    const child = mockApp({ app_key: 'child', react_route: '/backups/pg' });
    expect(resolveSchemaApp('/backups/pg/detail', [parent, child])).toEqual({
      appKey: 'child',
      reactRoute: '/backups/pg',
    });
  });

  it('excludes custom-UI apps from the candidate set', () => {
    expect(resolveSchemaApp('/tasks', [TASKS])).toBeNull();
  });

  it('returns null when no app react_route matches', () => {
    expect(resolveSchemaApp('/nonsense', [CHECKSUMS])).toBeNull();
  });

  it('resolves a disabled app (enabled-agnostic) so it can reach the splash', () => {
    const disabled = mockApp({ app_key: 'checksums', enabled: false });
    expect(resolveSchemaApp('/apps/checksums', [disabled])).toEqual({
      appKey: 'checksums',
      reactRoute: '/apps/checksums',
    });
  });

  it('does not match a react_route that is only a partial segment prefix', () => {
    const app = mockApp({ app_key: 'back', react_route: '/back' });
    expect(resolveSchemaApp('/backups/postgresql', [app])).toBeNull();
  });

  it('matches a slashless deep link against a react_route with a trailing slash', () => {
    const app = mockApp({ app_key: 'checksums', react_route: '/apps/checksums/' });
    expect(resolveSchemaApp('/apps/checksums', [app])).toEqual({
      appKey: 'checksums',
      reactRoute: '/apps/checksums',
    });
  });
});

describe('matchDefaultAppsPath', () => {
  it('extracts the app key from a default /apps/<id> path', () => {
    expect(matchDefaultAppsPath('/apps/checksums')).toEqual({
      appKey: 'checksums',
      reactRoute: '/apps/checksums',
    });
  });

  it('ignores the sub-path below /apps/<id>', () => {
    expect(matchDefaultAppsPath('/apps/checksums/new')).toEqual({
      appKey: 'checksums',
      reactRoute: '/apps/checksums',
    });
  });

  it('returns null for a non-/apps path', () => {
    expect(matchDefaultAppsPath('/backups/postgresql')).toBeNull();
  });
});

describe('SchemaDrivenAppResolver', () => {
  it('mounts the resolved app with its react_route as routeBase', () => {
    useEnabledApps.mockReturnValue({ data: [BACKUP_PG], isLoading: false, isError: false });
    renderAt('/backups/postgresql');

    const app = screen.getByTestId('schema-app');
    expect(app.getAttribute('data-plugin')).toBe('backup_pg');
    expect(app.getAttribute('data-routebase')).toBe('/backups/postgresql');
  });

  it('shows the AppDisabledPage splash for a disabled app, not NotFound', () => {
    useEnabledApps.mockReturnValue({
      data: [mockApp({ app_key: 'checksums', enabled: false })],
      isLoading: false,
      isError: false,
    });
    renderAt('/apps/checksums');

    expect(screen.getByTestId('app-disabled')).toBeTruthy();
    expect(screen.queryByTestId('schema-app')).toBeNull();
    expect(screen.queryByTestId('not-found')).toBeNull();
  });

  it('renders NotFound for an unmatched path after the listing loads', () => {
    useEnabledApps.mockReturnValue({ data: [CHECKSUMS], isLoading: false, isError: false });
    renderAt('/nonsense');

    expect(screen.getByTestId('not-found')).toBeTruthy();
    expect(screen.queryByTestId('schema-app')).toBeNull();
  });

  it('holds a spinner on a cold load with no cached listing', () => {
    useEnabledApps.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    renderAt('/apps/checksums');

    expect(screen.getByRole('progressbar')).toBeTruthy();
    expect(screen.queryByTestId('schema-app')).toBeNull();
    expect(screen.queryByTestId('not-found')).toBeNull();
  });

  it('fails open to a structural /apps/<id> mount when the listing errors', () => {
    useEnabledApps.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    renderAt('/apps/checksums');

    const app = screen.getByTestId('schema-app');
    expect(app.getAttribute('data-plugin')).toBe('checksums');
    expect(app.getAttribute('data-routebase')).toBe('/apps/checksums');
  });

  it('renders NotFound for an unmappable deviating path when the listing errors', () => {
    useEnabledApps.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    renderAt('/backups/postgresql');

    expect(screen.getByTestId('not-found')).toBeTruthy();
    expect(screen.queryByTestId('schema-app')).toBeNull();
  });
});
