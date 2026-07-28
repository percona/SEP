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

import type { AppField } from '../types';
import { StringField } from './StringField';
import { IntegerField } from './IntegerField';
import { FloatField } from './FloatField';
import { BoolField } from './BoolField';
import { ChoiceField } from './ChoiceField';
import { MultiChoiceField } from './MultiChoiceField';
import { TextAreaField } from './TextAreaField';
import { DateTimeField } from './DateTimeField';
import { FileField } from './FileField';
import { YamlField } from './YamlField';
import { ServiceField } from './ServiceField';
import { MultiServiceField } from './MultiServiceField';
import { SchemaField } from './SchemaField';
import { MultiSchemaField } from './MultiSchemaField';
import { TableField } from './TableField';
import { MultiTableField } from './MultiTableField';
import { HostField } from './HostField';
import { MultiHostField } from './MultiHostField';
import { RemoteChoiceField } from './RemoteChoiceField';
import { ScriptPreviewField } from './ScriptPreviewField';

export {
  StringField,
  IntegerField,
  FloatField,
  BoolField,
  ChoiceField,
  MultiChoiceField,
  TextAreaField,
  DateTimeField,
  FileField,
  YamlField,
  ServiceField,
  MultiServiceField,
  SchemaField,
  MultiSchemaField,
  TableField,
  MultiTableField,
  HostField,
  MultiHostField,
  RemoteChoiceField,
  ScriptPreviewField,
};

interface FieldRendererProps {
  field: AppField;
}

/**
 * Dispatches an AppField to the concrete component for its `type` discriminator.
 *
 * The switch is exhaustive on the discriminated union — adding a new field type
 * to `AppField` will surface a TypeScript error here until the case is added.
 */
export function FieldRenderer({ field }: FieldRendererProps) {
  switch (field.type) {
    case 'string':
      return <StringField field={field} />;
    case 'integer':
      return <IntegerField field={field} />;
    case 'float':
      return <FloatField field={field} />;
    case 'bool':
      return <BoolField field={field} />;
    case 'choice':
      return <ChoiceField field={field} />;
    case 'multi_choice':
      return <MultiChoiceField field={field} />;
    case 'textarea':
      return <TextAreaField field={field} />;
    case 'datetime':
      return <DateTimeField field={field} />;
    case 'file':
      return <FileField field={field} />;
    case 'yaml':
      return <YamlField field={field} />;
    case 'service':
      return <ServiceField field={field} />;
    case 'multi_service':
      return <MultiServiceField field={field} />;
    case 'schema':
      return <SchemaField field={field} />;
    case 'multi_schema':
      return <MultiSchemaField field={field} />;
    case 'table':
      return <TableField field={field} />;
    case 'multi_table':
      return <MultiTableField field={field} />;
    case 'host':
      return <HostField field={field} />;
    case 'multi_host':
      return <MultiHostField field={field} />;
    case 'script_preview':
      return <ScriptPreviewField field={field} />;
    case 'remote_choice':
      return <RemoteChoiceField field={field} />;
    default: {
      const exhaustive: never = field;
      void exhaustive;
      return null;
    }
  }
}
