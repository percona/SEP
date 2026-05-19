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
 * Plugin Schema types — defines the contract for schema-driven plugins.
 *
 * These types mirror the backend PluginSchema Pydantic model.
 * The backend serves schemas at GET /api/plugins/{name}/schema as JSON.
 * The SchemaFormRenderer auto-generates the UI from these definitions.
 *
 * Wire format is snake_case end-to-end. Uses a discriminated union on
 * `type` for type-safe field rendering.
 */

// ── Conditional-rule primitives (SEP-1071) ──────────────────────────────

/**
 * Predicate JSON shape — a single-key object whose key is the operator
 * name (`equals`, `truthy`, `all`, `any`, `xor`, `not`, etc.). The full
 * operator catalogue lives alongside the BE DSL; we keep this open here
 * because the FE counterpart (SEP-1077) consumes the wire format directly.
 */
export type Predicate = Record<string, unknown>;

/**
 * Binary self-cardinality gate at BaseField scope — when `when` matches,
 * the field carrying the gate is required (for `requires`) or forbidden
 * (for `forbidden`).
 */
export interface FieldGate {
  when: Predicate;
  message?: string;
}

/**
 * Cross-field cardinality constraint at FormSection or PluginSchema scope.
 * When `when` matches (omitted means always), the count of present fields
 * in `fields` must satisfy `min` / `max` (omitted bound = unbounded). The
 * backend strips `None`-valued keys from the wire payload, so optional
 * properties may be absent rather than `null`.
 */
export interface CardinalityRule {
  when?: Predicate;
  fields: string[];
  min?: number;
  max?: number;
  message?: string;
}

/**
 * Predicate-only invariant: the rule fails iff `fail_when` matches.
 * `error_fields` is an FE rendering hint pointing at the inputs to
 * highlight when the rule fires.
 */
export interface FailRule {
  fail_when: Predicate;
  error_fields: string[];
  message?: string;
}

// ── Base field ──────────────────────────────────────────────────────────

interface BaseField {
  name: string;
  label: string;
  required?: boolean;
  description?: string;
  default?: unknown;
  /** Self-cardinality gates: when matched, the field is required. */
  requires?: FieldGate[];
  /** Self-cardinality gates: when matched, the field is forbidden. */
  forbidden?: FieldGate[];
}

// ── Concrete field types ────────────────────────────────────────────────

export interface StringField extends BaseField {
  type: 'string';
  min_length?: number;
  max_length?: number;
  pattern?: string;
  placeholder?: string;
}

export interface IntegerField extends BaseField {
  type: 'integer';
  ge?: number;
  le?: number;
  step?: number;
}

export interface FloatField extends BaseField {
  type: 'float';
  ge?: number;
  le?: number;
  step?: number;
}

export interface BoolField extends BaseField {
  type: 'bool';
}

export interface ChoiceField extends BaseField {
  type: 'choice';
  choices: Array<{ label: string; value: string }>;
}

export interface MultiChoiceField extends BaseField {
  type: 'multichoice';
  choices: Array<{ label: string; value: string }>;
  min_items?: number;
  max_items?: number;
}

export interface TextAreaField extends BaseField {
  type: 'textarea';
  rows?: number;
  placeholder?: string;
}

export interface DateTimeField extends BaseField {
  type: 'datetime';
}

export interface FileField extends BaseField {
  type: 'file';
  accept?: string[];
}

export interface YamlField extends BaseField {
  type: 'yaml';
  rows?: number;
  placeholder?: string;
}

// ── Inventory-aware fields ──────────────────────────────────────────────

export interface ServiceField extends BaseField {
  type: 'service';
  service_types: string[];
}

export interface SchemaField extends BaseField {
  type: 'schema';
  depends_on: string;
}

export interface TableField extends BaseField {
  type: 'table';
  depends_on: string;
}

export interface HostField extends BaseField {
  type: 'host';
}

// ── Read-only preview ───────────────────────────────────────────────────

export interface ScriptPreviewField extends BaseField {
  type: 'script_preview';
  /**
   * Fully-resolved URL the renderer fetches preview content from. Schema
   * synthesisers should bake plugin-specific path segments here at schema
   * build time rather than templating client-side.
   */
  endpoint_url: string;
  /**
   * Names of sibling fields whose values trigger a debounced re-fetch.
   * Empty (the default) means fetch once on mount.
   */
  depends_on: string[];
  /** Optional default highlighter language hint. */
  language?: string;
}

// ── Discriminated union ─────────────────────────────────────────────────

export type PluginField =
  | StringField
  | IntegerField
  | FloatField
  | BoolField
  | ChoiceField
  | MultiChoiceField
  | TextAreaField
  | DateTimeField
  | FileField
  | YamlField
  | ServiceField
  | SchemaField
  | TableField
  | HostField
  | ScriptPreviewField;

// ── Form structure ──────────────────────────────────────────────────────

export interface FormSection {
  title: string;
  description?: string;
  fields: PluginField[];
  /** Whether the section is wrapped in an expandable/collapsible shell. */
  collapsible?: boolean;
  /** Initial expansion state when collapsible is enabled. */
  collapsed_by_default?: boolean;
  /** Whether to render the section after the submit button. */
  render_after_submit?: boolean;
  /** Cross-field cardinality constraints scoped to this section. */
  cardinality_rules?: CardinalityRule[];
  /** Predicate-only invariants scoped to this section. */
  fail_when?: FailRule[];
}

// ── List view ───────────────────────────────────────────────────────────

export interface ListColumn {
  key: string;
  label: string;
  sortable?: boolean;
  format?: 'text' | 'chip' | 'status' | 'date' | 'relative' | 'code' | 'actions';
}

export interface ListView {
  columns: ListColumn[];
  /** Column key to sort by. Prefix with '-' for descending (e.g. '-last_run'). */
  default_sort?: string;
}

// ── Capabilities ────────────────────────────────────────────────────────

export interface PluginCapabilities {
  chaining?: boolean;
  alert_on_fail?: boolean;
  scheduling?: boolean;
  topology?: boolean;
}

// ── Multi-entity plugins (inventory) ────────────────────────────────────

/** One CRUD resource when a plugin exposes several (nodes, services, …). */
export interface PluginEntitySchema {
  name: string;
  display_name: string;
  description?: string;
  forms: FormSection[];
  list_view: ListView;
  /** Optional detail-view syntax hints keyed by field name. */
  detail_highlights?: Partial<Record<string, 'sql' | 'json'>>;
}

// ── Top-level schema ────────────────────────────────────────────────────

export interface PluginSchema {
  name: string;
  display_name: string;
  description?: string;
  task_type?: string;
  /** Task-style single entity: forms + list_view (omit or leave entities unset). */
  forms?: FormSection[];
  capabilities?: PluginCapabilities;
  list_view?: ListView;
  /** When set, the shell renders one list/create/detail flow per entity. */
  entities?: PluginEntitySchema[];
  /** Schema-wide cross-field cardinality constraints (task-style plugins). */
  cardinality_rules?: CardinalityRule[];
  /** Schema-wide predicate-only invariants (task-style plugins). */
  fail_when?: FailRule[];
}
