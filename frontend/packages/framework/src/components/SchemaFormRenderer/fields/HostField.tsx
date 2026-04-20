import { useFormContext } from 'react-hook-form';
import { HostSelector } from '../../HostSelector';
import { useCascadingField } from '../hooks/useCascadingField';
import type { HostField as HostFieldType } from '../types';

interface HostFieldProps {
  field: HostFieldType;
}

export function HostField({ field }: HostFieldProps) {
  const { control } = useFormContext();
  useCascadingField({ fieldName: field.name, dependsOn: field.dependsOn });
  return (
    <HostSelector
      name={field.name}
      label={field.label}
      required={field.required}
      dependsOn={field.dependsOn}
      control={control}
    />
  );
}
