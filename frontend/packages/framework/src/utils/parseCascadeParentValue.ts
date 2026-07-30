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

import { extractId } from './extractId';

export interface CascadeParentState {
  /** Inventory ids extracted from a scalar or multi-value parent field. */
  ids: number[];
  /** Non-empty free-typed strings with no resolved inventory id. */
  customValues: string[];
  /** Stable key for resetting children when the parent selection changes. */
  resetKey: string;
  /** Parent is absent — no ids and no custom values. */
  isMissing: boolean;
  /** Only free-typed parent values are present (no inventory ids). */
  isCustomOnly: boolean;
}

/**
 * Normalize a cascading selector's parent value.
 *
 * Parent fields may commit either a single scalar / option object (single-value
 * reference selectors) or a `(number | string)[]` (multi-value reference
 * selectors). Inventory ids are extracted from each element; when
 * `allowCustom` is set, non-id strings are treated as free-typed parent values.
 */
export function parseCascadeParentValue(
  parent: unknown,
  options?: { allowCustom?: boolean },
): CascadeParentState {
  const allowCustom = options?.allowCustom ?? false;
  const ids: number[] = [];
  const customValues: string[] = [];
  const keyParts: string[] = [];

  const absorb = (item: unknown) => {
    if (item === null || item === undefined || item === '') {
      return;
    }
    if (allowCustom && typeof item === 'string') {
      const text = item.trim();
      if (text !== '') {
        customValues.push(text);
        keyParts.push(`custom:${text}`);
      }
      return;
    }
    const id = extractId(item);
    if (id !== null) {
      ids.push(id);
      keyParts.push(`id:${id}`);
    }
  };

  if (Array.isArray(parent)) {
    for (const item of parent) {
      absorb(item);
    }
  } else {
    absorb(parent);
  }

  const uniqueIds = [...new Set(ids)];
  const isMissing = uniqueIds.length === 0 && customValues.length === 0;
  const isCustomOnly = uniqueIds.length === 0 && customValues.length > 0;

  return {
    ids: uniqueIds,
    customValues,
    resetKey: keyParts.sort().join('|') || 'none',
    isMissing,
    isCustomOnly,
  };
}
