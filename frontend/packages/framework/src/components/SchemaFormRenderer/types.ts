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
 * Local type aliases for the plugin schema shape.
 *
 * Re-exports from `@sep/api` so field components and tests have a single
 * import surface. If the backend schema shape ever diverges from the api
 * package's contract, adapt here without touching every field file.
 */

export type {
  PluginSchema,
  PluginField,
  FormSection,
  StringField,
  IntegerField,
  FloatField,
  BoolField,
  ChoiceField,
  ChoiceOption,
  MultiChoiceField,
  TextAreaField,
  DateTimeField,
  FileField,
  YamlField,
  ServiceField,
  SchemaField,
  TableField,
  HostField,
  ScriptPreviewField,
  Predicate,
  FieldGate,
  CardinalityRule,
  FailRule,
} from '@sep/api';
