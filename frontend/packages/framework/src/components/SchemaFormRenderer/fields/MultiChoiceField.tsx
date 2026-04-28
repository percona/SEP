import { useFormContext, useWatch } from 'react-hook-form';
import MenuItem from '@mui/material/MenuItem';
import Checkbox from '@mui/material/Checkbox';
import ListItemText from '@mui/material/ListItemText';
import { SelectInput } from '@percona/percona-ui';
import type { MultiChoiceField as MultiChoiceFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface MultiChoiceFieldProps {
  field: MultiChoiceFieldType;
}

export function MultiChoiceField({ field }: MultiChoiceFieldProps) {
  const { control } = useFormContext();
  const selected = (useWatch({ control, name: field.name }) as string[] | undefined) ?? [];

  return (
    <SelectInput
      name={field.name}
      label={field.label}
      isRequired={field.required}
      control={control}
      helperText={field.description}
      selectFieldProps={{
        fullWidth: true,
        multiple: true,
        renderValue: (value) => {
          const values = (value as string[]) ?? [];
          return field.choices
            .filter((c) => values.includes(c.value))
            .map((c) => c.label)
            .join(', ');
        },
      }}
      controllerProps={{ name: field.name, rules: buildValidationRules(field) }}
    >
      {field.choices.map((choice) => (
        <MenuItem key={choice.value} value={choice.value}>
          <Checkbox checked={selected.includes(choice.value)} />
          <ListItemText primary={choice.label} />
        </MenuItem>
      ))}
    </SelectInput>
  );
}
