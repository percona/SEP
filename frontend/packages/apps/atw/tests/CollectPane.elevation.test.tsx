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

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CollectPane } from '../src/CollectPane';
import type { AtwSnippetSummary } from '../src/types';

vi.mock('@sep/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@sep/api')>()),
  apiClient: { get: vi.fn(), post: vi.fn() },
  useAuth: () => ({ isAdmin: true, canMutate: true }),
}));

import { apiClient } from '@sep/api';
const mockedApi = apiClient as unknown as { get: ReturnType<typeof vi.fn> };

const PT_STALK: AtwSnippetSummary = {
  name: 'pt-stalk.sh',
  title: 'pt-stalk',
  description: 'Executes pt-stalk command.',
  sudo: 'always',
};

const DISK_USAGE: AtwSnippetSummary = {
  name: 'disk_usage.sh',
  title: 'Disk usage',
  description: 'Reports disk usage.',
  sudo: 'optional',
};

const PT_MYSQL_SUMMARY: AtwSnippetSummary = {
  name: 'pt-mysql-summary.sh',
  title: 'pt-mysql-summary',
  description: 'Executes pt-mysql-summary command.',
  sudo: 'never',
};

/**
 * Executors as `GET /api/extensions/hosts/` reports them: measured unable to elevate,
 * measured able, and never observed.
 */
const HOSTS = [
  {
    id: 'pmm-server',
    name: 'pmm-server',
    address: '127.0.0.1',
    can_elevate: false,
  },
  {
    id: 'sep-mysql',
    name: 'sep-mysql',
    address: '172.28.9.40',
    can_elevate: true,
  },
  { id: 'unprobed', name: 'unprobed', address: '10.0.0.9', can_elevate: null },
];

const EXECUTOR_HOST_FIELD = {
  type: 'host',
  name: 'executor_host',
  label: 'Execution Host',
  required: true,
};

const SUDO_FIELD = {
  type: 'bool',
  name: 'sudo',
  label: 'Run with sudo',
  required: false,
  default: false,
};

/** The merged schema the backend builds: a sudo toggle only for an optional-sudo snippet. */
function schemaFor(snippets: AtwSnippetSummary[]) {
  const offersSudo = snippets.some((snippet) => snippet.sudo === 'optional');
  return {
    shared: offersSudo ? [EXECUTOR_HOST_FIELD, SUDO_FIELD] : [EXECUTOR_HOST_FIELD],
    per_snippet: [],
  };
}

function mockApis(snippets: AtwSnippetSummary[]) {
  mockedApi.get.mockImplementation((url: string, config?: { params?: { search?: string } }) => {
    if (url === '/extensions/hosts/') {
      return Promise.resolve({ data: HOSTS });
    }
    if (url.startsWith('/apps/atw/snippets/')) {
      const term = (config?.params?.search ?? '').toLowerCase();
      const items = snippets.filter((snippet) => snippet.title.toLowerCase().includes(term));
      return Promise.resolve({ data: { items, total: items.length, offset: 0, limit: 50 } });
    }
    if (url.includes('/execution-schema/')) {
      return Promise.resolve({ data: schemaFor(snippets) });
    }
    return Promise.resolve({ data: [] });
  });
}

/** Open the pane and pick `snippets` through the snippet search, one at a time. */
async function renderWithSelection(snippets: AtwSnippetSummary[]) {
  mockApis(snippets);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CollectPane incidentId="inc-1" />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  const input = await screen.findByRole('combobox', { name: 'Snippets' });
  for (const snippet of snippets) {
    await user.clear(input);
    await user.paste(snippet.title);
    await user.click(
      await screen.findByRole('option', { name: new RegExp(snippet.title) }, { timeout: 3000 }),
    );
  }
  await user.keyboard('{Escape}');
}

async function chooseHost(name: string) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('combobox', { name: /Execution Host/ }));
  await user.click(await screen.findByRole('option', { name }));
}

const CANNOT_ELEVATE = /cannot run commands with sudo/i;

describe('CollectPane executor elevation warning', { timeout: 15_000 }, () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('warns when the chosen host cannot elevate for a snippet that always runs with sudo', async () => {
    await renderWithSelection([PT_STALK]);

    await chooseHost('pmm-server');

    const warning = await screen.findByText(CANNOT_ELEVATE);
    expect(warning).toHaveTextContent('pmm-server');
    expect(warning).toHaveTextContent('pt-stalk');
    // A warning, not a gate: the batch can still be submitted.
    expect(screen.getByRole('button', { name: 'Execute batch' })).toBeEnabled();
  });

  it('stays silent on a host that can elevate', async () => {
    await renderWithSelection([PT_STALK]);

    await chooseHost('sep-mysql');

    expect(await screen.findByDisplayValue('sep-mysql')).toBeInTheDocument();
    expect(screen.queryByText(CANNOT_ELEVATE)).not.toBeInTheDocument();
  });

  it('stays silent on a host whose capability was never observed', async () => {
    await renderWithSelection([PT_STALK]);

    await chooseHost('unprobed');

    expect(await screen.findByDisplayValue('unprobed')).toBeInTheDocument();
    expect(screen.queryByText(CANNOT_ELEVATE)).not.toBeInTheDocument();
  });

  it('stays silent for a snippet that never runs with sudo', async () => {
    await renderWithSelection([PT_MYSQL_SUMMARY]);

    await chooseHost('pmm-server');

    expect(await screen.findByDisplayValue('pmm-server')).toBeInTheDocument();
    expect(screen.queryByText(CANNOT_ELEVATE)).not.toBeInTheDocument();
  });

  it('warns for an optional-sudo snippet only once Run with sudo is on', async () => {
    await renderWithSelection([DISK_USAGE]);

    await chooseHost('pmm-server');
    expect(await screen.findByDisplayValue('pmm-server')).toBeInTheDocument();
    expect(screen.queryByText(CANNOT_ELEVATE)).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByLabelText('Run with sudo'));

    const warning = await screen.findByText(CANNOT_ELEVATE);
    expect(warning).toHaveTextContent('Disk usage');
    expect(warning).toHaveTextContent(/turn sudo off/i);
  });

  it('names only the snippets that would run with sudo', async () => {
    await renderWithSelection([PT_STALK, PT_MYSQL_SUMMARY]);

    await chooseHost('pmm-server');

    const warning = await screen.findByText(CANNOT_ELEVATE);
    expect(warning).toHaveTextContent('pt-stalk');
    expect(warning).not.toHaveTextContent('pt-mysql-summary');
  });

  it('clears the warning when a capable host is chosen instead', async () => {
    await renderWithSelection([PT_STALK]);

    await chooseHost('pmm-server');
    await screen.findByText(CANNOT_ELEVATE);

    await chooseHost('sep-mysql');

    await waitFor(() => {
      expect(screen.queryByText(CANNOT_ELEVATE)).not.toBeInTheDocument();
    });
  });
});
