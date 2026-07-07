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
 * Array analogues of `freeSoloValue.ts` for the multi-value (`multiple`) path of
 * the reference selectors. A multi-value reference field collapses "pick several
 * from inventory" and "type new values" into one control; the committed
 * react-hook-form value is a `(number | string)[]` (mirroring the backend
 * `MultiServiceField` / `MultiSchemaField` / `MultiTableField` /
 * `MultiHostField` contract, whose `list[int | str]` element accepts either an
 * inventory id or a free-typed value under `allow_custom`).
 *
 * Option ids may be numbers (service / schema / table) or strings (host), so a
 * stored scalar resolves to an option whenever it matches an option's `id`
 * regardless of type; a scalar that matches no option and is a non-empty string
 * is a free-typed value.
 */

/** Minimal shape every multi-value reference option satisfies. */
export interface MultiReferenceOption {
  id: number | string;
  name: string;
}

/**
 * Resolve the stored react-hook-form array into the values MUI Autocomplete
 * should display:
 *
 *   - an option object (a back-compat / persisted shape) resolves to the
 *     matching option, falling back to the object itself;
 *   - a scalar that matches an option's `id` resolves to that option;
 *   - a non-empty string matching no option is shown as a free-typed value;
 *   - a scalar matching no option that is not a string (an id whose option is
 *     not loaded yet) is dropped, and empty entries are dropped.
 *
 * A non-array stored value (unset field) yields an empty array.
 */
export function toDisplayValues<T extends MultiReferenceOption>(
  stored: unknown,
  options: readonly T[],
): (T | string)[] {
  if (!Array.isArray(stored)) {
    return [];
  }
  const result: (T | string)[] = [];
  for (const item of stored) {
    if (item === null || item === undefined || item === '') {
      continue;
    }
    if (typeof item === 'object' && 'id' in (item as Record<string, unknown>)) {
      const id = (item as { id: unknown }).id;
      result.push(options.find((o) => o.id === id) ?? (item as T));
      continue;
    }
    const match = options.find((o) => o.id === item);
    if (match) {
      result.push(match);
    } else if (typeof item === 'string' && item.trim() !== '') {
      result.push(item.trim());
    }
  }
  return result;
}

/**
 * Normalize the array emitted by MUI Autocomplete's `onChange` into the
 * `(number | string)[]` committed to react-hook-form:
 *
 *   - an option object yields its `id`;
 *   - a typed string that exactly matches an option's label resolves to that
 *     option's `id` (not the string);
 *   - any other non-empty string is kept verbatim;
 *   - whitespace-only / empty strings are dropped.
 */
export function normalizeMultiChange<T extends MultiReferenceOption>(
  next: readonly (T | string)[],
  options: readonly T[],
  getOptionLabel: (option: T) => string,
): (number | string)[] {
  const result: (number | string)[] = [];
  for (const item of next) {
    if (typeof item === 'object') {
      result.push(item.id);
      continue;
    }
    const trimmed = item.trim();
    if (trimmed === '') {
      continue;
    }
    const match = options.find((o) => getOptionLabel(o) === trimmed);
    result.push(match ? match.id : trimmed);
  }
  return result;
}
