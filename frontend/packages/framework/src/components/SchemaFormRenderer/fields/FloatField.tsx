import { useFormContext } from 'react-hook-form';
import { TextInput } from '@percona/percona-ui';
import type { FloatField as FloatFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface FloatFieldProps {
  field: FloatFieldType;
}

export function FloatField({ field }: FloatFieldProps) {
  const { control } = useFormContext();
  return (
    <TextInput
      name={field.name}
      label={field.label}
      isRequired={field.required}
      control={control}
      textFieldProps={{
        type: 'number',
        helperText: field.description,
        fullWidth: true,
        inputProps: {
          min: field.ge,
          max: field.le,
          step: field.step ?? 'any',
        },
      }}
      controllerProps={{ rules: buildValidationRules(field) }}
    />
  );
}
