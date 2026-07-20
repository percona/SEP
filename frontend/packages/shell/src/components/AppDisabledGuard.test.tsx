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

// The guard reads the same `useEnabledApps` query that drives the sidebar.
// Mock only that export so we can drive each lifecycle state deterministically.
const useEnabledApps = vi.hoisted(() => vi.fn());
vi.mock('@sep/api', async (importActual) => {
  const actual = await importActual<typeof import('@sep/api')>();
  return { ...actual, useEnabledApps };
});

import AppDisabledGuard from './AppDisabledGuard';

const app = (overrides: Partial<EnabledApp>): EnabledApp => ({
  app_key: 'snippets',
  enabled: true,
  sidebar: true,
  uri_path: '/snippets',
  display_name: 'Snippet Manager',
  custom_ui: false,
  group: null,
  nav_order: null,
  react_route: '/snippets',
  nav_icon: null,
  blocking_dependencies: [],
  ...overrides,
});

function renderGuard(appKey = 'snippets') {
  return render(
    <MemoryRouter>
      <AppDisabledGuard appKey={appKey}>
        <div data-testid="child">child route</div>
      </AppDisabledGuard>
    </MemoryRouter>,
  );
}

const SPLASH = 'This feature is currently disabled.';

afterEach(() => {
  vi.clearAllMocks();
});

describe('AppDisabledGuard', () => {
  it('renders the splash when the app is disabled', () => {
    useEnabledApps.mockReturnValue({ data: [app({ enabled: false })] });
    renderGuard();
    expect(screen.getByText(SPLASH)).toBeInTheDocument();
    expect(screen.queryByTestId('child')).not.toBeInTheDocument();
  });

  it('renders the wrapped route when the app is enabled', () => {
    useEnabledApps.mockReturnValue({ data: [app({ enabled: true })] });
    renderGuard();
    expect(screen.getByTestId('child')).toBeInTheDocument();
    expect(screen.queryByText(SPLASH)).not.toBeInTheDocument();
  });

  it('shows a spinner during the cold initial load instead of mounting the route', () => {
    // No cached data yet → hold a spinner so the disabled-URL outcome is
    // deterministic rather than racing the optimistic app mount.
    useEnabledApps.mockReturnValue({ data: undefined, isLoading: true });
    renderGuard();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByTestId('child')).not.toBeInTheDocument();
    expect(screen.queryByText(SPLASH)).not.toBeInTheDocument();
  });

  it('renders the wrapped route on hook error (fail-open)', () => {
    useEnabledApps.mockReturnValue({ data: undefined, isError: true });
    renderGuard();
    expect(screen.getByTestId('child')).toBeInTheDocument();
    expect(screen.queryByText(SPLASH)).not.toBeInTheDocument();
  });

  it('fails open on a refetch error even while holding stale disabled data', () => {
    // React Query keeps the last successful payload while `isError` is true; the
    // guard must still render children rather than the stale-driven splash.
    useEnabledApps.mockReturnValue({ data: [app({ enabled: false })], isError: true });
    renderGuard();
    expect(screen.getByTestId('child')).toBeInTheDocument();
    expect(screen.queryByText(SPLASH)).not.toBeInTheDocument();
  });

  it('renders the wrapped route when the app key is absent from the response', () => {
    useEnabledApps.mockReturnValue({ data: [app({ app_key: 'tasks', enabled: false })] });
    renderGuard();
    expect(screen.getByTestId('child')).toBeInTheDocument();
    expect(screen.queryByText(SPLASH)).not.toBeInTheDocument();
  });

  it('names the blocking required app when the disablement is dependency-driven', () => {
    // atw is effective-disabled because its required app (snippets) is off; the
    // splash must name the dependency by its display_name, mapped from the list.
    useEnabledApps.mockReturnValue({
      data: [
        app({
          app_key: 'atw',
          display_name: 'Collect Diagnostic Data',
          enabled: false,
          blocking_dependencies: ['snippets'],
        }),
        app({ app_key: 'snippets', display_name: 'Snippet Manager', enabled: false }),
      ],
    });
    renderGuard('atw');
    expect(screen.getByText('Collect Diagnostic Data is unavailable')).toBeInTheDocument();
    expect(
      screen.getByText(
        'The Snippet Manager app must be enabled first. Contact an administrator to enable it.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('child')).not.toBeInTheDocument();
  });

  it('falls back to the generic splash when a blocking key cannot be mapped to a name', () => {
    // Defensive: an unmappable blocking key must never surface a raw key; the
    // guard drops it and the generic copy applies.
    useEnabledApps.mockReturnValue({
      data: [app({ enabled: false, blocking_dependencies: ['ghost'] })],
    });
    renderGuard();
    expect(screen.getByText(SPLASH)).toBeInTheDocument();
  });

  it('names every blocking app through the guard for multiple dependencies', () => {
    useEnabledApps.mockReturnValue({
      data: [
        app({
          app_key: 'atw',
          display_name: 'Collect Diagnostic Data',
          enabled: false,
          blocking_dependencies: ['snippets', 'tasks'],
        }),
        app({ app_key: 'snippets', display_name: 'Snippet Manager', enabled: false }),
        app({ app_key: 'tasks', display_name: 'Task Manager', enabled: false }),
      ],
    });
    renderGuard('atw');
    expect(screen.getByText('Collect Diagnostic Data is unavailable')).toBeInTheDocument();
    expect(
      screen.getByText(
        'These apps must be enabled first: Snippet Manager, Task Manager. Contact an administrator to enable them.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('child')).not.toBeInTheDocument();
  });

  it('drops only the unmappable key and keeps the singular message for the rest', () => {
    // One blocking key maps to a name, the other does not: the guard filters the
    // unmappable one, leaving a single named blocker (so the message stays singular).
    useEnabledApps.mockReturnValue({
      data: [
        app({
          app_key: 'atw',
          display_name: 'Collect Diagnostic Data',
          enabled: false,
          blocking_dependencies: ['snippets', 'ghost'],
        }),
        app({ app_key: 'snippets', display_name: 'Snippet Manager', enabled: false }),
      ],
    });
    renderGuard('atw');
    expect(screen.getByText('Collect Diagnostic Data is unavailable')).toBeInTheDocument();
    expect(
      screen.getByText(
        'The Snippet Manager app must be enabled first. Contact an administrator to enable it.',
      ),
    ).toBeInTheDocument();
  });

  it('shows the generic splash when blocking_dependencies is absent from the entry', () => {
    // A backend/contract gap that omits the field must hit the `?? []` fallback
    // rather than throwing on a missing array.
    const disabled = { ...app({ enabled: false }) } as Partial<EnabledApp>;
    delete disabled.blocking_dependencies;
    useEnabledApps.mockReturnValue({ data: [disabled as EnabledApp] });
    renderGuard();
    expect(screen.getByText(SPLASH)).toBeInTheDocument();
  });

  it('replaces the cold-load spinner with the splash once the query resolves', () => {
    useEnabledApps.mockReturnValue({ data: undefined, isLoading: true });
    const { rerender } = renderGuard();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();

    useEnabledApps.mockReturnValue({ data: [app({ enabled: false })] });
    rerender(
      <MemoryRouter>
        <AppDisabledGuard appKey="snippets">
          <div data-testid="child">child route</div>
        </AppDisabledGuard>
      </MemoryRouter>,
    );
    expect(screen.getByText(SPLASH)).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
});
