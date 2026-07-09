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

import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient, setTokenProvider } from '../src/client';
import { ApiError } from '../src/errors';
import {
  CONNECTIVITY_CHECK_PATH,
  type ConnectivityResult,
} from '../src/hooks/useConnectivityCheck';
import { server } from './msw-server';

const BASE = 'http://localhost';
// The mutationFn the hook runs: identical call so the contract is covered without RTL.
const runCheck = (body: { targets: string[] }) =>
  apiClient.post<ConnectivityResult[]>(CONNECTIVITY_CHECK_PATH, body).then((r) => r.data);

beforeEach(() => {
  apiClient.defaults.baseURL = `${BASE}/api`;
  setTokenProvider(() => 'admin-token');
});

afterEach(() => {
  setTokenProvider(() => null);
});

describe('useConnectivityCheck — request contract', () => {
  it('POSTs the targets body to the connectivity-check path (trailing slash) and returns the list', async () => {
    const seen = vi.fn();
    server.use(
      http.post(`${BASE}/api/sep/admin/connectivity-check/`, async ({ request }) => {
        seen({
          auth: request.headers.get('Authorization'),
          body: await request.json(),
        });
        return HttpResponse.json([
          { service: 'pmm', reachable: true, status: 'reachable', detail: 'OK', version: '2.4' },
        ] satisfies ConnectivityResult[]);
      }),
    );

    const result = await runCheck({ targets: ['pmm', 'inventory', 'tasks', 'nomad'] });

    expect(seen).toHaveBeenCalledWith({
      auth: 'Bearer admin-token',
      body: { targets: ['pmm', 'inventory', 'tasks', 'nomad'] },
    });
    expect(result).toEqual([
      { service: 'pmm', reachable: true, status: 'reachable', detail: 'OK', version: '2.4' },
    ]);
  });

  it('surfaces a non-2xx response as an ApiError (request-level failure)', async () => {
    server.use(
      http.post(`${BASE}/api/sep/admin/connectivity-check/`, () =>
        HttpResponse.json({ detail: 'Boom' }, { status: 500 }),
      ),
    );

    await expect(runCheck({ targets: ['pmm'] })).rejects.toBeInstanceOf(ApiError);
  });

  it('surfaces a transport-level failure as an ApiError (no HTTP response)', async () => {
    server.use(http.post(`${BASE}/api/sep/admin/connectivity-check/`, () => HttpResponse.error()));

    await expect(runCheck({ targets: ['pmm'] })).rejects.toBeInstanceOf(ApiError);
  });
});
