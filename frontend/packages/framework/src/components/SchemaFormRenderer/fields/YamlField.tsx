import { useFormContext } from 'react-hook-form';
import { TextInput } from '@percona/percona-ui';
import type { YamlField as YamlFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface YamlFieldProps {
  field: YamlFieldType;
}

export function YamlField({ field }: YamlFieldProps) {
  const { control } = useFormContext();
  return (
    <TextInput
      name={field.name}
      label={field.label}
      isRequired={field.required}
      control={control}
      textFieldProps={{
        multiline: true,
        rows: field.rows ?? 8,
        placeholder: field.placeholder,
        helperText: field.description,
        fullWidth: true,
        inputProps: {
          style: { fontFamily: "'Roboto Mono', monospace", fontSize: 13 },
          spellCheck: false,
        },
      }}
      controllerProps={{ rules: buildValidationRules(field) }}
    />
  );
}
