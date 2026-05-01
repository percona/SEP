import type { PluginField } from '../types';
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
import { SchemaField } from './SchemaField';
import { TableField } from './TableField';
import { HostField } from './HostField';
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
  SchemaField,
  TableField,
  HostField,
  ScriptPreviewField,
};

interface FieldRendererProps {
  field: PluginField;
}

/**
 * Dispatches a PluginField to the concrete component for its `type` discriminator.
 *
 * The switch is exhaustive on the discriminated union — adding a new field type
 * to `PluginField` will surface a TypeScript error here until the case is added.
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
    case 'multichoice':
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
    case 'schema':
      return <SchemaField field={field} />;
    case 'table':
      return <TableField field={field} />;
    case 'host':
      return <HostField field={field} />;
    case 'script_preview':
      return <ScriptPreviewField field={field} />;
    default: {
      const exhaustive: never = field;
      void exhaustive;
      return null;
    }
  }
}
