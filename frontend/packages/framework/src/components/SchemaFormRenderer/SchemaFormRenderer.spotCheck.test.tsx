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

/**
 * Spot-check: one representative form per SchemaFormRenderer consumer.
 *
 * Direct consumers: backup_mongo, alters, atw (CollectPane), dipper.
 * Via SnippetExecutionAccordion: snippets and alert_troubleshooting (same
 * synthesised schema path — user-authored snippet parameters plus Execution
 * controls). Confirms help icons appear only on described fields and core
 * inputs still mount — a regression guard for the framework-global label
 * change. Apps that do not use SchemaFormRenderer (report, alerts list,
 * inventory browse, tasks list) are unaffected by this change.
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { SchemaFormRenderer } from './SchemaFormRenderer';
import type { FormSection } from './types';

vi.mock('@sep/api', () => ({
  apiClient: { get: vi.fn().mockResolvedValue({ data: [] }), post: vi.fn() },
  useAlertConfig: () => ({ data: undefined, isLoading: false }),
}));

function renderWithProviders(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function expectHelp(label: string, present: boolean) {
  // aria-label is the constant "Help"; data-help-for disambiguates per field.
  const matches = document.querySelectorAll(`[data-help-for="${CSS.escape(label)}"]`);
  if (present) {
    expect(matches.length).toBeGreaterThan(0);
  } else {
    expect(matches).toHaveLength(0);
  }
}

describe('SchemaFormRenderer — cross-app help-icon spot-check', () => {
  it('backup_mongo-like create form: icons on described fields only', () => {
    const sections: FormSection[] = [
      {
        title: 'Task',
        fields: [
          {
            type: 'string',
            name: 'credentials_path',
            label: 'Credentials Path',
            description: 'Optional path to MongoDB URI credentials on the Nomad node',
          },
        ],
      },
      {
        title: 'Storage',
        fields: [
          {
            type: 'choice',
            name: 'storage_type',
            label: 'Storage Type',
            choices: [
              { label: 'S3-compatible', value: 's3' },
              { label: 'Filesystem', value: 'filesystem' },
            ],
          },
          {
            type: 'string',
            name: 'storage_s3_region',
            label: 'S3 Region',
            description: 'Required for S3 storage.',
          },
          { type: 'string', name: 'storage_filesystem_path', label: 'Filesystem Path' },
        ],
      },
      {
        title: 'BackupOptions',
        fields: [
          {
            type: 'textarea',
            name: 'backup_priority',
            label: 'Node Priority (YAML)',
            description: 'YAML mapping of mongod addresses to backup priority.',
          },
          { type: 'integer', name: 'backup_compression_level', label: 'Compression Level' },
          {
            type: 'bool',
            name: 'pitr_enabled',
            label: 'Enable PITR',
            description: 'Enable point-in-time recovery.',
          },
        ],
      },
    ];

    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);

    expect(screen.getByTestId('text-input-credentials_path')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-storage_s3_region')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-storage_filesystem_path')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-backup_priority')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-backup_compression_level')).toBeInTheDocument();
    expect(screen.getByTestId('switch-input-pitr_enabled')).toBeInTheDocument();

    expectHelp('Credentials Path', true);
    expectHelp('S3 Region', true);
    expectHelp('Filesystem Path', false);
    expectHelp('Node Priority (YAML)', true);
    expectHelp('Compression Level', false);
    expectHelp('Enable PITR', true);
  });

  it('alters-like create form: icons on described flags, not on bare labels', () => {
    const sections: FormSection[] = [
      {
        title: 'Target',
        fields: [
          {
            type: 'string',
            name: 'schema_name',
            label: 'Schema',
            description: 'Schema to alter; pick from inventory or type a name.',
          },
          {
            type: 'string',
            name: 'table_name',
            label: 'Table',
            description: 'Table to alter; pick from inventory or type a name.',
          },
        ],
      },
      {
        title: 'flags',
        fields: [
          {
            type: 'bool',
            name: 'dry_run',
            label: 'Dry Run',
            description: 'Simulate without swapping the original and new table',
          },
          {
            type: 'string',
            name: 'print',
            label: 'Print',
            description: 'Print SQL statements to STDOUT',
          },
          { type: 'integer', name: 'chunk_time', label: 'Chunk Time' },
        ],
      },
    ];

    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);

    expect(screen.getByTestId('text-input-schema_name')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-table_name')).toBeInTheDocument();
    expect(screen.getByTestId('switch-input-dry_run')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-print')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-chunk_time')).toBeInTheDocument();

    expectHelp('Schema', true);
    expectHelp('Table', true);
    expectHelp('Dry Run', true);
    expectHelp('Print', true);
    expectHelp('Chunk Time', false);
  });

  it('atw CollectPane-like form: shared section plus namespaced per-snippet overrides', () => {
    // Mirrors CollectPane: shared parameters first, then a collapsible card per
    // selected snippet whose fields are namespaced (overrides.snipN.*) so two
    // snippets can declare the same parameter name without colliding.
    const sections: FormSection[] = [
      {
        title: 'Shared parameters',
        fields: [
          { type: 'host', name: 'executor_host', label: 'Execution Host', required: true },
          {
            type: 'bool',
            name: 'sudo',
            label: 'Run with sudo',
            description: 'Prepend sudo to the interpreter when the snippet is executed.',
          },
          {
            type: 'integer',
            name: 'minutes',
            label: 'Lookback minutes',
            description: 'Shared window applied to every selected snippet.',
          },
          { type: 'string', name: 'note', label: 'Operator note' },
        ],
      },
      {
        title: 'Disk usage check',
        description: 'Reports free space on the executor host.',
        collapsible: true,
        fields: [
          {
            type: 'string',
            name: 'overrides.snip0.path',
            label: 'Path',
            description: 'Filesystem path to inspect for this snippet only.',
          },
          { type: 'integer', name: 'overrides.snip0.threshold', label: 'Threshold %' },
        ],
      },
    ];

    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);

    expect(screen.getByLabelText(/Execution Host/i)).toBeInTheDocument();
    expect(screen.getByTestId('switch-input-sudo')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-minutes')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-note')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-overrides.snip0.path')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-overrides.snip0.threshold')).toBeInTheDocument();

    expectHelp('Execution Host', false);
    expectHelp('Run with sudo', true);
    expectHelp('Lookback minutes', true);
    expectHelp('Operator note', false);
    expectHelp('Path', true);
    expectHelp('Threshold %', false);
  });

  it('dipper-like collector form: icons follow payload parameter descriptions', () => {
    // Shape of a Dipper pcs-collect-pmm-* payload: mixed types whose descriptions
    // come from the script frontmatter. Extra tag is undescribed on purpose to
    // assert the negative case (real payloads usually describe every parameter).
    const sections: FormSection[] = [
      {
        title: 'Parameters',
        fields: [
          {
            type: 'string',
            name: 'pmmserver',
            label: 'PMM server URL',
            description:
              'Base URL of PMM server. Leave empty to use configured default (PMM.ENDPOINT).',
          },
          {
            type: 'string',
            name: 'node',
            label: 'Node name',
            description: 'Node name of audit target (required unless using --list).',
          },
          {
            type: 'bool',
            name: 'list',
            label: 'List services',
            description: 'List nodes and services on the PMM server instead of collecting graphs.',
          },
          {
            type: 'integer',
            name: 'width',
            label: 'Image width',
            description: 'Width of images in pixels.',
            default: 1280,
          },
          {
            type: 'datetime',
            name: 'start',
            label: 'Start time (UTC)',
            description: 'Starting timestamp for graph data. Defaults to 24h ago.',
          },
          { type: 'string', name: 'extra_tag', label: 'Extra tag' },
        ],
      },
    ];

    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);

    expect(screen.getByTestId('text-input-pmmserver')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-node')).toBeInTheDocument();
    expect(screen.getByTestId('switch-input-list')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-width')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-start')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-extra_tag')).toBeInTheDocument();

    expectHelp('PMM server URL', true);
    expectHelp('Node name', true);
    expectHelp('List services', true);
    expectHelp('Image width', true);
    expectHelp('Start time (UTC)', true);
    expectHelp('Extra tag', false);
  });

  it('snippet-execution form: user-authored params drive help icons (snippets + alert_troubleshooting)', () => {
    // Widest-reach consumer via SnippetExecutionAccordion. Parameter descriptions
    // come from snippet YAML frontmatter (not a fixed backend model); Execution
    // adds framework controls — sudo carries a description when present, the host does not.
    const sections: FormSection[] = [
      {
        title: 'Parameters',
        fields: [
          {
            type: 'string',
            name: 'table_name',
            label: 'Table Name',
            description: 'Table to inspect on the executor host.',
          },
          { type: 'string', name: 'database_name', label: 'Database Name' },
          {
            type: 'choice',
            name: 'format',
            label: 'Output format',
            description: 'How to render the snippet result.',
            // >3 choices use the select shell (help icon); ≤3 use radios + caption.
            choices: [
              { label: 'Plain text', value: 'text' },
              { label: 'JSON', value: 'json' },
              { label: 'CSV', value: 'csv' },
              { label: 'YAML', value: 'yaml' },
            ],
          },
          {
            type: 'bool',
            name: 'verbose',
            label: 'Verbose',
            description: 'Increase output verbosity.',
          },
          { type: 'integer', name: 'limit', label: 'Row limit' },
        ],
      },
      {
        title: 'Execution',
        fields: [
          { type: 'host', name: 'executor_host', label: 'Execution Host', required: true },
          {
            type: 'bool',
            name: 'sudo',
            label: 'Run with sudo',
            description: 'Prepend sudo to the interpreter when the snippet is executed.',
          },
        ],
      },
    ];

    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);

    expect(screen.getByTestId('text-input-table_name')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-database_name')).toBeInTheDocument();
    expect(screen.getByTestId('select-format-button')).toBeInTheDocument();
    expect(screen.getByTestId('switch-input-verbose')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-limit')).toBeInTheDocument();
    expect(screen.getByLabelText(/Execution Host/i)).toBeInTheDocument();
    expect(screen.getByTestId('switch-input-sudo')).toBeInTheDocument();

    expectHelp('Table Name', true);
    expectHelp('Database Name', false);
    expectHelp('Output format', true);
    expectHelp('Verbose', true);
    expectHelp('Row limit', false);
    expectHelp('Execution Host', false);
    expectHelp('Run with sudo', true);
  });
});
