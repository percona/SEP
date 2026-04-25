import { useFormContext } from 'react-hook-form';
import { TextInput } from '@percona/percona-ui';
import type { IntegerField as IntegerFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface IntegerFieldProps {
  field: IntegerFieldType;
}

export function IntegerField({ field }: IntegerFieldProps) {
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
          step: field.step ?? 1,
        },
      }}
      controllerProps={{ rules: buildValidationRules(field) }}
    />
  );
}
