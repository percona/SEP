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
import { cascadeParentResetKey } from './cascadeParentResetKey';

describe('cascadeParentResetKey', () => {
  it('keys hydrated options and numeric ids as id:', () => {
    expect(cascadeParentResetKey({ id: 7, name: 'svc' })).toBe('id:7');
    expect(cascadeParentResetKey(7)).toBe('id:7');
    expect(cascadeParentResetKey('7')).toBe('id:7');
  });

  it('keys free-typed non-id strings as custom:', () => {
    expect(cascadeParentResetKey('my-cluster')).toBe('custom:my-cluster');
  });

  it('keys missing parents as id:none', () => {
    expect(cascadeParentResetKey(null)).toBe('id:none');
    expect(cascadeParentResetKey(undefined)).toBe('id:none');
    expect(cascadeParentResetKey('')).toBe('id:none');
    expect(cascadeParentResetKey({ id: null })).toBe('id:none');
  });
});
