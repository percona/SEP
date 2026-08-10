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
 * class name and carry no inline options, so they fall back to a text input
 * unless the API supplies {@link SettingResponse.options}).
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

/** A selectable member for a choice control (label shown, value PATCHed). */
export type SettingChoiceOption = { label: string; value: unknown };

/**
 * Resolve the options for a choice control. Prefer non-empty API `options`
 * (enum members with typed values); otherwise map parsed `Literal[...]`
 * members to `{label, value}` string pairs.
 */
export function getSettingOptions(setting: SettingResponse): SettingChoiceOption[] {
  const fromApi = setting.options;
  if (Array.isArray(fromApi) && fromApi.length > 0) {
    return fromApi.map((o) => ({ label: o.label, value: o.value }));
  }
  const literals = parseLiteralOptions(setting.type);
  if (literals === null) {
    return [];
  }
  return literals.map((opt) => ({ label: opt, value: opt }));
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
  if (getSettingOptions(setting).length > 0) {
    return 'choice';
  }
  return 'text';
}

/**
 * Whether a setting can be edited at all: HOT, not a nested submodel, and
 * applicable under the current runtime state (e.g. the active auth provider).
 * A not-applicable field renders inert, so it is also not saveable
 * ({@link isSaveable} short-circuits through this helper).
 */
export function isEditable(setting: SettingResponse): boolean {
  return setting.reload === 'hot' && !setting.is_complex && setting.is_applicable !== false;
}

// ── Nested-setting grouping ────────────────────────────────────────────────

/**
 * The canonical segment chain for a setting. The backend keys each nested leaf
 * by `PARENT__CHILD[__GRANDCHILD]` and carries the explicit `key_path` chain
 * such that `key_path.join('__') === key`. We group strictly on that chain and
 * never split `key` on `__` (a segment could itself contain `__`). Falls back
 * to a single-segment chain for entries without an explicit `key_path`.
 */
export function segmentsOf(setting: SettingResponse): string[] {
  return setting.key_path && setting.key_path.length > 0 ? setting.key_path : [setting.key];
}

/** A directly-editable setting: a top-level scalar or a nested leaf. */
export interface LeafNode {
  kind: 'leaf';
  setting: SettingResponse;
}

/** A synthesised expandable parent, reconstructed from leaves' `key_path`. */
export interface GroupNode {
  kind: 'group';
  /** This node's own segment (e.g. `STRICT_TRANSPORT_SECURITY`). */
  segment: string;
  /** The `__`-joined prefix down to and including this node (e.g. `A__B`). */
  keyPrefix: string;
  /**
   * The canonical segment chain down to and including this node (e.g.
   * `['A', 'B']`). This is the node's true identity: unlike `keyPrefix`, two
   * distinct chains can never share one `keyPath`, so it is the safe basis for
   * a stable, unambiguous key / `data-testid`.
   */
  keyPath: string[];
  children: SettingNode[];
}

export type SettingNode = LeafNode | GroupNode;

/**
 * A collision-free identity string for a group node, for use as a React `key`
 * or `data-testid`. Segments are canonical attribute names (which cannot
 * contain `.`), so joining on `.` can never alias the way the `__`-joined
 * `keyPrefix` can (e.g. `['A__B']` and `['A', 'B']` share a `keyPrefix` but not
 * a `keyPath`).
 */
export function groupNodeId(node: GroupNode): string {
  return node.keyPath.join('.');
}

/**
 * Build the parent -> child render tree for one settings class from its flat
 * entry list.
 *
 * The LIST response expands each nested-overridable parent into one entry per
 * scalar leaf (the parent's own summary entry is replaced), so the parent rows
 * are reconstructed here purely from each leaf's `key_path` segment chain:
 *   - a single-segment entry (a top-level scalar, or a non-expandable complex
 *     field) becomes a leaf node;
 *   - a multi-segment entry is filed under a synthesised group per leading
 *     segment, nesting one more level for three-segment keys (the backend's
 *     two-level maximum, e.g. `A__B__C`).
 *
 * Insertion order is preserved, and a group is created once per distinct prefix
 * so sibling leaves share their parent. Anything deeper than the supported two
 * levels is clamped: the leaf is filed under its level-two group rather than
 * recursing without bound.
 */
export function buildSettingTree(settings: SettingResponse[]): SettingNode[] {
  const MAX_GROUP_DEPTH = 2; // two levels of nesting => at most A__B__leaf
  const roots: SettingNode[] = [];
  const groupsByPrefix = new Map<string, GroupNode>();

  for (const setting of settings) {
    const segments = segmentsOf(setting);
    if (segments.length <= 1) {
      roots.push({ kind: 'leaf', setting });
      continue;
    }

    // Walk/create the group chain for every segment but the last (the leaf),
    // capped at MAX_GROUP_DEPTH groups so an unexpectedly deep key can't recurse
    // without bound.
    const groupSegments = segments.slice(0, -1).slice(0, MAX_GROUP_DEPTH);
    let siblings = roots;
    const prefixParts: string[] = [];
    for (const segment of groupSegments) {
      prefixParts.push(segment);
      // Identify a group by its exact segment chain, never by the joined string:
      // two distinct chains (e.g. ['A__B'] and ['A', 'B']) can join to the same
      // text, and merging them would attach leaves to the wrong parent.
      const identity = JSON.stringify(prefixParts);
      let group = groupsByPrefix.get(identity);
      if (!group) {
        group = {
          kind: 'group',
          segment,
          keyPrefix: prefixParts.join('__'),
          keyPath: [...prefixParts],
          children: [],
        };
        groupsByPrefix.set(identity, group);
        siblings.push(group);
      }
      siblings = group.children;
    }
    siblings.push({ kind: 'leaf', setting });
  }

  return roots;
}

/** Count the leaves reachable under a node (for a parent summary). A leaf is
 * not necessarily editable; a NOT_OVERRIDABLE leaf still counts. */
export function countLeaves(node: SettingNode): number {
  if (node.kind === 'leaf') {
    return 1;
  }
  return node.children.reduce((total, child) => total + countLeaves(child), 0);
}

/** Count the leaves reachable under a node that currently carry an override. */
export function countOverriddenLeaves(node: SettingNode): number {
  if (node.kind === 'leaf') {
    return node.setting.has_override ? 1 : 0;
  }
  return node.children.reduce((total, child) => total + countOverriddenLeaves(child), 0);
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
 * Format a value for the read-only Current column. When ``options`` includes a
 * matching member, show its label (e.g. ``WARNING``) instead of the dumped
 * wire value (e.g. ``30``).
 */
export function formatSettingDisplayValue(
  value: unknown,
  options?: SettingChoiceOption[] | null,
): string {
  if (options && options.length > 0 && value !== null && value !== undefined) {
    const match = options.find((opt) => String(opt.value) === String(value));
    if (match) {
      return match.label;
    }
  }
  return formatSettingValue(value);
}

/**
 * Format a value for the "view more" modal, pretty-printing objects/arrays
 * onto multiple indented lines so a `<pre>` block renders readable JSON.
 * Prefer option labels when provided (same as the Current column).
 */
export function formatSettingValuePretty(
  value: unknown,
  options?: SettingChoiceOption[] | null,
): string {
  if (options && options.length > 0 && value !== null && value !== undefined) {
    const match = options.find((opt) => String(opt.value) === String(value));
    if (match) {
      return match.label;
    }
  }
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
  if (kind === 'choice') {
    const match = getSettingOptions(setting).find((opt) => String(opt.value) === String(edit));
    return match ? match.value : edit;
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
