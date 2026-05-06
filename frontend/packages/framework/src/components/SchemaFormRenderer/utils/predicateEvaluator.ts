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

import type { FieldGate, Predicate } from '../types';

type FormValues = Record<string, unknown>;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) {
    return false;
  }
  const proto = Object.getPrototypeOf(v) as unknown;
  return proto === Object.prototype || proto === null;
}

function isTruthy(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  // mirror Python bool({}): empty plain objects are falsy
  if (isPlainObject(value)) {
    return Object.keys(value).length > 0;
  }
  return Boolean(value);
}

function isPresent(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  // mirror Python _field_is_present: empty plain objects are absent
  if (isPlainObject(value)) {
    return Object.keys(value).length > 0;
  }
  return value !== null && value !== undefined && value !== '';
}

function isFieldRef(v: unknown): v is { $field: string } {
  return typeof v === 'object' && v !== null && '$field' in v;
}

function resolveValue(raw: unknown, values: FormValues): unknown {
  return isFieldRef(raw) ? values[(raw as { $field: string }).$field] : raw;
}

/**
 * Coerces a value to number for ordered comparisons.
 * Intentional divergence from Python (which raises TypeError on "10" > 5):
 * RHF stores text-input values as strings until coerceFormValues runs at submit,
 * so predicate evaluation must handle string representations of numbers.
 */
function toNum(v: unknown): number {
  return typeof v === 'number' ? v : Number(v);
}

/**
 * Evaluate a predicate wire-format object against the current form values.
 *
 * Mirrors the backend DSL operators from `app/sep/plugins/framework/rules.py`.
 * Each predicate is a single-key object `{ <operator>: <operand> }` — the BE
 * schema validator enforces this; multi-key predicates are not valid wire format
 * and only the first entry would be evaluated.
 * Unknown operators return false so malformed schemas degrade gracefully.
 */
export function evaluatePredicate(predicate: Predicate, values: FormValues): boolean {
  const entries = Object.entries(predicate);
  if (entries.length === 0) {
    return false;
  }
  const [op, operand] = entries[0];

  switch (op) {
    case 'truthy':
      return isTruthy(values[operand as string]);
    case 'falsy':
      return !isTruthy(values[operand as string]);

    case 'equals': {
      const entry = Object.entries(operand as Record<string, unknown>)[0];
      if (!entry) {
        return false;
      }
      const [field, raw] = entry;
      return values[field] === resolveValue(raw, values);
    }
    case 'not_equals': {
      const entry = Object.entries(operand as Record<string, unknown>)[0];
      if (!entry) {
        return false;
      }
      const [field, raw] = entry;
      return values[field] !== resolveValue(raw, values);
    }
    case 'gt': {
      const entry = Object.entries(operand as Record<string, unknown>)[0];
      if (!entry) {
        return false;
      }
      const [field, raw] = entry;
      return toNum(values[field]) > toNum(resolveValue(raw, values));
    }
    case 'gte': {
      const entry = Object.entries(operand as Record<string, unknown>)[0];
      if (!entry) {
        return false;
      }
      const [field, raw] = entry;
      return toNum(values[field]) >= toNum(resolveValue(raw, values));
    }
    case 'lt': {
      const entry = Object.entries(operand as Record<string, unknown>)[0];
      if (!entry) {
        return false;
      }
      const [field, raw] = entry;
      return toNum(values[field]) < toNum(resolveValue(raw, values));
    }
    case 'lte': {
      const entry = Object.entries(operand as Record<string, unknown>)[0];
      if (!entry) {
        return false;
      }
      const [field, raw] = entry;
      return toNum(values[field]) <= toNum(resolveValue(raw, values));
    }

    case 'all_truthy': {
      const fs = operand as string[];
      return fs.length > 0 && fs.every((f) => isTruthy(values[f]));
    }
    case 'all_falsy': {
      const fs = operand as string[];
      return fs.length > 0 && fs.every((f) => !isTruthy(values[f]));
    }
    case 'any_truthy':
      return (operand as string[]).some((f) => isTruthy(values[f]));
    case 'any_falsy':
      return (operand as string[]).some((f) => !isTruthy(values[f]));
    case 'any_present':
      return (operand as string[]).some((f) => isPresent(values[f]));
    case 'all_present': {
      const fs = operand as string[];
      return fs.length > 0 && fs.every((f) => isPresent(values[f]));
    }
    case 'none_present': {
      const fs = operand as string[];
      return fs.length > 0 && fs.every((f) => !isPresent(values[f]));
    }
    case 'all_equal': {
      const fields = operand as string[];
      if (fields.length < 2) {
        return false;
      }
      const first = values[fields[0]];
      return fields.slice(1).every((f) => values[f] === first);
    }

    case 'all': {
      const ps = operand as Predicate[];
      return ps.length > 0 && ps.every((p) => evaluatePredicate(p, values));
    }
    case 'any':
      return (operand as Predicate[]).some((p) => evaluatePredicate(p, values));
    case 'xor': {
      // n-ary XOR: true when exactly one operand evaluates to true.
      // Subsumes binary XOR and handles any arity the BE may emit.
      const preds = operand as Predicate[];
      if (preds.length === 0) {
        return false;
      }
      return preds.filter((p) => evaluatePredicate(p, values)).length === 1;
    }
    case 'not':
      return !evaluatePredicate(operand as Predicate, values);

    default:
      return false;
  }
}

function getPredicateFieldNames(predicate: Predicate): string[] {
  const entries = Object.entries(predicate);
  if (entries.length === 0) {
    return [];
  }
  const [op, operand] = entries[0];

  switch (op) {
    case 'truthy':
    case 'falsy':
      return [operand as string];
    case 'equals':
    case 'not_equals':
    case 'gt':
    case 'gte':
    case 'lt':
    case 'lte': {
      const entry = Object.entries(operand as Record<string, unknown>)[0];
      if (!entry) {
        return [];
      }
      const [field, raw] = entry;
      const names: string[] = [field];
      if (isFieldRef(raw)) {
        names.push((raw as { $field: string }).$field);
      }
      return names;
    }
    case 'all_truthy':
    case 'all_falsy':
    case 'any_truthy':
    case 'any_falsy':
    case 'any_present':
    case 'all_present':
    case 'none_present':
    case 'all_equal':
      return operand as string[];
    case 'all':
    case 'any':
    case 'xor':
      return (operand as Predicate[]).flatMap((p) => getPredicateFieldNames(p));
    case 'not':
      return getPredicateFieldNames(operand as Predicate);
    default:
      return [];
  }
}

/** Returns the deduplicated set of field names referenced by a list of gates. */
export function getGateFieldNames(gates: FieldGate[]): string[] {
  return [...new Set(gates.flatMap((g) => getPredicateFieldNames(g.when)))];
}
