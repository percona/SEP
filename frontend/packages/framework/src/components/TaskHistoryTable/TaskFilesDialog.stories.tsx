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

import type { Meta, StoryObj } from '@storybook/react-vite';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TaskFilesDialog } from './TaskFilesDialog';

const FILES_ONLY = {
  'output/result.csv': { size: 204800, is_dir: false },
  'output/summary.txt': { size: 1024, is_dir: false },
};

const DIR_ONLY = {
  'artifacts/run-2026-01-15/': { size: 0, is_dir: true },
};

const MIXED = {
  'output/report.pdf': { size: 1048576, is_dir: false },
  'output/logs/': { size: 0, is_dir: true },
  'output/data.csv': { size: 51200, is_dir: false },
};

/** Pre-populate a QueryClient so the dialog renders instantly without a real API call.
 * staleTime: Infinity prevents the pre-seeded data from being immediately refetched
 * (which would flip the dialog into an error state since no real server is available). */
function makePreloadedClient(taskHistoryId: number, data: object) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(['task-history-files', taskHistoryId], data);
  return client;
}

const meta: Meta<typeof TaskFilesDialog> = {
  title: 'Framework/TaskHistoryTable',
  component: TaskFilesDialog,
  parameters: { layout: 'centered' },
};
export default meta;

type Story = StoryObj<typeof TaskFilesDialog>;

export const FilesDialog_FilesOnly: Story = {
  name: 'Files Dialog – Files only',
  args: { open: true, taskHistoryId: 1, onClose: () => {} },
  decorators: [
    (Story) => (
      <QueryClientProvider client={makePreloadedClient(1, FILES_ONLY)}>
        <Story />
      </QueryClientProvider>
    ),
  ],
};

export const FilesDialog_DirOnly: Story = {
  name: 'Files Dialog – Directory only',
  args: { open: true, taskHistoryId: 2, onClose: () => {} },
  decorators: [
    (Story) => (
      <QueryClientProvider client={makePreloadedClient(2, DIR_ONLY)}>
        <Story />
      </QueryClientProvider>
    ),
  ],
};

export const FilesDialog_Mixed: Story = {
  name: 'Files Dialog – Mixed files and directories',
  args: { open: true, taskHistoryId: 3, onClose: () => {} },
  decorators: [
    (Story) => (
      <QueryClientProvider client={makePreloadedClient(3, MIXED)}>
        <Story />
      </QueryClientProvider>
    ),
  ],
};

export const FilesDialog_Empty: Story = {
  name: 'Files Dialog – Empty',
  args: { open: true, taskHistoryId: 4, onClose: () => {} },
  decorators: [
    (Story) => (
      <QueryClientProvider client={makePreloadedClient(4, {})}>
        <Story />
      </QueryClientProvider>
    ),
  ],
};
