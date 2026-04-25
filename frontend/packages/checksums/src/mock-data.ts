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
