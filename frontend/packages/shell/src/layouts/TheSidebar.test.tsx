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
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The footer reads `useAppInfo`; the surrounding NavigationProvider reads
// `useEnabledApps`. Mock both so the footer rendering is deterministic and the
// nav list stays empty.
const useAppInfo = vi.hoisted(() => vi.fn());
const useEnabledApps = vi.hoisted(() => vi.fn());
vi.mock('@sep/api', async (importActual) => {
  const actual = await importActual<typeof import('@sep/api')>();
  return { ...actual, useAppInfo, useEnabledApps };
});

import { DrawerContent } from './TheSidebar';
import { NavigationProvider } from '../contexts/navigation';

const FOOTER = 'Percona Services Enablement Platform v1.2.3';

function renderDrawer(collapsed: boolean) {
  return render(
    <MemoryRouter>
      <NavigationProvider>
        <DrawerContent collapsed={collapsed} />
      </NavigationProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('TheSidebar footer', () => {
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
    useEnabledApps.mockReturnValue({ data: [] });
  });

  it('renders the dynamic footer text alongside the copyright line when expanded', () => {
    useAppInfo.mockReturnValue({ data: { footer_text: FOOTER } });
    renderDrawer(false);
    expect(screen.getByText(FOOTER)).toBeInTheDocument();
    expect(screen.getByText(/Percona LLC/)).toBeInTheDocument();
  });

  it('hides the footer entirely when the sidebar is collapsed', () => {
    useAppInfo.mockReturnValue({ data: { footer_text: FOOTER } });
    renderDrawer(true);
    expect(screen.queryByText(FOOTER)).not.toBeInTheDocument();
    expect(screen.queryByText(/Percona LLC/)).not.toBeInTheDocument();
  });

  it('renders the copyright line without the footer while loading', () => {
    useAppInfo.mockReturnValue({ data: undefined, isLoading: true });
    renderDrawer(false);
    expect(screen.getByText(/Percona LLC/)).toBeInTheDocument();
    expect(screen.queryByText(FOOTER)).not.toBeInTheDocument();
  });

  it('renders the copyright line without the footer on error', () => {
    useAppInfo.mockReturnValue({ data: undefined, isError: true });
    renderDrawer(false);
    expect(screen.getByText(/Percona LLC/)).toBeInTheDocument();
    expect(screen.queryByText(FOOTER)).not.toBeInTheDocument();
  });
});
