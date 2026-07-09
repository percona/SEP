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
import { FormProvider, useForm, useWatch } from 'react-hook-form';
import Stack from '@mui/material/Stack';
import { ServiceSelector } from './ServiceSelector';
import { SchemaSelector } from '../SchemaSelector';
import { TableSelector } from '../TableSelector';

interface CascadeForm {
  service: { id: number; name: string; type: string } | null;
  schema: { id: number; name: string } | null;
  table: { id: number; name: string } | null;
}

const SERVICES = {
  items: [
    { id: 1, name: 'mysql-prod-1', type: 'mysql' },
    { id: 2, name: 'mysql-staging-1', type: 'mysql' },
    { id: 3, name: 'pg-prod-1', type: 'postgresql' },
    { id: 4, name: 'mongo-prod-1', type: 'mongodb' },
  ],
  total: 4,
  offset: 0,
  limit: 200,
};

const SCHEMAS_BY_SERVICE: Record<number, Array<{ id: number; name: string }>> = {
  1: [
    { id: 11, name: 'app_prod' },
    { id: 12, name: 'analytics' },
  ],
  2: [{ id: 21, name: 'app_staging' }],
  3: [
    { id: 31, name: 'public' },
    { id: 32, name: 'reporting' },
  ],
  4: [],
};

const TABLES_BY_SCHEMA: Record<number, Array<{ id: number; name: string }>> = {
  11: [
    { id: 111, name: 'users' },
    { id: 112, name: 'orders' },
  ],
  12: [{ id: 121, name: 'events' }],
  21: [{ id: 211, name: 'users' }],
  31: [
    { id: 311, name: 'accounts' },
    { id: 312, name: 'transactions' },
  ],
  32: [],
};

// Build the per-URL response map consumed by the storybook fetch wrapper.
// Matching is longest-prefix, so the per-id paths take precedence over the
// generic `/api/sep/services/` services-list registration.
const cascadeFetchResponses: Record<string, unknown> = {
  '/api/sep/services/': SERVICES,
};
for (const [serviceId, list] of Object.entries(SCHEMAS_BY_SERVICE)) {
  cascadeFetchResponses[`/sep/services/${serviceId}/schemas`] = list;
}
for (const [schemaId, list] of Object.entries(TABLES_BY_SCHEMA)) {
  cascadeFetchResponses[`/sep/schemas/${schemaId}/tables`] = list;
}

function CurrentValues() {
  const value = useWatch<CascadeForm>();
  return (
    <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, fontSize: 12 }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function CascadeDemo({ serviceTypes }: { serviceTypes?: string[] }) {
  const methods = useForm<CascadeForm>({
    defaultValues: { service: null, schema: null, table: null },
  });

  return (
    <FormProvider {...methods}>
      <Stack spacing={2} sx={{ maxWidth: 480, p: 2 }}>
        <ServiceSelector name="service" label="Service" serviceTypes={serviceTypes as never} />
        <SchemaSelector name="schema" label="Schema" dependsOn="service" />
        <TableSelector name="table" label="Table" dependsOn="schema" />
        <CurrentValues />
      </Stack>
    </FormProvider>
  );
}

const meta: Meta<typeof CascadeDemo> = {
  title: 'Selectors/CascadingSelectors',
  component: CascadeDemo,
  parameters: { fetchResponses: cascadeFetchResponses },
};
export default meta;

type Story = StoryObj<typeof CascadeDemo>;

export const AllServiceTypes: Story = { args: {} };

export const MySQLOnly: Story = { args: { serviceTypes: ['mysql'] } };

export const PostgresOnly: Story = { args: { serviceTypes: ['postgresql'] } };
