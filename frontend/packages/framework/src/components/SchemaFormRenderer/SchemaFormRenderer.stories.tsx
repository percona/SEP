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

import type { ComponentType, ReactNode } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { ALERT_CONFIG_QUERY_KEY } from '@sep/api';
import type { FormSection } from './types';
import { SchemaFormRenderer } from './SchemaFormRenderer';

const MULTI_SECTION_SCHEMA: FormSection[] = [
  {
    title: 'Task details',
    description: 'Identify this task and where it should run.',
    fields: [
      {
        type: 'string',
        name: 'title',
        label: 'Title',
        required: true,
        min_length: 3,
        max_length: 64,
        placeholder: 'Nightly consistency check',
      },
      {
        type: 'textarea',
        name: 'notes',
        label: 'Notes',
        rows: 3,
        description: 'Optional free-form notes for the runbook.',
      },
      {
        type: 'choice',
        name: 'priority',
        label: 'Priority',
        required: true,
        choices: [
          { label: 'Low', value: 'low' },
          { label: 'Normal', value: 'normal' },
          { label: 'High', value: 'high' },
        ],
      },
    ],
  },
  {
    title: 'Target',
    description: 'Service → schema → table cascade (dependent selectors).',
    fields: [
      {
        type: 'service',
        name: 'serviceId',
        label: 'Service',
        required: true,
        service_types: ['mysql', 'postgresql'],
      },
      {
        type: 'schema',
        name: 'schemaName',
        label: 'Schema',
        required: true,
        depends_on: 'serviceId',
      },
      {
        type: 'table',
        name: 'tableName',
        label: 'Table',
        required: true,
        depends_on: 'schemaName',
      },
    ],
  },
  {
    title: 'Execution',
    fields: [
      {
        type: 'integer',
        name: 'timeoutSeconds',
        label: 'Timeout (seconds)',
        ge: 1,
        le: 3600,
        default: 60,
      },
      {
        type: 'float',
        name: 'samplingRate',
        label: 'Sampling rate',
        ge: 0,
        le: 1,
        step: 0.01,
        default: 0.1,
      },
      { type: 'bool', name: 'dryRun', label: 'Dry run', default: true },
      {
        type: 'multichoice',
        name: 'tags',
        label: 'Tags',
        choices: [
          { label: 'Production', value: 'prod' },
          { label: 'Canary', value: 'canary' },
          { label: 'Compliance', value: 'compliance' },
        ],
      },
      {
        type: 'datetime',
        name: 'scheduledFor',
        label: 'Scheduled for',
      },
      {
        type: 'yaml',
        name: 'overrides',
        label: 'Config overrides',
        rows: 6,
        placeholder: 'key: value',
      },
    ],
  },
];

const withQueryClient = (Story: ComponentType) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <Story />
    </QueryClientProvider>
  );
};

function AlertConfigSeeder({ available, children }: { available: boolean; children: ReactNode }) {
  const queryClient = useQueryClient();
  queryClient.setQueryData(ALERT_CONFIG_QUERY_KEY, { available });
  return <>{children}</>;
}

function withAlertConfig(available: boolean) {
  return (Story: ComponentType) => (
    <AlertConfigSeeder available={available}>
      <Story />
    </AlertConfigSeeder>
  );
}

const SIMPLE_TASK_SECTIONS: FormSection[] = [
  {
    title: 'Task',
    fields: [{ type: 'string', name: 'task_name', label: 'Task Name', required: true }],
  },
];

const meta: Meta<typeof SchemaFormRenderer> = {
  title: 'Framework/SchemaFormRenderer',
  component: SchemaFormRenderer,
  decorators: [withQueryClient],
  parameters: { layout: 'padded' },
};
export default meta;

type Story = StoryObj<typeof SchemaFormRenderer>;

export const MultiSectionSchema: Story = {
  args: {
    sections: MULTI_SECTION_SCHEMA,
    submitLabel: 'Create task',
    onSubmit: (values: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log('submit', values);
    },
  },
};

