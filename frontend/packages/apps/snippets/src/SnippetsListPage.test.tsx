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

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, DEFAULT_APP_LIST_LIMIT, DEFAULT_APP_LIST_OFFSET } from '@sep/api';
import { SnippetsListPage } from './SnippetsListPage';
import {
  useSnippets,
  useApproveSnippet,
  useRemoveSnippetApproval,
  useBatchApproveSnippets,
  useSnippetsCapabilities,
  useSnippetServiceTypes,
  useRefreshSnippets,
} from './hooks';

vi.mock('react-router', () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock('./hooks', () => ({
  useSnippets: vi.fn(),
  useApproveSnippet: vi.fn(),
  useRemoveSnippetApproval: vi.fn(),
  useBatchApproveSnippets: vi.fn(),
  useSnippetsCapabilities: vi.fn(),
  // Default to an empty facet so describes that ignore it never crash on the
  // destructure; clearAllMocks keeps this implementation (only resetAllMocks drops it).
  useSnippetServiceTypes: vi.fn(() => ({
    data: { service_types: [], has_uncategorized: false },
  })),
  useRefreshSnippets: vi.fn(),
}));

const mockUseSnippets = vi.mocked(useSnippets);
const mockUseApproveSnippet = vi.mocked(useApproveSnippet);
const mockUseRemoveSnippetApproval = vi.mocked(useRemoveSnippetApproval);
const mockUseBatchApproveSnippets = vi.mocked(useBatchApproveSnippets);
const mockUseSnippetsCapabilities = vi.mocked(useSnippetsCapabilities);
const mockUseSnippetServiceTypes = vi.mocked(useSnippetServiceTypes);
const mockUseRefreshSnippets = vi.mocked(useRefreshSnippets);

function serviceTypeFacet(service_types: string[], has_uncategorized: boolean) {
  return {
    data: { service_types, has_uncategorized },
  } as unknown as ReturnType<typeof useSnippetServiceTypes>;
}

function snippetsListResult(
  items: Record<string, unknown>[],
  pagination: { total: number; offset: number; limit: number } | null = null,
) {
  return {
    data: { items, pagination },
    isLoading: false,
    error: null,
  } as unknown as ReturnType<typeof useSnippets>;
}

const unapprovedSnippet = {
  filename: 'check.sh',
  title: 'Check',
  description: 'A check script',
  service_type: 'mysql',
  size: 100,
  md5_digest: 'abc123',
  is_approved: false,
  approved_at: null,
  updated_by: null,
  reason: 'New snippet',
  requires_sudo: false,
  sudo_optional: false,
  sudo_default: false,
  interpreter: 'bash',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: null,
};

const approvedSnippet = {
  ...unapprovedSnippet,
  filename: 'approved.sh',
  is_approved: true,
};

describe('SnippetsListPage — ApproveButton', () => {
  const approveMutate = vi.fn();
  const removeMutate = vi.fn();
  const batchMutate = vi.fn();
  const refreshMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseApproveSnippet.mockReturnValue({
      mutate: approveMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useApproveSnippet>);
    mockUseRemoveSnippetApproval.mockReturnValue({
      mutate: removeMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useRemoveSnippetApproval>);
    mockUseBatchApproveSnippets.mockReturnValue({
      mutate: batchMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useBatchApproveSnippets>);
    // Default: manual sync disabled, no pending refresh.
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: false },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: refreshMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);
  });

  describe('per-row approval requires confirmation', () => {
    beforeEach(() => {
      mockUseSnippets.mockReturnValue(snippetsListResult([unapprovedSnippet]));
    });

    it('disables approval until the snippet has been downloaded', () => {
      render(<SnippetsListPage isAdmin />);

      expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled();
    });

    it('download action enables the approval confirmation flow', () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('link', { name: /download/i }));
      fireEvent.click(screen.getByRole('button', { name: /approve/i }));

      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(approveMutate).not.toHaveBeenCalled();
    });

    it('dialog warns about approving without inspection', () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('link', { name: /download/i }));
      fireEvent.click(screen.getByRole('button', { name: /approve/i }));

      const dialog = screen.getByRole('dialog');
      expect(dialog).toHaveTextContent(/inspect/i);
    });

    it('dialog includes the snippet filename', () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('link', { name: /download/i }));
      fireEvent.click(screen.getByRole('button', { name: /approve/i }));

      expect(screen.getByRole('dialog')).toHaveTextContent('check.sh');
    });

    it('Cancel closes the dialog without approving', async () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('link', { name: /download/i }));
      fireEvent.click(screen.getByRole('button', { name: /approve/i }));
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
      expect(approveMutate).not.toHaveBeenCalled();
    });

    it('Confirm in dialog calls approve mutation', () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('link', { name: /download/i }));
      fireEvent.click(screen.getByRole('button', { name: /approve/i }));
      fireEvent.click(screen.getByRole('button', { name: /^approve$/i }));

      expect(approveMutate).toHaveBeenCalledOnce();
    });
  });

  describe('Remove approval button needs no confirmation', () => {
    beforeEach(() => {
      mockUseSnippets.mockReturnValue(snippetsListResult([approvedSnippet]));
    });

    it('fires remove mutation immediately without a dialog', () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('button', { name: /remove/i }));

      expect(removeMutate).toHaveBeenCalledOnce();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  describe('batch approval requires confirmation', () => {
    beforeEach(() => {
      mockUseSnippets.mockReturnValue(snippetsListResult([unapprovedSnippet, approvedSnippet]));
    });

    it('opens a confirmation dialog instead of batch approving immediately', () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('checkbox', { name: /select check\.sh/i }));
      fireEvent.click(screen.getByRole('button', { name: /batch approve/i }));

      expect(screen.getByRole('dialog')).toHaveTextContent(/WITHOUT being downloaded first/i);
      expect(batchMutate).not.toHaveBeenCalled();
    });

    it('confirming the batch dialog calls the batch mutation', () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('checkbox', { name: /select check\.sh/i }));
      fireEvent.click(screen.getByRole('button', { name: /batch approve/i }));
      fireEvent.click(screen.getByRole('button', { name: /approve selected/i }));

      expect(batchMutate).toHaveBeenCalledWith({ filenames: ['check.sh'] }, expect.any(Object));
    });

    it('select all ignores already-approved snippets', () => {
      render(<SnippetsListPage isAdmin />);

      fireEvent.click(screen.getByRole('checkbox', { name: /select all snippets/i }));

      expect(screen.getByRole('checkbox', { name: /select check\.sh/i })).toBeChecked();
      expect(screen.getByRole('checkbox', { name: /select approved\.sh/i })).not.toBeChecked();
      expect(screen.getByRole('checkbox', { name: /select approved\.sh/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /batch approve \(1\)/i })).toBeInTheDocument();
    });
  });
});

