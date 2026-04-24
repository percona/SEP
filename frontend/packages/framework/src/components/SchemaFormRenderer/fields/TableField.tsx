import { useFormContext } from 'react-hook-form';
import { TableSelector } from '../../TableSelector';
import { useCascadingField } from '../hooks/useCascadingField';
import type { TableField as TableFieldType } from '../types';

interface TableFieldProps {
  field: TableFieldType;
}

export function TableField({ field }: TableFieldProps) {
  const { control } = useFormContext();
  useCascadingField({ fieldName: field.name, dependsOn: field.dependsOn });
  return (
    <TableSelector
      name={field.name}
      label={field.label}
      required={field.required}
      dependsOn={field.dependsOn}
      control={control}
    />
  );
}
