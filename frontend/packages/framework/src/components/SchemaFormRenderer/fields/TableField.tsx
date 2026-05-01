import { TableSelector } from '../../TableSelector';
import type { TableField as TableFieldType } from '../types';

interface TableFieldProps {
  field: TableFieldType;
}

export function TableField({ field }: TableFieldProps) {
  return (
    <TableSelector
      name={field.name}
      label={field.label}
      required={field.required}
      dependsOn={field.dependsOn}
    />
  );
}