describe('SnippetsListPage — RefreshButton', () => {
  const refreshMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSnippets.mockReturnValue(snippetsListResult([]));
    mockUseApproveSnippet.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useApproveSnippet>);
    mockUseRemoveSnippetApproval.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRemoveSnippetApproval>);
    mockUseBatchApproveSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useBatchApproveSnippets>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: refreshMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);
  });

  it('hides refresh button when manual_sync_enabled is false (admin)', () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: false },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);

    render(<SnippetsListPage isAdmin />);

    expect(screen.queryByRole('button', { name: /refresh snippets/i })).not.toBeInTheDocument();
  });

  it('hides refresh button when user is not admin (sync enabled)', () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);

    render(<SnippetsListPage isAdmin={false} />);

    expect(screen.queryByRole('button', { name: /refresh snippets/i })).not.toBeInTheDocument();
  });

  it('shows refresh button when isAdmin and manual_sync_enabled', () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);

    render(<SnippetsListPage isAdmin />);

    expect(screen.getByRole('button', { name: /refresh snippets/i })).toBeInTheDocument();
  });

  it('click opens confirmation dialog with correct text', () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);

    render(<SnippetsListPage isAdmin />);
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toHaveTextContent(
      /Are you sure you want to refresh the saved snippets now\?/i,
    );
    expect(refreshMutate).not.toHaveBeenCalled();
  });

  it('Cancel closes dialog without calling mutation', async () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);

    render(<SnippetsListPage isAdmin />);
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(refreshMutate).not.toHaveBeenCalled();
  });

  it('Confirm calls refresh mutation', () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);

    render(<SnippetsListPage isAdmin />);
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));
    fireEvent.click(screen.getByRole('button', { name: /^refresh$/i }));

    expect(refreshMutate).toHaveBeenCalledOnce();
  });

  it('disables refresh button while mutation is pending', () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: refreshMutate,
      isPending: true,
    } as unknown as ReturnType<typeof useRefreshSnippets>);

    render(<SnippetsListPage isAdmin />);

    expect(screen.getByRole('button', { name: /refresh snippets/i })).toBeDisabled();
  });

  it('shows generic error alert on non-HTTP failure', async () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn((_, callbacks) => {
        callbacks?.onError?.(new Error('disk walk failed'));
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);

    render(<SnippetsListPage isAdmin />);
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));
    fireEvent.click(screen.getByRole('button', { name: /^refresh$/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/refresh failed/i);
    });
  });

  it('surfaces backend detail for HTTP error responses', async () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    const httpErr = new ApiError({
      kind: 'http',
      status: 403,
      message: 'Manual snippet sync is disabled in this deployment.',
    });
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn((_, callbacks) => {
        callbacks?.onError?.(httpErr);
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);

    render(<SnippetsListPage isAdmin />);
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));
    fireEvent.click(screen.getByRole('button', { name: /^refresh$/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/Manual snippet sync is disabled/i);
    });
  });

  it('shows formatted timestamp on success', async () => {
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn((_, callbacks) => {
        callbacks?.onSuccess?.({ refreshed_at: '2026-05-07T12:34:56Z' });
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);

    render(<SnippetsListPage isAdmin />);
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));
    fireEvent.click(screen.getByRole('button', { name: /^refresh$/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/Snippets refreshed at/i);
    });
  });

  it('clears downloaded set after successful refresh', async () => {
    mockUseSnippets.mockReturnValue(snippetsListResult([unapprovedSnippet]));
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn((_, callbacks) => {
        callbacks?.onSuccess?.({ refreshed_at: '2026-05-07T12:34:56Z' });
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);

    render(<SnippetsListPage isAdmin />);

    // Download enables the Approve button.
    fireEvent.click(screen.getByRole('link', { name: /download/i }));
    expect(screen.getByRole('button', { name: /approve/i })).not.toBeDisabled();

    // Trigger refresh.
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));
    fireEvent.click(screen.getByRole('button', { name: /^refresh$/i }));

    // Approve should be disabled again — downloaded set cleared.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled();
    });
  });

  it('clears selected set after successful refresh', async () => {
    mockUseSnippets.mockReturnValue(snippetsListResult([unapprovedSnippet]));
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn((_, callbacks) => {
        callbacks?.onSuccess?.({ refreshed_at: '2026-05-07T12:34:56Z' });
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);

    render(<SnippetsListPage isAdmin />);

    // Select the snippet.
    fireEvent.click(screen.getByRole('checkbox', { name: /select check\.sh/i }));
    expect(screen.getByRole('button', { name: /batch approve \(1\)/i })).toBeInTheDocument();

    // Trigger refresh.
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));
    fireEvent.click(screen.getByRole('button', { name: /^refresh$/i }));

    // Checkbox unchecked — selected set cleared.
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: /select check\.sh/i })).not.toBeChecked();
    });
  });

  it('resets the service-type filter after a successful refresh', async () => {
    mockUseSnippets.mockReturnValue(
      snippetsListResult([{ ...unapprovedSnippet, filename: 'mysql.sh', service_type: 'mysql' }]),
    );
    mockUseSnippetServiceTypes.mockReturnValue(serviceTypeFacet(['mysql'], false));
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: true },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn((_, callbacks) => {
        callbacks?.onSuccess?.({ refreshed_at: '2026-05-07T12:34:56Z' });
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);

    render(<SnippetsListPage isAdmin />);

    // Narrow to the mysql service type.
    fireEvent.mouseDown(screen.getByLabelText('Filter by service type'));
    fireEvent.click(screen.getByRole('option', { name: 'mysql' }));
    expect(screen.getByLabelText('Filter by service type')).toHaveTextContent('mysql');

    // Refresh resets the filter back to "All services".
    fireEvent.click(screen.getByRole('button', { name: /refresh snippets/i }));
    fireEvent.click(screen.getByRole('button', { name: /^refresh$/i }));

    await waitFor(() => {
      expect(screen.getByLabelText('Filter by service type')).toHaveTextContent('All services');
    });
  });
});

