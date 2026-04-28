import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect } from 'react';
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

function installFetchMock() {
  if ((globalThis as { __sepCascadeMock?: boolean }).__sepCascadeMock) {
    return;
  }
  (globalThis as { __sepCascadeMock?: boolean }).__sepCascadeMock = true;
  const realFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (url.includes('/api/inventory/services/')) {
      return new Response(JSON.stringify(SERVICES), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const schemaMatch = url.match(/\/inventory-api\/services\/(\d+)\/schemas/);
    if (schemaMatch) {
      const id = Number(schemaMatch[1]);
      return new Response(JSON.stringify(SCHEMAS_BY_SERVICE[id] ?? []), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const tableMatch = url.match(/\/inventory-api\/schemas\/(\d+)\/tables/);
    if (tableMatch) {
      const id = Number(tableMatch[1]);
      return new Response(JSON.stringify(TABLES_BY_SCHEMA[id] ?? []), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return realFetch(input, init);
  }) as typeof fetch;
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
  useEffect(() => {
    installFetchMock();
  }, []);

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
};
export default meta;

type Story = StoryObj<typeof CascadeDemo>;

export const AllServiceTypes: Story = { args: {} };

export const MySQLOnly: Story = { args: { serviceTypes: ['mysql'] } };

export const PostgresOnly: Story = { args: { serviceTypes: ['postgresql'] } };
