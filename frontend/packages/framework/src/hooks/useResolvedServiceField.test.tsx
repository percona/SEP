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

import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FormProvider, useForm } from 'react-hook-form';
import type { PropsWithChildren, ReactNode } from 'react';
import { FormFieldsProvider } from '../components/SchemaFormRenderer/formFieldsContext';
import type { AppField } from '../components/SchemaFormRenderer/types';
import { useResolvedServiceField } from './useResolvedServiceField';

vi.mock('@sep/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@sep/api')>()),
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
import { apiClient } from '@sep/api';
const mocked = apiClient as unknown as { get: ReturnType<typeof vi.fn> };

const SERVICE_FIELDS: AppField[] = [
  {
    type: 'service',
    name: 'service_id',
    label: 'Database Service',
    required: true,
    service_types: ['mongodb'],
  },
];

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

function harness(defaultServiceId: unknown, fields: AppField[] = SERVICE_FIELDS) {
  const client = makeClient();
  return function Wrapper({ children }: PropsWithChildren): ReactNode {
    const methods = useForm({ defaultValues: { service_id: defaultServiceId } });
    return (
      <QueryClientProvider client={client}>
        <FormFieldsProvider value={fields}>
          <FormProvider {...methods}>{children}</FormProvider>
        </FormFieldsProvider>
      </QueryClientProvider>
    );
  };
}

describe('useResolvedServiceField', () => {
  beforeEach(() => {
    mocked.get.mockReset();
  });

  it('returns a hydrated service option without fetching', () => {
    const { result } = renderHook(() => useResolvedServiceField('service_id'), {
      wrapper: harness({ id: 7, name: 'Alpha Cluster', type: 'mongodb' }),
    });

    expect(result.current.isResolving).toBe(false);
    expect(result.current.service?.name).toBe('Alpha Cluster');
    expect(result.current.resetKey).toBe('id:7');
    expect(mocked.get).not.toHaveBeenCalled();
  });

  it('rehydrates a scalar service id via useServices', async () => {
    mocked.get.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
      if (url === '/sep/services/') {
        expect(config?.params).toMatchObject({ service_type: 'mongodb' });
        return Promise.resolve({
          data: {
            items: [
              {
                id: 7,
                name: 'Alpha Cluster',
                type: 'mongodb',
                node: { name: 'node-a', address: '10.0.0.1', type: 'generic' },
                node_id: 1,
                schemas: [],
              },
            ],
            total: 1,
            offset: 0,
            limit: 200,
          },
        });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });

    const { result } = renderHook(() => useResolvedServiceField('service_id'), {
      wrapper: harness(7),
    });

    expect(result.current.isResolving).toBe(true);
    expect(result.current.resetKey).toBe('id:7');

    await waitFor(() => {
      expect(result.current.isResolving).toBe(false);
      expect(result.current.service?.name).toBe('Alpha Cluster');
    });
  });
});