describe('SnippetsListPage — server-driven filters', () => {
  const mysqlUnapproved = {
    ...unapprovedSnippet,
    filename: 'mysql-log.sh',
    title: 'MySQL log rotate',
    description: 'rotates logs',
    service_type: 'mysql',
    is_approved: false,
  };
  const mongoApproved = {
    ...unapprovedSnippet,
    filename: 'mongo-status.sh',
    title: 'Mongo status',
    description: 'status check',
    service_type: 'mongodb',
    is_approved: true,
  };
  const mongoUnapproved = {
    ...unapprovedSnippet,
    filename: 'mongo-slow.sh',
    title: 'Mongo slow query',
    description: 'slow query log helper',
    service_type: 'mongodb',
    is_approved: false,
  };
  const uncategorized = {
    ...unapprovedSnippet,
    filename: 'misc.sh',
    title: 'Miscellaneous',
    description: 'no service type here',
    service_type: null,
    is_approved: false,
  };

  const allSnippets = [mysqlUnapproved, mongoApproved, mongoUnapproved, uncategorized];

  function lastQuery(): Record<string, unknown> {
    const { calls } = mockUseSnippets.mock;
    return (calls[calls.length - 1]?.[0] ?? {}) as Record<string, unknown>;
  }

  function selectOption(controlLabel: string, optionName: string) {
    fireEvent.mouseDown(screen.getByLabelText(controlLabel));
    fireEvent.click(screen.getByRole('option', { name: optionName }));
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSnippets.mockReturnValue(
      snippetsListResult(allSnippets, { total: allSnippets.length, offset: 0, limit: 50 }),
    );
    // The dropdown options come from the whole-dataset facet, not the page rows.
    mockUseSnippetServiceTypes.mockReturnValue(serviceTypeFacet(['mongodb', 'mysql'], true));
    mockUseApproveSnippet.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useApproveSnippet>);
    mockUseRemoveSnippetApproval.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRemoveSnippetApproval>);
    mockUseBatchApproveSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useBatchApproveSnippets>);
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: false },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);
  });

  it('drives the free-text search into the server query (debounced, case preserved)', async () => {
    render(<SnippetsListPage />);

    fireEvent.change(screen.getByLabelText('Search snippets'), {
      target: { value: 'SLOW' },
    });

    await waitFor(() => {
      expect(lastQuery()).toMatchObject({ search: 'SLOW' });
    });
  });

  it('drives the approval filter into the server query', () => {
    render(<SnippetsListPage />);

    selectOption('Filter by approval status', 'Not approved');

    expect(lastQuery()).toMatchObject({ approval: 'not_approved' });
  });

  it('drives the service-type filter into the server query', () => {
    render(<SnippetsListPage />);

    selectOption('Filter by service type', 'mongodb');

    expect(lastQuery()).toMatchObject({ serviceType: 'mongodb' });
  });

  it('maps the Uncategorized option to the uncategorized flag', () => {
    render(<SnippetsListPage />);

    selectOption('Filter by service type', 'Uncategorized');

    // A distinct flag carries "no service type" — not an overloaded service_type
    // value that a real free-form service type could collide with.
    expect(lastQuery()).toMatchObject({ uncategorized: true, serviceType: undefined });
  });

  it('sends the raw value for a service type that collides with the "all" sentinel', () => {
    // The facet offers a real service type literally equal to "all", distinct from
    // the "All services" (no-filter) entry.
    mockUseSnippetServiceTypes.mockReturnValue(serviceTypeFacet(['all', 'mongodb'], false));

    render(<SnippetsListPage />);

    selectOption('Filter by service type', 'all');

    expect(lastQuery()).toMatchObject({ serviceType: 'all', uncategorized: false });
  });

  it('drives all three filters into the server query together', async () => {
    render(<SnippetsListPage />);

    selectOption('Filter by approval status', 'Not approved');
    selectOption('Filter by service type', 'mongodb');
    fireEvent.change(screen.getByLabelText('Search snippets'), {
      target: { value: 'log' },
    });

    await waitFor(() => {
      expect(lastQuery()).toMatchObject({
        search: 'log',
        approval: 'not_approved',
        serviceType: 'mongodb',
      });
    });
  });

  it('resets to the first page when a filter changes', () => {
    // A total beyond one page so the next-page control is enabled.
    mockUseSnippets.mockReturnValue(
      snippetsListResult(allSnippets, { total: 120, offset: 0, limit: 50 }),
    );

    render(<SnippetsListPage />);

    // Move to the second page, then change a filter.
    fireEvent.click(screen.getByRole('button', { name: /go to next page/i }));
    expect(lastQuery()).toMatchObject({ offset: 50 });

    selectOption('Filter by approval status', 'Approved');

    expect(lastQuery()).toMatchObject({ offset: 0, approval: 'approved' });
  });

  it('shows the filtered-empty state while keeping the filter controls visible', async () => {
    // The server returns rows until a search narrows them to nothing.
    mockUseSnippets.mockImplementation(
      (options?: { search?: string }) =>
        (options?.search
          ? snippetsListResult([], { total: 0, offset: 0, limit: 50 })
          : snippetsListResult(allSnippets, {
              total: allSnippets.length,
              offset: 0,
              limit: 50,
            })) as ReturnType<typeof useSnippets>,
    );

    render(<SnippetsListPage />);

    fireEvent.change(screen.getByLabelText('Search snippets'), {
      target: { value: 'no-such-snippet' },
    });

    // The search box stays reachable (so the filter can be cleared) and the
    // filtered-empty message replaces the table.
    await waitFor(() => {
      expect(screen.getByText(/no snippets match the current filters/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText('Search snippets')).toBeInTheDocument();
  });

  it('coalesces rapid keystrokes into a single settled search term', () => {
    vi.useFakeTimers();
    try {
      render(<SnippetsListPage />);
      const box = screen.getByLabelText('Search snippets');

      fireEvent.change(box, { target: { value: 'a' } });
      fireEvent.change(box, { target: { value: 'ab' } });
      fireEvent.change(box, { target: { value: 'abc' } });

      // Before the debounce window elapses, no intermediate term reaches the query.
      act(() => {
        vi.advanceTimersByTime(299);
      });
      expect(lastQuery().search).toBeUndefined();

      // One tick later the window closes and only the final term is sent.
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(lastQuery()).toMatchObject({ search: 'abc' });
    } finally {
      vi.useRealTimers();
    }
  });

  it('clearing the search box drops the term and resets to the first page', () => {
    mockUseSnippets.mockReturnValue(
      snippetsListResult(allSnippets, { total: 120, offset: 0, limit: 50 }),
    );
    vi.useFakeTimers();
    try {
      render(<SnippetsListPage />);
      const box = screen.getByLabelText('Search snippets');

      fireEvent.change(box, { target: { value: 'slow' } });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(lastQuery()).toMatchObject({ search: 'slow', offset: 0 });

      // Advance to a later page, then clear the search box.
      fireEvent.click(screen.getByRole('button', { name: /go to next page/i }));
      expect(lastQuery()).toMatchObject({ offset: 50, search: 'slow' });

      fireEvent.change(box, { target: { value: '' } });
      act(() => {
        vi.advanceTimersByTime(300);
      });

      expect(lastQuery().search).toBeUndefined();
      expect(lastQuery()).toMatchObject({ offset: 0 });
    } finally {
      vi.useRealTimers();
    }
  });

  it('sends a service type literally named "uncategorized" as an equality value, not the flag', () => {
    // A real service type named "uncategorized" is prefixed, so it stays distinct
    // from the bare UNCATEGORIZED sentinel and must not flip the flag.
    mockUseSnippetServiceTypes.mockReturnValue(serviceTypeFacet(['mysql', 'uncategorized'], false));

    render(<SnippetsListPage />);

    selectOption('Filter by service type', 'uncategorized');

    expect(lastQuery()).toMatchObject({ serviceType: 'uncategorized', uncategorized: false });
  });

  it('round-trips a service type that itself starts with the "type:" prefix', () => {
    // The MenuItem value double-prefixes ("type:type:foo"); decoding strips only
    // the first prefix so the real value reaches the server intact.
    mockUseSnippetServiceTypes.mockReturnValue(serviceTypeFacet(['type:foo'], false));

    render(<SnippetsListPage />);

    selectOption('Filter by service type', 'type:foo');

    expect(lastQuery()).toMatchObject({ serviceType: 'type:foo', uncategorized: false });
  });

  it('excludes selections for rows hidden by a server filter from the batch payload', () => {
    // Selection is scoped to the visible (current-page) rows, so a row that a
    // server-side filter later drops from the page is never batch-approved.
    const batchMutate = vi.fn();
    mockUseBatchApproveSnippets.mockReturnValue({
      mutate: batchMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useBatchApproveSnippets>);
    mockUseSnippets.mockReturnValue(
      snippetsListResult([mysqlUnapproved, mongoUnapproved], {
        total: 2,
        offset: 0,
        limit: 50,
      }),
    );

    const { rerender } = render(<SnippetsListPage isAdmin />);

    // Select every visible unapproved row.
    fireEvent.click(screen.getByRole('checkbox', { name: /select all snippets/i }));

    // A server filter narrows the page so mongo-slow.sh is no longer present.
    mockUseSnippets.mockReturnValue(
      snippetsListResult([mysqlUnapproved], { total: 1, offset: 0, limit: 50 }),
    );
    rerender(<SnippetsListPage isAdmin />);

    fireEvent.click(screen.getByRole('button', { name: /batch approve/i }));
    fireEvent.click(screen.getByRole('button', { name: /approve selected/i }));

    expect(batchMutate).toHaveBeenCalledWith({ filenames: ['mysql-log.sh'] }, expect.anything());
  });
});

describe('SnippetsListPage — server pagination', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseApproveSnippet.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useApproveSnippet>);
    mockUseRemoveSnippetApproval.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRemoveSnippetApproval>);
    mockUseBatchApproveSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useBatchApproveSnippets>);
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: false },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);
  });

  it('requests the default page from useSnippets', () => {
    mockUseSnippets.mockReturnValue(snippetsListResult([unapprovedSnippet]));

    render(<SnippetsListPage />);

    expect(mockUseSnippets).toHaveBeenCalledWith(
      expect.objectContaining({
        offset: DEFAULT_APP_LIST_OFFSET,
        limit: DEFAULT_APP_LIST_LIMIT,
      }),
    );
  });

  it('renders TablePagination when the hook returns pagination metadata', () => {
    mockUseSnippets.mockReturnValue(
      snippetsListResult([unapprovedSnippet], { total: 120, offset: 0, limit: 50 }),
    );

    render(<SnippetsListPage />);

    expect(screen.getByText(/1–50 of 120/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /go to next page/i })).toBeInTheDocument();
  });

  it('omits TablePagination when the hook returns a bare list', () => {
    mockUseSnippets.mockReturnValue(snippetsListResult([unapprovedSnippet]));

    render(<SnippetsListPage />);

    expect(screen.queryByText(/of \d+/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /go to next page/i })).not.toBeInTheDocument();
  });

  it('refetches with the new offset when the next page is clicked', () => {
    mockUseSnippets.mockReturnValue(
      snippetsListResult([unapprovedSnippet], { total: 120, offset: 0, limit: 50 }),
    );

    render(<SnippetsListPage />);
    mockUseSnippets.mockClear();

    fireEvent.click(screen.getByRole('button', { name: /go to next page/i }));

    expect(mockUseSnippets).toHaveBeenCalledWith(
      expect.objectContaining({
        offset: 50,
        limit: 50,
      }),
    );
  });

  it('guards the page index against a zero limit so the pager never shows NaN', () => {
    // `Math.max(limit, 1)` keeps the page-index division finite even if the
    // backend ever returns a zero limit.
    mockUseSnippets.mockReturnValue(
      snippetsListResult([unapprovedSnippet], { total: 1, offset: 0, limit: 0 }),
    );

    render(<SnippetsListPage />);

    const pager = screen.getByText(/of 1/i);
    expect(pager).toBeInTheDocument();
    expect(pager.textContent ?? '').not.toContain('NaN');
  });

  it('snaps back to the last valid page when the filtered total shrinks below the offset', async () => {
    // The server echoes the requested offset; `total` shrinks after a mutation.
    let total = 120;
    mockUseSnippets.mockImplementation(
      (opts?: { offset?: number }) =>
        snippetsListResult([unapprovedSnippet], {
          total,
          offset: opts?.offset ?? 0,
          limit: 50,
        }) as ReturnType<typeof useSnippets>,
    );

    const { rerender } = render(<SnippetsListPage />);

    // Page to the second page (offset 50), still in range while total is 120.
    fireEvent.click(screen.getByRole('button', { name: /go to next page/i }));
    expect(mockUseSnippets).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 }));

    // A mutation shrinks the filtered total to a single page; the next render
    // surfaces it and the out-of-range offset must be clamped to page one.
    total = 20;
    mockUseSnippets.mockClear();
    rerender(<SnippetsListPage />);

    await waitFor(() => {
      expect(mockUseSnippets).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
    });
    // The row is visible again rather than a stranded empty page.
    expect(screen.getByText('check.sh')).toBeInTheDocument();
    expect(screen.queryByText(/no snippets match the current filters/i)).not.toBeInTheDocument();
  });
});

