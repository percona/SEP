import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FormProvider, useForm } from 'react-hook-form';
import type { PropsWithChildren } from 'react';
import { ServiceSelector } from './ServiceSelector';

vi.mock('@sep/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
import { apiClient } from '@sep/api';
const mocked = apiClient as unknown as { get: ReturnType<typeof vi.fn> };

function makePage(items: Array<{ id: number; name: string; type: string }>) {
  return { data: { items, total: items.length, offset: 0, limit: 200 } };
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

function Harness({ serviceTypes }: { serviceTypes?: readonly string[] }) {
  const methods = useForm({ defaultValues: { service: null } });
  return (
    <FormProvider {...methods}>
      <ServiceSelector name="service" label="Service" serviceTypes={serviceTypes as never} />
    </FormProvider>
  );
}

function Wrapper({ children, client }: PropsWithChildren<{ client: QueryClient }>) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('ServiceSelector', () => {
  beforeEach(() => {
    mocked.get.mockReset();
  });

  it('fetches services and renders options', async () => {
    mocked.get.mockResolvedValueOnce(
      makePage([
        { id: 1, name: 'mysql-prod', type: 'mysql' },
        { id: 2, name: 'pg-prod', type: 'postgresql' },
      ]),
    );

    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness />
      </Wrapper>,
    );

    await waitFor(() =>
      expect(mocked.get).toHaveBeenCalledWith('/api/inventory/services/', {
        params: { offset: 0, limit: 200 },
      }),
    );

    const user = userEvent.setup();
    await user.click(screen.getByLabelText('Service'));
    expect(await screen.findByText('mysql-prod (mysql)')).toBeInTheDocument();
    expect(screen.getByText('pg-prod (postgresql)')).toBeInTheDocument();
  });

  it('passes serviceTypes filter as query param', async () => {
    mocked.get.mockResolvedValueOnce(makePage([{ id: 1, name: 'mysql-prod', type: 'mysql' }]));

    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness serviceTypes={['mysql']} />
      </Wrapper>,
    );

    await waitFor(() =>
      expect(mocked.get).toHaveBeenCalledWith('/api/inventory/services/', {
        params: { offset: 0, limit: 200, service_type: 'mysql' },
      }),
    );
  });

  it('renders error state', async () => {
    mocked.get.mockRejectedValueOnce(new Error('boom'));
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness />
      </Wrapper>,
    );
    await screen.findByText('boom');
  });

  it('renders empty state', async () => {
    mocked.get.mockResolvedValueOnce(makePage([]));
    const client = makeClient();
    render(
      <Wrapper client={client}>
        <Harness />
      </Wrapper>,
    );
    await screen.findByText('No services available');
  });
});
