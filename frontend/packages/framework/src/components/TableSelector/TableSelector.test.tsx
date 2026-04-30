import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FormProvider, useForm } from 'react-hook-form';
import type { PropsWithChildren } from 'react';
import { TableSelector } from './TableSelector';
import type { SchemaOption } from '../../hooks/useSchemas';
import type { TableOption } from '../../hooks/useTables';

vi.mock('@sep/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
import { apiClient } from '@sep/api';
const mocked = apiClient as unknown as { get: ReturnType<typeof vi.fn> };

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

interface FormShape {
  schema: SchemaOption | null;
  table: TableOption | null;
}

function Wrapper({ children, client }: PropsWithChildren<{ client: QueryClient }>) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function Harness({ initialSchema }: { initialSchema: SchemaOption | null }) {
  const methods = useForm<FormShape>({
    defaultValues: { schema: initialSchema, table: null },
  });
  return (
    <FormProvider {...methods}>
      <TableSelector name="table" label="Table" dependsOn="schema" />
    </FormProvider>
  );
}

describe('TableSelector', () => {
  beforeEach(() => {
    mocked.get.mockReset();
  });

  it('disabled with no schema', () => {
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness initialSchema={null} />
      </Wrapper>,
    );
    expect(screen.getByLabelText('Table')).toBeDisabled();
    expect(screen.getByText('Select a schema first')).toBeInTheDocument();
    expect(mocked.get).not.toHaveBeenCalled();
  });

  it('fetches tables when schema set', async () => {
    mocked.get.mockResolvedValueOnce({
      data: [
        { id: 100, name: 'users' },
        { id: 101, name: 'orders' },
      ],
    });
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness initialSchema={{ id: 42, name: 'app_prod' }} />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(mocked.get).toHaveBeenCalledWith('/inventory-api/schemas/42/tables'),
    );
  });

  it('resets value when parent schema changes', async () => {
    mocked.get.mockResolvedValue({ data: [{ id: 1, name: 't' }] });
    const client = makeClient();
    let setSchema!: (s: SchemaOption | null) => void;

    function Probe() {
      const methods = useForm<FormShape>({
        defaultValues: { schema: { id: 1, name: 's' }, table: { id: 9, name: 'pre' } },
      });
      setSchema = (s) => methods.setValue('schema', s);
      return (
        <FormProvider {...methods}>
          <TableSelector name="table" label="Table" dependsOn="schema" />
          <output data-testid="table-value">{JSON.stringify(methods.watch('table'))}</output>
        </FormProvider>
      );
    }

    render(
      <Wrapper client={client}>
        <Probe />
      </Wrapper>,
    );

    expect(screen.getByTestId('table-value').textContent).toContain('pre');

    await act(async () => {
      setSchema({ id: 2, name: 's2' });
    });

    await waitFor(() => {
      expect(screen.getByTestId('table-value').textContent).toBe('null');
    });
  });

  it('renders error state', async () => {
    mocked.get.mockRejectedValueOnce(new Error('tables down'));
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness initialSchema={{ id: 1, name: 's' }} />
      </Wrapper>,
    );
    await screen.findByText('tables down');
  });

  it('renders empty state', async () => {
    mocked.get.mockResolvedValueOnce({ data: [] });
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness initialSchema={{ id: 1, name: 's' }} />
      </Wrapper>,
    );
    await screen.findByText('No tables in this schema');
  });
});