describe('SnippetsListPage — service-type label normalization', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseApproveSnippet.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useApproveSnippet>);
    mockUseRemoveSnippetApproval.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRemoveSnippetApproval>);
    mockUseBatchApproveSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useBatchApproveSnippets>);
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: false },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);
  });

  function renderWithServiceType(serviceType: string | null) {
    mockUseSnippets.mockReturnValue(
      snippetsListResult([{ ...unapprovedSnippet, service_type: serviceType }], {
        total: 1,
        offset: 0,
        limit: 50,
      }),
    );
    render(<SnippetsListPage />);
  }

  it('labels a spaces-only service type as Uncategorized', () => {
    renderWithServiceType('   ');

    expect(screen.getByText('Uncategorized')).toBeInTheDocument();
  });

  it('space-trims a padded service type for display', () => {
    renderWithServiceType('  mysql  ');

    expect(screen.getByText('mysql')).toBeInTheDocument();
    expect(screen.queryByText('Uncategorized')).not.toBeInTheDocument();
  });

  it('keeps a tab-only service type as a real value, not Uncategorized', () => {
    // SQL TRIM (and the aligned frontend) strip spaces only, so a tab survives —
    // the row is not folded into Uncategorized, matching the server facet.
    renderWithServiceType('\t');

    expect(screen.queryByText('Uncategorized')).not.toBeInTheDocument();
  });
});

describe('SnippetsListPage — loading and error states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSnippetsCapabilities.mockReturnValue({
      data: { manual_sync_enabled: false },
      isLoading: false,
    } as unknown as ReturnType<typeof useSnippetsCapabilities>);
    mockUseBatchApproveSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useBatchApproveSnippets>);
    mockUseRefreshSnippets.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRefreshSnippets>);
  });

  it('renders a loading spinner while the list query is pending', () => {
    mockUseSnippets.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as unknown as ReturnType<typeof useSnippets>);

    render(<SnippetsListPage />);

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders an error alert with the failure message when the list query fails', () => {
    mockUseSnippets.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('backend exploded'),
    } as unknown as ReturnType<typeof useSnippets>);

    render(<SnippetsListPage />);

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Failed to load snippets: backend exploded',
    );
  });
});
