/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

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