export const WithSubmitError: Story = {
  args: {
    sections: MULTI_SECTION_SCHEMA.slice(0, 1),
    submitLabel: 'Retry',
    submitError: 'The API rejected this request: validation failed on the backend.',
    onSubmit: () => {},
  },
};

export const MinimalForm: Story = {
  args: {
    sections: [
      {
        title: 'Signup',
        fields: [
          { type: 'string', name: 'name', label: 'Name', required: true },
          { type: 'string', name: 'email', label: 'Email', required: true, pattern: '^.+@.+$' },
        ],
      },
    ],
    submitLabel: 'Submit',
    onSubmit: (v: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log(v);
    },
  },
};

export const ConditionalFields: Story = {
  args: {
    sections: [
      {
        title: 'Mode',
        description:
          'Toggle "Advanced mode" to reveal the hidden field. Check "Needs reason" to make Reason required.',
        fields: [
          { type: 'bool', name: 'advanced', label: 'Advanced mode' },
          {
            type: 'string',
            name: 'advancedOption',
            label: 'Advanced option (hidden when advanced=false)',
            description: 'Visible only when Advanced mode is on.',
            forbidden: [{ when: { falsy: 'advanced' } }],
          },
          { type: 'bool', name: 'needsReason', label: 'Needs reason' },
          {
            type: 'string',
            name: 'reason',
            label: 'Reason (dynamically required)',
            description: 'Required only when Needs reason is checked.',
            requires: [{ when: { truthy: 'needsReason' } }],
          },
        ],
      },
    ],
    submitLabel: 'Submit',
    onSubmit: (v: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log('submit', v);
    },
  },
};

/**
 * Mirrors the pt-online-schema-change (alters) plugin's Recursion section.
 * "DSN Table" is only needed when Recursion Method is "DSN" — otherwise it
 * is hidden and excluded from the submission payload.
 */
export const AltersRecursionMethod: Story = {
  args: {
    sections: [
      {
        title: 'Recursion',
        description: 'Select "DSN" as the recursion method to reveal the DSN Table field.',
        fields: [
          {
            type: 'choice',
            name: 'recursion_method',
            label: 'Recursion Method',
            required: true,
            choices: [
              { label: 'Default', value: 'default' },
              { label: 'Processlist', value: 'processlist' },
              { label: 'Hosts', value: 'hosts' },
              { label: 'DSN', value: 'dsn' },
              { label: 'None', value: 'none' },
            ],
          },
          {
            type: 'string',
            name: 'dsn_table',
            label: 'DSN Table',
            description: 'DSN table in D=db,t=table format (e.g. D=percona,t=dsns).',
            forbidden: [{ when: { not_equals: { recursion_method: 'dsn' } } }],
          },
        ],
      },
    ],
    submitLabel: 'Run alter',
    onSubmit: (v: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log('submit', v);
    },
  },
};

/**
 * Mirrors the pt-archiver (archives) plugin's purge-conditions section.
 * When Swap Drop = 1 (SWAP_DROP) the WHERE clause is forbidden — pt-archiver
 * selects all rows. Any other swap_drop value requires a WHERE clause.
 */
export const ArchivesSwapDrop: Story = {
  args: {
    sections: [
      {
        title: 'Purge conditions',
        description:
          'Set Swap Drop to 1 (SWAP_DROP) to hide the WHERE field. Any other value makes WHERE required.',
        fields: [
          {
            type: 'integer',
            name: 'swap_drop',
            label: 'Swap Drop',
            required: true,
            ge: 0,
            le: 2,
            description: '0 = no swap, 1 = SWAP_DROP (no WHERE), 2 = SWAP_ARCHIVE_DROP',
          },
          {
            type: 'string',
            name: 'where',
            label: 'WHERE Condition',
            description: 'SQL WHERE clause selecting rows to purge (e.g. id < 1000).',
            forbidden: [{ when: { equals: { swap_drop: 1 } } }],
            requires: [{ when: { not_equals: { swap_drop: 1 } } }],
          },
        ],
      },
    ],
    submitLabel: 'Run archive',
    onSubmit: (v: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log('submit', v);
    },
  },
};

