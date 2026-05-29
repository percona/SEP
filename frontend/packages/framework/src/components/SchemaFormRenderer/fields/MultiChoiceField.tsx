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

import { Controller, useFormContext, useWatch } from 'react-hook-form';
import Box from '@mui/material/Box';
import Checkbox from '@mui/material/Checkbox';
import FormControl from '@mui/material/FormControl';
import FormHelperText from '@mui/material/FormHelperText';
import InputLabel from '@mui/material/InputLabel';
import ListItemText from '@mui/material/ListItemText';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import type { MultiChoiceField as MultiChoiceFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface MultiChoiceFieldProps {
  field: MultiChoiceFieldType;
}

export function MultiChoiceField({ field }: MultiChoiceFieldProps) {
  const { control } = useFormContext();
  const selected = (useWatch({ control, name: field.name }) as string[] | undefined) ?? [];
  const labelId = `${field.name}-label`;

  return (
    <Controller
      name={field.name}
      control={control}
      rules={buildValidationRules(field)}
      render={({ field: rhfField, fieldState: { error } }) => (
        <FormControl fullWidth size="small" error={!!error} sx={{ mt: 3 }}>
          <InputLabel id={labelId} shrink required={field.required}>
            {field.label}
          </InputLabel>
          <Select
            {...rhfField}
            labelId={labelId}
            label={field.label}
            multiple
            displayEmpty
            notched
            data-testid={`select-${field.name}-button`}
            inputProps={{ 'data-testid': `select-input-${field.name}` }}
            renderValue={(value) => {
              const values = (value as string[] | undefined) ?? [];
              if (values.length === 0) {
                return (
                  <Box component="span" sx={{ color: 'text.disabled' }}>
                    Select…
                  </Box>
                );
              }
              return field.choices
                .filter((c) => values.includes(c.value))
                .map((c) => c.label)
                .join(', ');
            }}
          >
            {field.choices.map((choice) => (
              <MenuItem key={choice.value} value={choice.value}>
                <Checkbox checked={selected.includes(choice.value)} />
                <ListItemText primary={choice.label} />
              </MenuItem>
            ))}
          </Select>
          {(error?.message || field.description) && (
            <FormHelperText>{error?.message ?? field.description}</FormHelperText>
          )}
        </FormControl>
      )}
    />
  );
}
