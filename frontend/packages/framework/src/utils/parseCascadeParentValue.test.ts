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
import { parseCascadeParentValue } from './parseCascadeParentValue';

describe('parseCascadeParentValue', () => {
  it('extracts a single inventory id from a scalar parent', () => {
    expect(parseCascadeParentValue(42)).toEqual({
      ids: [42],
      customValues: [],
      resetKey: 'id:42',
      isMissing: false,
      isCustomOnly: false,
    });
  });

  it('extracts inventory ids from a multi-value parent array', () => {
    expect(parseCascadeParentValue([1, 2, 1])).toEqual({
      ids: [1, 2],
      customValues: [],
      resetKey: 'id:1|id:1|id:2',
      isMissing: false,
      isCustomOnly: false,
    });
  });

  it('treats free-typed strings as custom values when allowCustom is set', () => {
    expect(parseCascadeParentValue(['testdb'], { allowCustom: true })).toEqual({
      ids: [],
      customValues: ['testdb'],
      resetKey: 'custom:testdb',
      isMissing: false,
      isCustomOnly: true,
    });
  });

  it('keeps numeric strings as custom values when allowCustom is set', () => {
    expect(parseCascadeParentValue('42', { allowCustom: true })).toEqual({
      ids: [],
      customValues: ['42'],
      resetKey: 'custom:42',
      isMissing: false,
      isCustomOnly: true,
    });
  });

  it('marks an empty array as missing', () => {
    expect(parseCascadeParentValue([])).toEqual({
      ids: [],
      customValues: [],
      resetKey: 'none',
      isMissing: true,
      isCustomOnly: false,
    });
  });
});
