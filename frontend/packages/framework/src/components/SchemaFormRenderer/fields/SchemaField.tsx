import { useFormContext } from 'react-hook-form';
import { SchemaSelector } from '../../SchemaSelector';
import { useCascadingField } from '../hooks/useCascadingField';
import type { SchemaField as SchemaFieldType } from '../types';

interface SchemaFieldProps {
  field: SchemaFieldType;
}

export function SchemaField({ field }: SchemaFieldProps) {
  const { control } = useFormContext();
  useCascadingField({ fieldName: field.name, dependsOn: field.dependsOn });
  return (
    <SchemaSelector
      name={field.name}
      label={field.label}
      required={field.required}
      dependsOn={field.dependsOn}
      control={control}
    />
  );
}
