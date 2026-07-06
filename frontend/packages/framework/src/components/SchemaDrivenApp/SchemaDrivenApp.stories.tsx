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

import type { ComponentType } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import Alert from '@mui/material/Alert';
import Paper from '@mui/material/Paper';
import type { AppSchema } from '@sep/api';
import { SchemaDrivenApp } from './SchemaDrivenApp';
import type { RenderFormSlot } from './types';
import { SchemaFormRenderer } from '../SchemaFormRenderer';

const mockSchema: AppSchema = {
  pluginName: 'checksums',
  display_name: 'Checksum',
  description: 'Consistency checks',
  capabilities: {},
  list_view: { columns: [{ key: 'name', label: 'Name' }] },
  forms: [
    {
      title: 'Task',
      fields: [
        { type: 'string', name: 'name', label: 'Name', required: true },
        { type: 'integer', name: 'timeout', label: 'Timeout (s)', default: 60 },
      ],
    },
  ],
} as unknown as AppSchema;

// The edit route is registered only for multi-entity apps, so the
// renderEditForm story needs an entity-backed schema (vs. the single-entity
// `mockSchema` the create story uses).
const mockEntitySchema: AppSchema = {
  pluginName: 'inventory',
  display_name: 'Inventory',
  capabilities: {},
  entities: [
    {
      name: 'nodes',
      display_name: 'Node',
      forms: [
        {
          title: 'Node',
          fields: [
            { type: 'string', name: 'label', label: 'Label', required: true },
            { type: 'integer', name: 'timeout', label: 'Timeout (s)', default: 60 },
          ],
        },
      ],
      list_view: { columns: [{ key: 'label', label: 'Label' }] },
    },
  ],
} as unknown as AppSchema;

const withProviders = (initialPath: string) => (Story: ComponentType) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <SnackbarProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <Story />
        </MemoryRouter>
      </SnackbarProvider>
    </QueryClientProvider>
  );
};

const meta: Meta<typeof SchemaDrivenApp> = {
  title: 'Framework/SchemaDrivenApp',
  component: SchemaDrivenApp,
  parameters: { layout: 'padded' },
};
export default meta;

type Story = StoryObj<typeof SchemaDrivenApp>;

/**
 * `renderCreateForm` whole-form slot (SEP-1355). The framework keeps the route,
 * page chrome (back button + title), the create mutation, and the snackbars;
 * only the form body is replaced. Here the slot adds a custom banner above a
 * composed `SchemaFormRenderer`, and submits through the framework `onSubmit`.
 */
const renderCreateForm: RenderFormSlot = ({
  sections,
  onSubmit,
  loading,
  defaultValues,
  capabilities,
  renderField,
}) => (
  <Paper variant="outlined" sx={{ p: 2 }}>
    <Alert severity="info" sx={{ mb: 2 }}>
      Custom create form provided by a app via the renderCreateForm slot.
    </Alert>
    <SchemaFormRenderer
      sections={sections}
      onSubmit={onSubmit}
      loading={loading}
      defaultValues={defaultValues}
      capabilities={capabilities}
      renderField={renderField}
      submitLabel="Create checksum"
    />
  </Paper>
);

export const WithRenderCreateFormSlot: Story = {
  args: { pluginName: 'checksums', mockSchema, mockTasks: [], renderCreateForm },
  decorators: [withProviders('/new')],
};

/**
 * `renderEditForm` whole-form slot (SEP-1355). Mirrors `renderCreateForm`: the
 * framework keeps the route, page chrome (back button + title), the update
 * mutation, and the snackbars; only the form body is replaced. The edit route
 * is multi-entity only, so this story uses `mockEntitySchema`, seeds the edited
 * row via `mockEntityItems`, and renders at the `/<entity>/<id>/edit` route.
 */
const renderEditForm: RenderFormSlot = ({
  sections,
  onSubmit,
  loading,
  defaultValues,
  renderField,
}) => (
  <Paper variant="outlined" sx={{ p: 2 }}>
    <Alert severity="info" sx={{ mb: 2 }}>
      Custom edit form provided by a app via the renderEditForm slot.
    </Alert>
    <SchemaFormRenderer
      sections={sections}
      onSubmit={onSubmit}
      loading={loading}
      defaultValues={defaultValues}
      renderField={renderField}
      submitLabel="Save changes"
    />
  </Paper>
);

export const WithRenderEditFormSlot: Story = {
  args: {
    pluginName: 'inventory',
    mockSchema: mockEntitySchema,
    mockTasks: [],
    mockEntityItems: { nodes: [{ id: '5', label: 'n1', timeout: 60 }] },
    renderEditForm,
  },
  decorators: [withProviders('/nodes/5/edit')],
};
