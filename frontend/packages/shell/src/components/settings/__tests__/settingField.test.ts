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
  formatSettingValue,
  getFieldKind,
  isEditable,
  isSaveable,
  parseLiteralOptions,
  toInitialEditValue,
  toPatchValue,
} from '../settingField';
import { makeSetting } from './fixtures';

describe('parseLiteralOptions', () => {
  it('extracts single-quoted union members', () => {
    expect(parseLiteralOptions("Literal['warn', 'fail', 'skip']")).toEqual([
      'warn',
      'fail',
      'skip',
    ]);
  });

  it('returns null for named enums and scalars', () => {
    expect(parseLiteralOptions('PreExecutionCheckMode')).toBeNull();
    expect(parseLiteralOptions('str')).toBeNull();
    expect(parseLiteralOptions('int')).toBeNull();
  });
});

describe('getFieldKind', () => {
  it('classifies by flags and type string', () => {
    expect(getFieldKind(makeSetting({ is_complex: true }))).toBe('complex');
    expect(getFieldKind(makeSetting({ is_secret: true, type: 'SecretStr' }))).toBe('secret');
    expect(getFieldKind(makeSetting({ type: 'bool' }))).toBe('bool');
    expect(getFieldKind(makeSetting({ type: 'int' }))).toBe('number');
    expect(getFieldKind(makeSetting({ type: 'float' }))).toBe('number');
    expect(getFieldKind(makeSetting({ type: "Literal['a', 'b']" }))).toBe('choice');
    expect(getFieldKind(makeSetting({ type: 'str' }))).toBe('text');
  });

  it('prioritises complex over secret', () => {
    expect(getFieldKind(makeSetting({ is_complex: true, is_secret: true }))).toBe('complex');
  });
});

describe('isEditable', () => {
  it('is true only for hot, non-complex fields', () => {
    expect(isEditable(makeSetting({ reload: 'hot' }))).toBe(true);
    expect(isEditable(makeSetting({ reload: 'not_overridable' }))).toBe(false);
    expect(isEditable(makeSetting({ reload: 'hot', is_complex: true }))).toBe(false);
  });
});

describe('formatSettingValue', () => {
  it('renders primitives, objects, and nullish values', () => {
    expect(formatSettingValue(null)).toBe('—');
    expect(formatSettingValue(undefined)).toBe('—');
    expect(formatSettingValue(true)).toBe('true');
    expect(formatSettingValue(42)).toBe('42');
    expect(formatSettingValue({ a: 1 })).toBe('{"a":1}');
  });
});

describe('toInitialEditValue', () => {
  it('coerces booleans and never seeds the redacted secret', () => {
    expect(toInitialEditValue(makeSetting({ type: 'bool', value: true }))).toBe(true);
    expect(toInitialEditValue(makeSetting({ type: 'int', value: 5 }))).toBe('5');
    expect(
      toInitialEditValue(makeSetting({ is_secret: true, type: 'SecretStr', value: '**********' })),
    ).toBe('');
  });
});

describe('toPatchValue', () => {
  it('converts edit values back to wire types', () => {
    expect(toPatchValue(makeSetting({ type: 'bool' }), true)).toBe(true);
    expect(toPatchValue(makeSetting({ type: 'int' }), '7')).toBe(7);
    expect(toPatchValue(makeSetting({ type: 'str' }), 'hi')).toBe('hi');
  });
});

describe('isSaveable', () => {
  it('blocks non-editable, blank, and unchanged-boolean states', () => {
    expect(isSaveable(makeSetting({ reload: 'not_overridable' }), 'x')).toBe(false);
    expect(isSaveable(makeSetting({ type: 'str' }), '   ')).toBe(false);
    expect(isSaveable(makeSetting({ type: 'bool', value: true }), true)).toBe(false);
    expect(isSaveable(makeSetting({ type: 'bool', value: true }), false)).toBe(true);
  });

  it('rejects the redacted literal for secrets but allows a real new value', () => {
    const secret = makeSetting({ is_secret: true, type: 'SecretStr', value: '**********' });
    expect(isSaveable(secret, '**********')).toBe(false);
    expect(isSaveable(secret, 'new-secret')).toBe(true);
  });

  it('rejects unparseable numbers', () => {
    expect(isSaveable(makeSetting({ type: 'int' }), 'abc')).toBe(false);
    expect(isSaveable(makeSetting({ type: 'int' }), '12')).toBe(true);
  });
});
