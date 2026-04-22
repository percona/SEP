import { useFormContext } from 'react-hook-form';
import MenuItem from '@mui/material/MenuItem';
import { RadioGroup, SelectInput } from '@percona/percona-ui';
import type { ChoiceField as ChoiceFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface ChoiceFieldProps {
  field: ChoiceFieldType;
}

// Small option sets render better as radios; larger as a select.
const RADIO_THRESHOLD = 3;

export function ChoiceField({ field }: ChoiceFieldProps) {
  const { control } = useFormContext();
  const rules = buildValidationRules(field);

  if (field.choices.length > 0 && field.choices.length <= RADIO_THRESHOLD) {
    return (
      <RadioGroup
        name={field.name}
        label={field.label}
        isRequired={field.required}
        control={control}
        labelProps={{ caption: field.description }}
        options={field.choices}
        controllerProps={{ rules }}
      />
    );
  }

  return (
    <SelectInput
      name={field.name}
      label={field.label}
      isRequired={field.required}
      control={control}
      helperText={field.description}
      selectFieldProps={{ fullWidth: true }}
      controllerProps={{ name: field.name, rules }}
    >
      {field.choices.map((choice) => (
        <MenuItem key={choice.value} value={choice.value}>
          {choice.label}
        </MenuItem>
      ))}
    </SelectInput>
  );
}
