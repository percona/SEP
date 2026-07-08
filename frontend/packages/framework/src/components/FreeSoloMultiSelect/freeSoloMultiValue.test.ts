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
  normalizeMultiChange,
  toDisplayValues,
  type MultiReferenceOption,
} from './freeSoloMultiValue';

const OPTIONS: MultiReferenceOption[] = [
  { id: 10, name: 'app_prod' },
  { id: 11, name: 'analytics' },
];

// Hosts carry string ids — a distinct branch from the numeric service/schema/table ids.
const HOST_OPTIONS: MultiReferenceOption[] = [
  { id: 'worker-1', name: 'Worker One' },
  { id: 'worker-2', name: 'Worker Two' },
];

const labelOf = (o: MultiReferenceOption) => o.name;

describe('toDisplayValues', () => {
  it('resolves stored numeric ids to their options', () => {
    expect(toDisplayValues([10, 11], OPTIONS)).toEqual([
      { id: 10, name: 'app_prod' },
      { id: 11, name: 'analytics' },
    ]);
  });

  it('keeps stored free strings verbatim', () => {
    expect(toDisplayValues(['custom_a', 'custom_b'], OPTIONS)).toEqual(['custom_a', 'custom_b']);
  });

  it('resolves a mixed [id, string] array', () => {
    expect(toDisplayValues([10, 'custom'], OPTIONS)).toEqual([
      { id: 10, name: 'app_prod' },
      'custom',
    ]);
  });

  it('resolves stored string ids to their options (host-style string ids)', () => {
    expect(toDisplayValues(['worker-1', 'worker-2'], HOST_OPTIONS)).toEqual([
      { id: 'worker-1', name: 'Worker One' },
      { id: 'worker-2', name: 'Worker Two' },
    ]);
  });

  it('resolves stored option objects (back-compat) to the matching option', () => {
    expect(toDisplayValues([{ id: 11, name: 'analytics' }], OPTIONS)).toEqual([
      { id: 11, name: 'analytics' },
    ]);
  });

  it('drops ids whose option has not loaded yet and empty entries', () => {
    expect(toDisplayValues([99, '', 10, '  '], OPTIONS)).toEqual([{ id: 10, name: 'app_prod' }]);
  });

  it('treats a non-array stored value as empty', () => {
    expect(toDisplayValues(null, OPTIONS)).toEqual([]);
    expect(toDisplayValues(undefined, OPTIONS)).toEqual([]);
    expect(toDisplayValues(10, OPTIONS)).toEqual([]);
  });
});

describe('normalizeMultiChange', () => {
  it('commits ids for picked option objects', () => {
    expect(normalizeMultiChange([{ id: 10, name: 'app_prod' }], OPTIONS, labelOf)).toEqual([10]);
  });

  it('commits string ids for picked host-style option objects', () => {
    expect(
      normalizeMultiChange([{ id: 'worker-1', name: 'Worker One' }], HOST_OPTIONS, labelOf),
    ).toEqual(['worker-1']);
  });

  it('keeps typed values with no matching option as strings', () => {
    expect(normalizeMultiChange(['brand_new'], OPTIONS, labelOf)).toEqual(['brand_new']);
  });

  it('resolves a typed value matching an option label to its id', () => {
    expect(normalizeMultiChange(['analytics'], OPTIONS, labelOf)).toEqual([11]);
  });

  it('normalizes a mixed array and drops empty entries', () => {
    expect(
      normalizeMultiChange(
        [{ id: 10, name: 'app_prod' }, 'custom', '   ', 'analytics'],
        OPTIONS,
        labelOf,
      ),
    ).toEqual([10, 'custom', 11]);
  });

  it('yields an empty array when nothing is selected', () => {
    expect(normalizeMultiChange([], OPTIONS, labelOf)).toEqual([]);
  });
});
