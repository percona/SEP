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
 * Spot-check: render SchemaFormRenderer with form shapes representative of
 * SchemaDrivenApp plugins that share this renderer (backup_mongo, alters,
 * archives-style tasks). Confirms help icons appear only on described fields
 * and core inputs still mount — a regression guard for the framework-global
 * label change. Apps that do not use SchemaFormRenderer (report, alerts list,
 * inventory browse, tasks list) are unaffected by this change.
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { SchemaFormRenderer } from './SchemaFormRenderer';
import type { FormSection } from './types';

vi.mock('@sep/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
  useAlertConfig: () => ({ data: undefined, isLoading: false }),
}));

function renderWithProviders(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function expectHelp(label: string, present: boolean) {
  const matches = screen.queryAllByLabelText(`Help for ${label}`);
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

  it('archives/tasks-style mixed section still renders selects + undescribed fields', () => {
    const sections: FormSection[] = [
      {
        title: 'Source',
        fields: [
          { type: 'integer', name: 'source_db_id', label: 'Source DB' },
          {
            type: 'choice',
            name: 'swap_drop',
            label: 'Swap Drop',
            description: 'Choose how tables are swapped after archive.',
            choices: [
              { label: 'Swap', value: 'swap' },
              { label: 'Drop', value: 'drop' },
              { label: 'None', value: 'none' },
              { label: 'Rename', value: 'rename' },
            ],
          },
          { type: 'string', name: 'where', label: 'Where' },
        ],
      },
    ];

    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);

    expect(screen.getByTestId('text-input-source_db_id')).toBeInTheDocument();
    expect(screen.getByTestId('select-swap_drop-button')).toBeInTheDocument();
    expect(screen.getByTestId('text-input-where')).toBeInTheDocument();
    expectHelp('Swap Drop', true);
    expectHelp('Source DB', false);
    expectHelp('Where', false);
  });
});
