import { useFormContext } from 'react-hook-form';
import { TextInput } from '@percona/percona-ui';
import type { StringField as StringFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface StringFieldProps {
  field: StringFieldType;
}

export function StringField({ field }: StringFieldProps) {
  const { control } = useFormContext();
  return (
    <TextInput
      name={field.name}
      label={field.label}
      isRequired={field.required}
      control={control}
      textFieldProps={{
        placeholder: field.placeholder,
        helperText: field.description,
        fullWidth: true,
      }}
      controllerProps={{ rules: buildValidationRules(field) }}
    />
  );
}
