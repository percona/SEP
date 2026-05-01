import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FormProvider, useForm } from 'react-hook-form';
import type { PropsWithChildren } from 'react';
import { SchemaSelector } from './SchemaSelector';
import type { ServiceOption } from '../../hooks/useServices';
import type { SchemaOption } from '../../hooks/useSchemas';

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
  service: ServiceOption | null;
  schema: SchemaOption | null;
}

function Harness({
  initialService,
  onMount,
}: {
  initialService: ServiceOption | null;
  onMount?: (api: { setService: (s: ServiceOption | null) => void }) => void;
}) {
  const methods = useForm<FormShape>({
    defaultValues: { service: initialService, schema: null },
  });
  if (onMount) {
    onMount({ setService: (s) => methods.setValue('service', s) });
  }
  return (
    <FormProvider {...methods}>
      <SchemaSelector name="schema" label="Schema" dependsOn="service" />
    </FormProvider>
  );
}

function Wrapper({ children, client }: PropsWithChildren<{ client: QueryClient }>) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('SchemaSelector', () => {
  beforeEach(() => {
    mocked.get.mockReset();
  });

  it('is disabled and skips fetch when no service selected', async () => {
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness initialService={null} />
      </Wrapper>,
    );
    expect(screen.getByLabelText('Schema')).toBeDisabled();
    expect(screen.getByText('Select a service first')).toBeInTheDocument();
    expect(mocked.get).not.toHaveBeenCalled();
  });

  it('fetches schemas when service is set', async () => {
    mocked.get.mockResolvedValueOnce({
      data: [
        { id: 10, name: 'app_prod' },
        { id: 11, name: 'analytics' },
      ],
    });

    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness initialService={{ id: 7, name: 'svc', type: 'mysql' }} />
      </Wrapper>,
    );

    await waitFor(() =>
      expect(mocked.get).toHaveBeenCalledWith('/inventory-api/services/7/schemas'),
    );
  });

  it('resets value when parent service changes', async () => {
    mocked.get.mockResolvedValue({ data: [{ id: 1, name: 'a' }] });
    const client = makeClient();
    const apiRef: { current: ((s: ServiceOption | null) => void) | null } = { current: null };
    const initial: ServiceOption = { id: 1, name: 's1', type: 'mysql' };

    function Probe() {
      const methods = useForm<FormShape>({
        defaultValues: { service: initial, schema: { id: 99, name: 'pre-existing' } },
      });
      apiRef.current = (s) => methods.setValue('service', s);
      return (
        <FormProvider {...methods}>
          <SchemaSelector name="schema" label="Schema" dependsOn="service" />
          <output data-testid="schema-value">{JSON.stringify(methods.watch('schema'))}</output>
        </FormProvider>
      );
    }

    render(
      <Wrapper client={client}>
        <Probe />
      </Wrapper>,
    );

    expect(screen.getByTestId('schema-value').textContent).toContain('pre-existing');

    await act(async () => {
      apiRef.current?.({ id: 2, name: 's2', type: 'mysql' });
    });

    await waitFor(() => {
      expect(screen.getByTestId('schema-value').textContent).toBe('null');
    });
  });

  it('renders error state', async () => {
    mocked.get.mockRejectedValueOnce(new Error('schemas down'));
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness initialService={{ id: 1, name: 's', type: 'mysql' }} />
      </Wrapper>,
    );
    await screen.findByText('schemas down');
  });

  it('renders empty state', async () => {
    mocked.get.mockResolvedValueOnce({ data: [] });
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness initialService={{ id: 1, name: 's', type: 'mysql' }} />
      </Wrapper>,
    );
    await screen.findByText('No schemas in this service');
  });
});
