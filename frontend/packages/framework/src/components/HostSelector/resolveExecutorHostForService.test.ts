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

import { describe, expect, it } from 'vitest';
import type { HostOption } from '../../hooks/useHosts';
import { resolveExecutorHostForService } from './resolveExecutorHostForService';

const hosts: HostOption[] = [
  { id: 'node-a', name: 'Display A', address: '10.0.0.1' },
  { id: 'node-b', name: 'Display B', address: '10.0.0.2' },
  { id: 'mongo-prod', name: 'Display Mongo', address: '10.0.0.9' },
];

describe('resolveExecutorHostForService', () => {
  it('prefers service.node.name matching a host id', () => {
    expect(
      resolveExecutorHostForService(hosts, {
        name: 'mongo-prod',
        node: { name: 'node-b', address: '10.0.0.1' },
      }),
    ).toEqual(hosts[1]);
  });

  it('falls back to service.node.address when node.name misses', () => {
    expect(
      resolveExecutorHostForService(hosts, {
        name: 'other',
        node: { name: 'unknown-node', address: '10.0.0.1' },
      }),
    ).toEqual(hosts[0]);
  });

  it('falls back to service.name matching a host id', () => {
    expect(
      resolveExecutorHostForService(hosts, {
        name: 'mongo-prod',
        node: { name: 'unknown', address: '10.9.9.9' },
      }),
    ).toEqual(hosts[2]);
  });

  it('returns undefined when nothing matches', () => {
    expect(
      resolveExecutorHostForService(hosts, {
        name: 'nope',
        node: { name: 'nope', address: '1.2.3.4' },
      }),
    ).toBeUndefined();
  });
});
