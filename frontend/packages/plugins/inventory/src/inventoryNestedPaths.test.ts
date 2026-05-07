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
import {
  inventoryMountPrefix,
  parseNestedInventoryPath,
  pathThroughPairIndex,
  pathToNestedInventoryParent,
} from './inventoryNestedPaths';

describe('inventoryNestedPaths', () => {
  it('inventoryMountPrefix extracts prefix ending at inventory segment', () => {
    expect(inventoryMountPrefix('/inventory/nodes')).toBe('/inventory');
    expect(inventoryMountPrefix('/schema-change/inventory/nodes')).toBe('/schema-change/inventory');
    expect(inventoryMountPrefix('/no-inventory-here')).toBe('');
  });

  it('parseNestedInventoryPath parses nested trail starting at nodes', () => {
    const prefix = '/inventory';
    const pathname = '/inventory/nodes/1/services/2/schemas/3/tables/4';
    const parsed = parseNestedInventoryPath(pathname, prefix);
    expect(parsed).not.toBeNull();
    expect(parsed!.pairs).toEqual([
      { entity: 'nodes', id: '1' },
      { entity: 'services', id: '2' },
      { entity: 'schemas', id: '3' },
      { entity: 'tables', id: '4' },
    ]);
    expect(parsed!.entityName).toBe('tables');
    expect(parsed!.id).toBe('4');
  });

  it('pathThroughPairIndex builds cumulative nested URLs', () => {
    const prefix = '/inventory';
    const pairs = [
      { entity: 'nodes', id: '1' },
      { entity: 'services', id: '2' },
      { entity: 'schemas', id: '3' },
    ];
    expect(pathThroughPairIndex(prefix, pairs, 0)).toBe('/inventory');
    expect(pathThroughPairIndex(prefix, pairs, 1)).toBe('/inventory/nodes/1');
    expect(pathThroughPairIndex(prefix, pairs, 3)).toBe('/inventory/nodes/1/services/2/schemas/3');
  });

  it('pathToNestedInventoryParent strips last entity/id pair from deep nested trail', () => {
    const prefix = '/inventory';
    const pathname = '/inventory/nodes/1/services/2/schemas/3/tables/4';
    expect(pathToNestedInventoryParent(pathname, prefix)).toBe(
      '/inventory/nodes/1/services/2/schemas/3',
    );
  });

  it('pathToNestedInventoryParent from node detail goes to nodes list', () => {
    const prefix = '/inventory';
    expect(pathToNestedInventoryParent('/inventory/nodes/7', prefix)).toBe('/inventory/nodes');
  });
});
