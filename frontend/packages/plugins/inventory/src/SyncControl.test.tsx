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

import type { ReactNode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SnackbarProvider } from 'notistack';
import { apiClient } from '@sep/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SyncControl } from './SyncControl';

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <SnackbarProvider>{children}</SnackbarProvider>
      </QueryClientProvider>
    );
  };
}

function stubGet(syncers: { name: string; display_name: string }[], isRunning = false) {
  return vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
    if (String(url).includes('/available-syncers/')) {
      return { data: syncers };
    }
    if (String(url).includes('/sync/status/')) {
      return { data: { is_running: isRunning } };
    }
    throw new Error(`Unmocked GET ${String(url)}`);
  });
}

async function stubPost(status = 200, body: unknown = {}) {
  return vi.spyOn(apiClient, 'post').mockImplementation(async () => {
    if (status >= 400) {
      const { ApiError } = await import('@sep/api');
      throw new ApiError(
        {
          kind: 'http',
          status,
          message: (body as { detail?: string }).detail ?? `HTTP ${status}`,
        },
        null,
      );
    }
    return { data: body };
  });
}

describe('SyncControl', () => {
  describe('render-when-syncers-empty', () => {
    afterEach(() => vi.restoreAllMocks());

    it('renders nothing when available-syncers is empty', async () => {
      const spy = stubGet([]);
      const { container } = render(<SyncControl />, { wrapper: makeWrapper() });
      // Wait for the query to settle (spy called) before asserting — avoids a
      // false positive where the assertion passes during the loading phase.
      await waitFor(() => expect(spy).toHaveBeenCalled());
      expect(container.firstChild).toBeNull();
    });
  });

  describe('render-with-single-syncer', () => {
    afterEach(() => vi.restoreAllMocks());

    it('shows primary button but no dropdown chevron', async () => {
      stubGet([{ name: 'myapp.MySyncer', display_name: 'My Syncer' }]);
      render(<SyncControl />, { wrapper: makeWrapper() });
      await screen.findByRole('button', { name: /sync all/i });
      expect(screen.queryByRole('button', { name: /select a syncer/i })).not.toBeInTheDocument();
    });
  });

  describe('render-with-multiple-syncers', () => {
    afterEach(() => vi.restoreAllMocks());

    it('shows primary button and dropdown chevron', async () => {
      stubGet([
        { name: 'myapp.SyncerA', display_name: 'Syncer A' },
        { name: 'myapp.SyncerB', display_name: 'Syncer B' },
      ]);
      render(<SyncControl />, { wrapper: makeWrapper() });
      await screen.findByRole('button', { name: /sync all/i });
      expect(screen.getByRole('button', { name: /select a syncer/i })).toBeInTheDocument();
    });

    it('opens dropdown menu on chevron click', async () => {
      const user = userEvent.setup();
      stubGet([
        { name: 'myapp.SyncerA', display_name: 'Syncer A' },
        { name: 'myapp.SyncerB', display_name: 'Syncer B' },
      ]);
      render(<SyncControl />, { wrapper: makeWrapper() });
      await screen.findByRole('button', { name: /select a syncer/i });
      await user.click(screen.getByRole('button', { name: /select a syncer/i }));
      await screen.findByRole('menuitem', { name: /Sync Syncer A/i });
      expect(screen.getByRole('menuitem', { name: /Sync Syncer B/i })).toBeInTheDocument();
    });
  });

  describe('primary-button trigger', () => {
    afterEach(() => vi.restoreAllMocks());

    it('POSTs to /sync/ with empty body when primary button clicked', async () => {
      const user = userEvent.setup();
      stubGet([{ name: 'myapp.MySyncer', display_name: 'My Syncer' }]);
      const postSpy = await stubPost(202);
      render(<SyncControl />, { wrapper: makeWrapper() });
      await user.click(await screen.findByRole('button', { name: /sync all/i }));
      await waitFor(() => {
        expect(postSpy).toHaveBeenCalledWith(expect.stringContaining('/sync/'), {});
      });
    });
  });

  describe('dropdown-item trigger', () => {
    afterEach(() => vi.restoreAllMocks());

    it('POSTs to /sync/ with syncer name when dropdown item clicked', async () => {
      const user = userEvent.setup();
      stubGet([
        { name: 'myapp.SyncerA', display_name: 'Syncer A' },
        { name: 'myapp.SyncerB', display_name: 'Syncer B' },
      ]);
      const postSpy = await stubPost(202);
      render(<SyncControl />, { wrapper: makeWrapper() });
      await user.click(await screen.findByRole('button', { name: /select a syncer/i }));
      await user.click(await screen.findByRole('menuitem', { name: /Sync Syncer A/i }));
      await waitFor(() => {
        expect(postSpy).toHaveBeenCalledWith(expect.stringContaining('/sync/'), {
          syncer: 'myapp.SyncerA',
        });
      });
    });
  });

  describe('disabled-while-running', () => {
    afterEach(() => vi.restoreAllMocks());

    it('disables button group and shows spinner when sync is running', async () => {
      stubGet([{ name: 'myapp.MySyncer', display_name: 'My Syncer' }], true);
      render(<SyncControl />, { wrapper: makeWrapper() });
      const btn = await screen.findByRole('button', { name: /sync all/i });
      await waitFor(() => expect(btn).toBeDisabled());
      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });
  });

  describe('snackbar-on-400', () => {
    afterEach(() => vi.restoreAllMocks());

    it('shows error snackbar with server message when POST returns 400', async () => {
      const user = userEvent.setup();
      stubGet([{ name: 'myapp.MySyncer', display_name: 'My Syncer' }]);
      await stubPost(400, { detail: 'Unknown syncer: myapp.MySyncer' });
      render(<SyncControl />, { wrapper: makeWrapper() });
      await user.click(await screen.findByRole('button', { name: /sync all/i }));
      await screen.findByText(/Unknown syncer: myapp\.MySyncer/i);
    });

    it('shows generic snackbar for non-400 errors', async () => {
      const user = userEvent.setup();
      stubGet([{ name: 'myapp.MySyncer', display_name: 'My Syncer' }]);
      await stubPost(500, { detail: 'Internal server error' });
      render(<SyncControl />, { wrapper: makeWrapper() });
      await user.click(await screen.findByRole('button', { name: /sync all/i }));
      await screen.findByText(/Failed to start sync/i);
    });
  });
});
