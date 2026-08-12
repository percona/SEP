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
  buildSettingTree,
  countLeaves,
  countOverriddenLeaves,
  groupNodeId,
  formatSettingValue,
  formatSettingDisplayValue,
  formatSettingValuePretty,
  matchOptionLabel,
  getFieldKind,
  isEditable,
  isSaveable,
  parseLiteralOptions,
  segmentsOf,
  toInitialEditValue,
  toPatchValue,
  type GroupNode,
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

  it('treats non-empty options as choice even when type is a named enum', () => {
    expect(
      getFieldKind(
        makeSetting({
          type: 'LogLevel',
          options: [
            { label: 'WARNING', value: 30 },
            { label: 'DEBUG', value: 10 },
          ],
        }),
      ),
    ).toBe('choice');
  });

  it('keeps complex and secret ahead of options-based choice', () => {
    expect(
      getFieldKind(
        makeSetting({
          is_complex: true,
          options: [{ label: 'A', value: 'a' }],
        }),
      ),
    ).toBe('complex');
    expect(
      getFieldKind(
        makeSetting({
          is_secret: true,
          type: 'SecretStr',
          options: [{ label: 'A', value: 'a' }],
        }),
      ),
    ).toBe('secret');
  });

  it('still does not invent Literal options from a bare enum type name', () => {
    expect(parseLiteralOptions('PreExecutionCheckMode')).toBeNull();
    expect(getFieldKind(makeSetting({ type: 'PreExecutionCheckMode' }))).toBe('text');
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

describe('formatSettingDisplayValue', () => {
  const options = [
    { label: 'WARNING', value: 30 },
    { label: 'DEBUG', value: 10 },
  ];

  it('prefers the matching option label over the raw dumped value', () => {
    expect(formatSettingDisplayValue(30, options)).toBe('WARNING');
    expect(formatSettingDisplayValue(10, options)).toBe('DEBUG');
  });

  it('falls back to formatSettingValue when options are absent or unmatched', () => {
    expect(formatSettingDisplayValue(30)).toBe('30');
    expect(formatSettingDisplayValue(30, [])).toBe('30');
    expect(formatSettingDisplayValue(99, [{ label: 'WARNING', value: 30 }])).toBe('99');
  });
});

describe('matchOptionLabel', () => {
  const options = [
    { label: 'WARNING', value: 30 },
    { label: 'DEBUG', value: 10 },
  ];

  it('returns the matching label for dumped wire values', () => {
    expect(matchOptionLabel(30, options)).toBe('WARNING');
    expect(matchOptionLabel('10', options)).toBe('DEBUG');
  });

  it('returns null when options are missing or unmatched', () => {
    expect(matchOptionLabel(30)).toBeNull();
    expect(matchOptionLabel(30, [])).toBeNull();
    expect(matchOptionLabel(99, options)).toBeNull();
  });
});

describe('formatSettingValuePretty', () => {
  it('prefers option labels before pretty-printing', () => {
    expect(
      formatSettingValuePretty(30, [
        { label: 'WARNING', value: 30 },
        { label: 'DEBUG', value: 10 },
      ]),
    ).toBe('WARNING');
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

  it('round-trips IntEnum choice via typed option value', () => {
    const setting = makeSetting({
      type: 'LogLevel',
      value: 30,
      options: [
        { label: 'WARNING', value: 30 },
        { label: 'DEBUG', value: 10 },
      ],
    });
    expect(toInitialEditValue(setting)).toBe('30');
    expect(toPatchValue(setting, '10')).toBe(10);
    expect(typeof toPatchValue(setting, '10')).toBe('number');
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

describe('segmentsOf', () => {
  it('uses the explicit key_path chain when present', () => {
    expect(segmentsOf(makeSetting({ key: 'A__B', key_path: ['A', 'B'] }))).toEqual(['A', 'B']);
  });

  it('falls back to a single-segment chain when key_path is absent', () => {
    expect(segmentsOf(makeSetting({ key: 'TOP', key_path: undefined }))).toEqual(['TOP']);
  });

  it('does not split key on __ (a segment may itself contain __)', () => {
    // key_path is authoritative: one segment that happens to contain "__".
    expect(segmentsOf(makeSetting({ key: 'WEIRD__SEG', key_path: ['WEIRD__SEG'] }))).toEqual([
      'WEIRD__SEG',
    ]);
  });
});

describe('buildSettingTree', () => {
  it('keeps top-level scalars as leaf nodes', () => {
    const a = makeSetting({ key: 'A', key_path: ['A'] });
    const b = makeSetting({ key: 'B', key_path: ['B'] });
    const tree = buildSettingTree([a, b]);
    expect(tree).toEqual([
      { kind: 'leaf', setting: a },
      { kind: 'leaf', setting: b },
    ]);
  });

  it('groups one-level nested leaves under a synthesised parent', () => {
    const child1 = makeSetting({ key: 'SESSION__MAX_AGE', key_path: ['SESSION', 'MAX_AGE'] });
    const child2 = makeSetting({ key: 'SESSION__SECURE', key_path: ['SESSION', 'SECURE'] });
    const tree = buildSettingTree([child1, child2]);
    expect(tree).toHaveLength(1);
    const group = tree[0] as GroupNode;
    expect(group.kind).toBe('group');
    expect(group.segment).toBe('SESSION');
    expect(group.keyPrefix).toBe('SESSION');
    expect(group.children).toEqual([
      { kind: 'leaf', setting: child1 },
      { kind: 'leaf', setting: child2 },
    ]);
  });

  it('nests two levels for three-segment keys', () => {
    const leaf = makeSetting({
      key: 'SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE',
      key_path: ['SECURITY_HEADERS', 'STRICT_TRANSPORT_SECURITY', 'MAX_AGE'],
    });
    const tree = buildSettingTree([leaf]);
    const outer = tree[0] as GroupNode;
    expect(outer.segment).toBe('SECURITY_HEADERS');
    const inner = outer.children[0] as GroupNode;
    expect(inner.kind).toBe('group');
    expect(inner.segment).toBe('STRICT_TRANSPORT_SECURITY');
    expect(inner.keyPrefix).toBe('SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY');
    expect(inner.children).toEqual([{ kind: 'leaf', setting: leaf }]);
  });

  it('shares a parent group across sibling leaves and preserves order', () => {
    const top = makeSetting({ key: 'TOP', key_path: ['TOP'] });
    const n1 = makeSetting({ key: 'NOMAD__ENDPOINT', key_path: ['NOMAD', 'ENDPOINT'] });
    const n2 = makeSetting({ key: 'NOMAD__TOKEN', key_path: ['NOMAD', 'TOKEN'] });
    const tree = buildSettingTree([top, n1, n2]);
    expect(tree).toHaveLength(2);
    expect(tree[0]).toEqual({ kind: 'leaf', setting: top });
    expect((tree[1] as GroupNode).children).toHaveLength(2);
  });

  it('does not merge distinct segment chains that join to the same string', () => {
    // ['A__B'] and ['A', 'B'] both join to "A__B" but are different chains: a
    // one-level group with a "__"-bearing first segment vs a two-level path.
    const weird = makeSetting({ key: 'A__B__X', key_path: ['A__B', 'X'] });
    const normal = makeSetting({ key: 'A__B__Y', key_path: ['A', 'B', 'Y'] });
    const tree = buildSettingTree([weird, normal]);
    // Two distinct top-level groups, not one merged group.
    expect(tree).toHaveLength(2);
    expect((tree[0] as GroupNode).segment).toBe('A__B');
    expect((tree[1] as GroupNode).segment).toBe('A');
    // Their keyPrefix collides, but their identity (keyPath) does not.
    expect((tree[0] as GroupNode).keyPrefix).toBe('A__B');
    expect((tree[1] as GroupNode).keyPath).toEqual(['A']);
    expect(groupNodeId(tree[0] as GroupNode)).not.toBe(groupNodeId(tree[1] as GroupNode));
  });

  it('clamps anything deeper than two levels onto the level-two group', () => {
    const deep = makeSetting({ key: 'A__B__C__D', key_path: ['A', 'B', 'C', 'D'] });
    const a = buildSettingTree([deep])[0] as GroupNode;
    expect(a.segment).toBe('A');
    const b = a.children[0] as GroupNode;
    expect(b.segment).toBe('B');
    // No third group level: the leaf is filed directly under B.
    expect(b.children).toEqual([{ kind: 'leaf', setting: deep }]);
  });
});

describe('countLeaves', () => {
  it('counts editable leaves under a node', () => {
    const tree = buildSettingTree([
      makeSetting({ key: 'NOMAD__ENDPOINT', key_path: ['NOMAD', 'ENDPOINT'] }),
      makeSetting({ key: 'NOMAD__TOKEN', key_path: ['NOMAD', 'TOKEN'] }),
    ]);
    expect(countLeaves(tree[0])).toBe(2);
  });
});

describe('countOverriddenLeaves', () => {
  it('counts only the leaves carrying an override', () => {
    const tree = buildSettingTree([
      makeSetting({ key: 'NOMAD__ENDPOINT', key_path: ['NOMAD', 'ENDPOINT'], has_override: true }),
      makeSetting({ key: 'NOMAD__TOKEN', key_path: ['NOMAD', 'TOKEN'], has_override: false }),
    ]);
    expect(countOverriddenLeaves(tree[0])).toBe(1);
  });
});
