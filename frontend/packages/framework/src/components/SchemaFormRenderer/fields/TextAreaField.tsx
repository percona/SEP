import { useFormContext } from 'react-hook-form';
import { TextInput } from '@percona/percona-ui';
import type { TextAreaField as TextAreaFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface TextAreaFieldProps {
  field: TextAreaFieldType;
}

export function TextAreaField({ field }: TextAreaFieldProps) {
  const { control } = useFormContext();
  return (
    <TextInput
      name={field.name}
      label={field.label}
      isRequired={field.required}
      control={control}
      textFieldProps={{
        multiline: true,
        rows: field.rows ?? 4,
        placeholder: field.placeholder,
        helperText: field.description,
        fullWidth: true,
      }}
      controllerProps={{ rules: buildValidationRules(field) }}
    />
  );
}
