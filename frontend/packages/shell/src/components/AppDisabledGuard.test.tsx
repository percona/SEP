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
  ...overrides,
});

function renderGuard() {
  return render(
    <MemoryRouter>
      <AppDisabledGuard appKey="snippets">
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
});
