import { SchemaSelector } from '../../SchemaSelector';
import type { SchemaField as SchemaFieldType } from '../types';

interface SchemaFieldProps {
  field: SchemaFieldType;
}

export function SchemaField({ field }: SchemaFieldProps) {
  return (
    <SchemaSelector
      name={field.name}
      label={field.label}
      required={field.required}
      dependsOn={field.dependsOn}
    />
  );
}
