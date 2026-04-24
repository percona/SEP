import { useFormContext } from 'react-hook-form';
import { TextInput } from '@percona/percona-ui';
import type { DateTimeField as DateTimeFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface DateTimeFieldProps {
  field: DateTimeFieldType;
}

export function DateTimeField({ field }: DateTimeFieldProps) {
  const { control } = useFormContext();
  return (
    <TextInput
      name={field.name}
      label={field.label}
      isRequired={field.required}
      control={control}
      textFieldProps={{
        type: 'datetime-local',
        helperText: field.description,
        fullWidth: true,
        InputLabelProps: { shrink: true },
      }}
      controllerProps={{ rules: buildValidationRules(field) }}
    />
  );
}
