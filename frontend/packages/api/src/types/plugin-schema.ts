/**
 * Plugin Schema types — defines the contract for schema-driven plugins.
 *
 * These types mirror the backend PluginSchema Pydantic model.
 * The backend serves schemas at GET /api/plugins/{name}/schema as JSON.
 * The SchemaFormRenderer auto-generates the UI from these definitions.
 *
 * Uses a discriminated union on `type` for type-safe field rendering.
 */

// ── Base field ──────────────────────────────────────────────────────────

interface BaseField {
  name: string;
  label: string;
  required?: boolean;
  description?: string;
  default?: unknown;
}

// ── Concrete field types ────────────────────────────────────────────────

export interface StringField extends BaseField {
  type: 'string';
  minLength?: number;
  maxLength?: number;
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
  minItems?: number;
  maxItems?: number;
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
  serviceTypes: string[];
}

export interface SchemaField extends BaseField {
  type: 'schema';
  dependsOn: string;
}

export interface TableField extends BaseField {
  type: 'table';
  dependsOn: string;
}

export interface HostField extends BaseField {
  type: 'host';
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
  | HostField;

// ── Form structure ──────────────────────────────────────────────────────

export interface FormSection {
  title: string;
  description?: string;
  fields: PluginField[];
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
  /** Column key to sort by. Prefix with '-' for descending (e.g. '-lastRun'). */
  defaultSort?: string;
}

// ── Capabilities ────────────────────────────────────────────────────────

export interface PluginCapabilities {
  chaining?: boolean;
  alertOnFail?: boolean;
  scheduling?: boolean;
}

// ── Multi-entity plugins (inventory) ────────────────────────────────────

/** One CRUD resource when a plugin exposes several (nodes, services, …). */
export interface PluginEntitySchema {
  name: string;
  displayName: string;
  description?: string;
  forms: FormSection[];
  listView: ListView;
}

// ── Top-level schema ────────────────────────────────────────────────────

export interface PluginSchema {
  name: string;
  displayName: string;
  description?: string;
  taskType?: string;
  /** Task-style single entity: forms + listView (omit or leave entities unset). */
  forms?: FormSection[];
  capabilities?: PluginCapabilities;
  listView?: ListView;
  /** When set, the shell renders one list/create/detail flow per entity. */
  entities?: PluginEntitySchema[];
}