/**
 * Combined end-to-end story covering all three section-level rule primitives
 * in a single realistic archives-like schema:
 *
 *  - cardinality_rule:  source_db_id XOR source_table_id (exactly one)
 *  - fail_when:         SWAP_DROP mode is incompatible with table-level source
 *  - forbidden + requires on `where`: hidden when swap_drop=1, required otherwise
 *
 * This is the "combined 5-validator" shape referenced in SEP-1077 AC #4 —
 * intended as living documentation for plugin authors migrating to Wave 2.
 */
export const ArchivesCombined: Story = {
  args: {
    sections: [
      {
        title: 'Archives — full rule set',
        description:
          'Fill exactly one source (DB or Table). Set swap_drop and configure the WHERE clause.',
        cardinality_rules: [
          {
            fields: ['source_db_id', 'source_table_id'],
            min: 1,
            max: 1,
            message: 'Specify exactly one source: either DB or Table, not both.',
          },
        ],
        fail_when: [
          {
            fail_when: {
              all: [{ equals: { swap_drop: 1 } }, { truthy: 'source_table_id' }],
            },
            error_fields: ['swap_drop', 'source_table_id'],
            message: 'SWAP_DROP mode (swap_drop=1) cannot be combined with a table-level source.',
          },
        ],
        fields: [
          {
            type: 'string',
            name: 'source_db_id',
            label: 'Source DB',
            description: 'Archive from an entire database.',
          },
          {
            type: 'string',
            name: 'source_table_id',
            label: 'Source Table',
            description: 'Archive from a single table.',
          },
          {
            type: 'integer',
            name: 'swap_drop',
            label: 'Swap Drop',
            required: true,
            ge: 0,
            le: 2,
            description: '0 = no swap, 1 = SWAP_DROP (no WHERE), 2 = SWAP_ARCHIVE_DROP',
          },
          {
            type: 'string',
            name: 'where',
            label: 'WHERE Condition',
            description: 'SQL WHERE clause selecting rows to purge (e.g. id < 1000).',
            forbidden: [{ when: { equals: { swap_drop: 1 } } }],
            requires: [{ when: { not_equals: { swap_drop: 1 } } }],
          },
        ],
      },
    ],
    submitLabel: 'Run archive',
    onSubmit: (v: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log('submit', v);
    },
  },
};

/**
 * Mirrors the pt-archiver source selection: exactly one of source_db_id or
 * source_table_id must be filled (XOR / exactly-one cardinality rule).
 * The error banner appears immediately when both are filled or both are empty.
 */
export const ArchivesSourceXor: Story = {
  args: {
    sections: [
      {
        title: 'Source',
        description: 'Fill exactly one of DB or Table as the archiver source.',
        cardinality_rules: [
          {
            fields: ['source_db_id', 'source_table_id'],
            min: 1,
            max: 1,
            message: 'Specify exactly one source: either DB or Table, not both.',
          },
        ],
        fields: [
          {
            type: 'string',
            name: 'source_db_id',
            label: 'Source DB',
            description: 'Archive from an entire database.',
          },
          {
            type: 'string',
            name: 'source_table_id',
            label: 'Source Table',
            description: 'Archive from a single table.',
          },
        ],
      },
    ],
    submitLabel: 'Run archive',
    onSubmit: (v: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log('submit', v);
    },
  },
};

/** Alert provider configured: checkbox is enabled and actionable. */
export const WithAlertCapabilityEnabled: Story = {
  decorators: [withAlertConfig(true)],
  args: {
    sections: SIMPLE_TASK_SECTIONS,
    capabilities: { alert_on_fail: true },
    submitLabel: 'Create task',
    onSubmit: (v: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log('submit', v);
    },
  },
};

/** No alert provider configured: checkbox is rendered but disabled with a tooltip. */
export const WithAlertCapabilityUnavailable: Story = {
  decorators: [withAlertConfig(false)],
  args: {
    sections: SIMPLE_TASK_SECTIONS,
    capabilities: { alert_on_fail: true },
    submitLabel: 'Create task',
    onSubmit: (v: Record<string, unknown>) => {
      // eslint-disable-next-line no-console
      console.log('submit', v);
    },
  },
};
