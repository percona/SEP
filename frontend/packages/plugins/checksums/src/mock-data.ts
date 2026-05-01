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
 * Mock checksum tasks for development.
 *
 * In production the generic usePluginTasks hook fetches real data from
 * GET /api/plugins/checksums/ — this mock is bypassed.
 */
export const mockChecksumTasks = [
  {
    id: 1,
    service: 'prod-db-01',
    schema: 'orders',
    status: 'completed',
    differences: 0,
    last_run: '2026-04-09T10:30:00Z',
    chunk_size: 1000,
    replicate_check: true,
  },
  {
    id: 2,
    service: 'prod-db-01',
    schema: 'users',
    status: 'completed',
    differences: 3,
    last_run: '2026-04-09T09:15:00Z',
    chunk_size: 5000,
    replicate_check: true,
  },
  {
    id: 3,
    service: 'prod-db-02',
    schema: '*',
    status: 'running',
    differences: 0,
    last_run: '2026-04-09T11:00:00Z',
    chunk_size: 1000,
    replicate_check: false,
  },
  {
    id: 4,
    service: 'staging-db-01',
    schema: 'inventory',
    status: 'failed',
    differences: 0,
    last_run: '2026-04-08T22:00:00Z',
    chunk_size: 10000,
    replicate_check: true,
  },
  {
    id: 5,
    service: 'prod-db-03',
    schema: 'analytics',
    status: 'completed',
    differences: 0,
    last_run: '2026-04-08T18:45:00Z',
    chunk_size: 1000,
    replicate_check: true,
  },
] as const;
