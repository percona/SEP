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

const ENTITY_NAMES = new Set(['nodes', 'services', 'schemas', 'tables']);

export type NestedInventoryPair = { entity: string; id: string };

/** URL prefix ending at the ``inventory`` segment (e.g. ``/inventory`` or ``/schema-change/inventory``). */
export function inventoryMountPrefix(pathname: string): string {
  const parts = pathname.split('/').filter(Boolean);
  const idx = parts.lastIndexOf('inventory');
  if (idx < 0) {
    return '';
  }
  return `/${parts.slice(0, idx + 1).join('/')}`;
}

function tailAfterPrefix(pathname: string, prefix: string): string[] {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  if (!prefix || !normalized.startsWith(prefix)) {
    return [];
  }
  let tail = normalized.slice(prefix.length);
  if (tail.startsWith('/')) {
    tail = tail.slice(1);
  }
  return tail.split('/').filter(Boolean);
}

/**
 * Parse ``/…/nodes/1/services/2/schemas/3`` into alternating entity/id pairs.
 * Returns null if the path is not a valid nested inventory trail.
 */
export function parseNestedInventoryPath(
  pathname: string,
  prefix: string,
): { pairs: NestedInventoryPair[]; entityName: string; id: string } | null {
  const parts = tailAfterPrefix(pathname, prefix);
  if (parts.length < 2 || parts[0] !== 'nodes') {
    return null;
  }
  const pairs: NestedInventoryPair[] = [];
  for (let i = 0; i < parts.length - 1; i += 2) {
    const entity = parts[i];
    const id = parts[i + 1];
    if (!ENTITY_NAMES.has(entity) || !/^\d+$/.test(id)) {
      return null;
    }
    pairs.push({ entity, id });
  }
  if (pairs.length === 0) {
    return null;
  }
  const last = pairs[pairs.length - 1];
  return { pairs, entityName: last.entity, id: last.id };
}

/**
 * Parse flat ``/…/schemas/5`` (legacy) for breadcrumbs and flat detail routes.
 */
export function parseFlatInventoryRoute(
  pathname: string,
  prefix: string,
): { entityName?: string; id?: string } {
  const parts = tailAfterPrefix(pathname, prefix);
  while (parts.length > 0 && parts[parts.length - 1] === 'edit') {
    parts.pop();
  }
  if (parts.length === 0) {
    return {};
  }
  const entityName = parts[0];
  if (!ENTITY_NAMES.has(entityName)) {
    return {};
  }
  if (parts.length === 1) {
    return { entityName };
  }
  const second = parts[1];
  if (second === 'new') {
    return { entityName };
  }
  return { entityName, id: second };
}

/** Parent URL for nested inventory (strip last entity/id pair, or nodes list from node detail). */
export function pathToNestedInventoryParent(pathname: string, prefix: string): string {
  const norm = pathname.replace(/\/+$/, '') || '/';
  if (!prefix || !norm.startsWith(prefix)) {
    return norm;
  }
  const parts = tailAfterPrefix(norm, prefix);
  if (parts.length <= 2) {
    return `${prefix}/nodes`;
  }
  if (
    parts.length >= 4 &&
    ENTITY_NAMES.has(parts[parts.length - 2]!) &&
    /^\d+$/.test(parts[parts.length - 1]!)
  ) {
    return `${prefix}/${parts.slice(0, -2).join('/')}`;
  }
  return `${prefix}/nodes`;
}

/** Build nested path prefix up to and including the given pair index (0 = nodes). */
export function pathThroughPairIndex(
  prefix: string,
  pairs: NestedInventoryPair[],
  endExclusive: number,
): string {
  const slice = pairs.slice(0, endExclusive);
  if (slice.length === 0) {
    return prefix;
  }
  return `${prefix}/${slice.map((p) => `${p.entity}/${p.id}`).join('/')}`;
}

/** Back-compat alias for ``parseFlatInventoryRoute`` (pathname-based parsing outside inner ``Routes``). */
export const parseInventoryRoute = parseFlatInventoryRoute;
