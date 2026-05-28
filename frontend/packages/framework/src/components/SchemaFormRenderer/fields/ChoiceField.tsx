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
      formControlProps={{ fullWidth: true }}
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
