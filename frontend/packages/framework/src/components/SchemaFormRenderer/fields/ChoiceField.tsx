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

import { Controller, useFormContext } from 'react-hook-form';
import Box from '@mui/material/Box';
import MenuItem from '@mui/material/MenuItem';
import { RadioGroup } from '@percona/percona-ui';
import { SchemaSelectShell } from '../SchemaSelectShell';
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

  const labelId = `${field.name}-label`;

  return (
    <Controller
      name={field.name}
      control={control}
      rules={rules}
      render={({ field: rhfField, fieldState: { error } }) => (
        <SchemaSelectShell
          field={rhfField}
          labelId={labelId}
          label={field.label}
          required={field.required}
          error={error}
          description={field.description}
          renderValue={(value) => {
            if (value === undefined || value === null || value === '') {
              return (
                <Box component="span" sx={{ color: 'text.disabled' }}>
                  Select…
                </Box>
              );
            }
            return field.choices.find((c) => c.value === value)?.label ?? String(value);
          }}
        >
          {field.choices.map((choice) => (
            <MenuItem key={choice.value} value={choice.value}>
              {choice.label}
            </MenuItem>
          ))}
        </SchemaSelectShell>
      )}
    />
  );
}
