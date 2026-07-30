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
import { expect, userEvent, waitFor, within } from 'storybook/test';
import type { StoryEventSource } from '../../../.storybook/sseMocks';
import { SnippetExecutionAccordion } from './SnippetExecutionAccordion';

const meta: Meta<typeof SnippetExecutionAccordion> = {
  title: 'Framework/SnippetExecutionAccordion',
  component: SnippetExecutionAccordion,
  parameters: { layout: 'padded' },
};

export default meta;
type Story = StoryObj<typeof SnippetExecutionAccordion>;

const baseSchema = {
  name: 'snippets',
  display_name: 'Test Snippet',
  forms: [
    {
      title: 'Execution',
      fields: [
        {
          type: 'string',
          name: 'executor_host',
          label: 'Execution Host',
          required: true,
        },
        {
          type: 'string',
          name: 'table_name',
          label: 'Table Name',
          required: false,
        },
        {
          type: 'string',
          name: 'database_name',
          label: 'Database Name',
          required: false,
        },
      ],
    },
  ],
};

const successHistory = {
  items: [
    {
      id: 101,
      status: 'success',
      started_at: '2026-04-28T10:00:00Z',
      finished_at: '2026-04-28T10:00:42Z',
      duration: 42,
      executed_by: 'admin',
      has_logs: true,
      task: { id: 101, name: 'check.sh' },
      execution_request: {
        task: 'check.sh',
        target: 'db1.example.com',
        meta: {},
        tracking: {},
      },
    },
    {
      id: 100,
      status: 'failed',
      started_at: '2026-04-28T09:00:00Z',
      finished_at: '2026-04-28T09:00:18Z',
      duration: 18,
      executed_by: 'admin',
      has_logs: true,
      task: { id: 100, name: 'check.sh' },
      execution_request: {
        task: 'check.sh',
        target: 'db2.example.com',
        meta: {},
        tracking: {},
      },
    },
  ],
};

// ── Stories ───────────────────────────────────────────────────────────────

/** Collapsed accordion — no schema fetch issued until expanded. */
export const Default: Story = {
  args: {
    snippetFilename: 'collapsed-snippet.sh',
    title: 'Disk usage check',
    description: 'Reports disk usage on the executor host.',
  },
};

/**
 * Accordion with a parent-supplied executor host. The ``executor_host`` field
 * is stripped from the rendered form and injected at submit time.
 */
export const WithExecutorHost: Story = {
  args: {
    snippetFilename: 'host-snippet.sh',
    executorHost: 'db1.example.com',
    title: 'Slow query check',
    description: 'Page-level <HostSelector> drives the host. Form omits it.',
    defaultExpanded: true,
  },
  parameters: {
    fetchResponses: {
      '/api/apps/snippets/snippet/schema?snippet_filename=host-snippet.sh': baseSchema,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => {
      expect(canvas.getByLabelText(/Table Name/i)).toBeInTheDocument();
    });
    expect(canvas.queryByLabelText(/Execution Host/i)).not.toBeInTheDocument();
  },
};

/**
 * Accordion expanded with no parent host. The ``executor_host`` field stays
 * in the form so the user picks the host themselves.
 */
export const DefaultExpanded: Story = {
  args: {
    snippetFilename: 'expanded-snippet.sh',
    title: 'Replication lag check',
    description: 'No parent host; user selects executor in-form.',
    defaultExpanded: true,
  },
  parameters: {
    fetchResponses: {
      '/api/apps/snippets/snippet/schema?snippet_filename=expanded-snippet.sh': baseSchema,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => {
      expect(canvas.getByLabelText(/Execution Host/i)).toBeInTheDocument();
    });
    expect(canvas.getByLabelText(/Table Name/i)).toBeInTheDocument();
  },
};

/**
 * Accordion in snippets-detail mode — execution history table renders below
 * the form. Used by ``SnippetDetailPage``.
 */
export const WithHistory: Story = {
  args: {
    snippetFilename: 'history-snippet.sh',
    executorHost: 'db1.example.com',
    title: 'Connection count audit',
    description: 'Detail-page mode: per-snippet execution history visible.',
    defaultExpanded: true,
    showHistory: true,
  },
  parameters: {
    fetchResponses: {
      '/api/apps/snippets/snippet/schema?snippet_filename=history-snippet.sh': baseSchema,
      '/api/apps/snippets/snippet/history?snippet_filename=history-snippet.sh': successHistory,
    },
  },
};

/**
 * Submit posts to the snippets execute endpoint and surfaces the live log
 * viewer. The story uses the storybook SSE mock harness so the log stream
 * resolves to a SUCCESS terminal status.
 */
export const AfterSuccessfulRun: Story = {
  args: {
    snippetFilename: 'run-snippet.sh',
    executorHost: 'db1.example.com',
    title: 'Run-and-watch',
    description: 'Click Execute; the log viewer mounts and reaches SUCCESS.',
    defaultExpanded: true,
  },
  parameters: {
    fetchResponses: {
      '/api/apps/snippets/snippet/schema?snippet_filename=run-snippet.sh': baseSchema,
      '/api/apps/snippets/snippet/execute?snippet_filename=run-snippet.sh': { task_id: 4242 },
      '/execution-events/4242': [],
    },
    sseScripts: {
      '/stream-logs/4242': (es: StoryEventSource) => {
        es.emitMessage({
          msg: 'Probe started\n',
          step: 'main',
          type: 'stdout',
          offset: 1,
        });
        es.emitMessage({
          msg: 'Probe finished cleanly\n',
          step: 'main',
          type: 'stdout',
          offset: 2,
        });
        es.emitNamed('finish', { status: 'success' });
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const execute = await canvas.findByRole('button', { name: /execute/i });
    await userEvent.click(execute);
    await waitFor(() => {
      expect(canvas.getAllByText(/Probe finished cleanly/i).length).toBeGreaterThan(0);
    });
  },
};
