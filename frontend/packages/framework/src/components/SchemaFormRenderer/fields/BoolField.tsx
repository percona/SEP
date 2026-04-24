import { useFormContext } from 'react-hook-form';
import { SwitchInput } from '@percona/percona-ui';
import type { BoolField as BoolFieldType } from '../types';

interface BoolFieldProps {
  field: BoolFieldType;
}

export function BoolField({ field }: BoolFieldProps) {
  const { control } = useFormContext();
  return (
    <SwitchInput
      name={field.name}
      label={field.label}
      labelCaption={field.description}
      control={control}
    />
  );
}
