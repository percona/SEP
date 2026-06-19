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
 * Pure helpers that map an API {@link SettingResponse} onto an edit control.
 *
 * The settings API reports a field's shape through three signals — the
 * human-readable `type` string, `is_secret`, and `is_complex` — rather than a
 * machine-readable schema. These helpers centralise the dispatch so the React
 * components stay declarative and the logic is unit-testable in isolation.
 */
import { REDACTED_SECRET, type SettingResponse } from '@sep/api';

export type FieldKind = 'complex' | 'secret' | 'bool' | 'number' | 'choice' | 'text';

/**
 * The edit value carried in component state while a row is being edited.
 * Booleans render as a toggle; every other control edits a string and is
 * converted back to its wire type at save time.
 */
export type EditValue = boolean | string;

/**
 * Parse the options out of a `Literal[...]` annotation string, e.g.
 * `Literal['warn', 'fail']` → `['warn', 'fail']`. Returns `null` for anything
 * that is not a recognisable string-literal union (named enums render as their
 * class name and carry no inline options, so they fall back to a text input).
 *
 * Limitation: splitting on `,` means a literal member that itself contains a
 * comma (e.g. `Literal["a,b"]`) won't parse and also falls back to text. No
 * current setting uses comma-bearing literals, so a full tokenizer is overkill.
 */
export function parseLiteralOptions(type: string): string[] | null {
  const match = /^Literal\[(.+)\]$/.exec(type.trim());
  if (!match) {
    return null;
  }
  const options = match[1]
    .split(',')
    .map((part) => part.trim())
    .map((part) => /^'([^']*)'$|^"([^"]*)"$/.exec(part))
    .map((m) => (m ? (m[1] ?? m[2]) : null))
    .filter((opt): opt is string => opt !== null);
  return options.length > 0 ? options : null;
}

/** Classify a setting into the control kind that should render it. */
export function getFieldKind(setting: SettingResponse): FieldKind {
  if (setting.is_complex) {
    return 'complex';
  }
  if (setting.is_secret) {
    return 'secret';
  }
  const type = setting.type.trim();
  if (type === 'bool') {
    return 'bool';
  }
  if (type === 'int' || type === 'float') {
    return 'number';
  }
  if (parseLiteralOptions(type) !== null) {
    return 'choice';
  }
  return 'text';
}

/** Whether a setting can be edited at all (HOT and not a nested submodel). */
export function isEditable(setting: SettingResponse): boolean {
  return setting.reload === 'hot' && !setting.is_complex;
}

/** Format a raw setting value for read-only display. */
export function formatSettingValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

/**
 * Format a value for the "view more" modal, pretty-printing objects/arrays
 * onto multiple indented lines so a `<pre>` block renders readable JSON.
 */
export function formatSettingValuePretty(value: unknown): string {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }
  return formatSettingValue(value);
}

/**
 * Seed the edit state from a setting's current value. Secrets always start
 * empty — the redacted literal must never be pre-loaded into the input, or the
 * admin could accidentally PATCH `**********` back as the real secret.
 */
export function toInitialEditValue(setting: SettingResponse): EditValue {
  const kind = getFieldKind(setting);
  if (kind === 'bool') {
    return Boolean(setting.value);
  }
  if (kind === 'secret') {
    return '';
  }
  if (setting.value === null || setting.value === undefined) {
    return '';
  }
  return String(setting.value);
}

/** Convert an edit value back to the JSON value sent in a PATCH body. */
export function toPatchValue(setting: SettingResponse, edit: EditValue): unknown {
  const kind = getFieldKind(setting);
  if (kind === 'bool') {
    return Boolean(edit);
  }
  if (kind === 'number') {
    return Number(edit);
  }
  return edit;
}

/**
 * Whether the current edit state is a valid, non-redacted change worth saving.
 * Guards the secret round-trip trap and rejects blank / unparseable numbers.
 */
export function isSaveable(setting: SettingResponse, edit: EditValue): boolean {
  if (!isEditable(setting)) {
    return false;
  }
  const kind = getFieldKind(setting);
  if (kind === 'bool') {
    return Boolean(edit) !== Boolean(setting.value);
  }
  if (typeof edit !== 'string') {
    return false;
  }
  const trimmed = edit.trim();
  if (trimmed === '') {
    return false;
  }
  if (kind === 'secret') {
    // Never let the redacted literal be persisted as the new secret.
    return trimmed !== REDACTED_SECRET;
  }
  if (kind === 'number') {
    return Number.isFinite(Number(trimmed));
  }
  return true;
}
