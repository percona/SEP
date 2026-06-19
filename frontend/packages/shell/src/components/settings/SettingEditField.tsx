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

import Chip from '@mui/material/Chip';
import FormControlLabel from '@mui/material/FormControlLabel';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import type { SettingResponse } from '@sep/api';

import {
  type EditValue,
  formatSettingValue,
  getFieldKind,
  parseLiteralOptions,
} from './settingField';

export interface SettingEditFieldProps {
  setting: SettingResponse;
  value: EditValue;
  onChange: (value: EditValue) => void;
  disabled?: boolean;
  error?: string | null;
}

/**
 * Dispatches a single setting onto the appropriate edit control based on its
 * reported `type`, `is_secret`, and `is_complex` flags. Complex (nested) fields
 * are not editable yet and render a read-only value with an explanatory chip.
 */
export default function SettingEditField({
  setting,
  value,
  onChange,
  disabled = false,
  error = null,
}: SettingEditFieldProps) {
  const kind = getFieldKind(setting);
  const helperText = error ?? undefined;

  switch (kind) {
    case 'complex':
      return (
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
            {formatSettingValue(setting.value)}
          </Typography>
          <Chip size="small" label="nested editing not yet supported" />
        </Stack>
      );

    case 'bool':
      return (
        <FormControlLabel
          control={
            <Switch
              checked={Boolean(value)}
              disabled={disabled}
              onChange={(e) => onChange(e.target.checked)}
              inputProps={{ 'aria-label': `${setting.key} toggle` }}
            />
          }
          label={value ? 'Enabled' : 'Disabled'}
        />
      );

    case 'choice': {
      const options = parseLiteralOptions(setting.type) ?? [];
      return (
        <TextField
          select
          size="small"
          fullWidth
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          error={Boolean(error)}
          helperText={helperText}
          onChange={(e) => onChange(e.target.value)}
          slotProps={{ htmlInput: { 'aria-label': setting.key } }}
        >
          {options.map((opt) => (
            <MenuItem key={opt} value={opt}>
              {opt}
            </MenuItem>
          ))}
        </TextField>
      );
    }

    case 'number':
      return (
        <TextField
          type="number"
          size="small"
          fullWidth
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          error={Boolean(error)}
          helperText={helperText}
          onChange={(e) => onChange(e.target.value)}
          slotProps={{ htmlInput: { 'aria-label': setting.key } }}
        />
      );

    case 'secret':
      return (
        <TextField
          type="password"
          size="small"
          fullWidth
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          error={Boolean(error)}
          helperText={helperText ?? 'Enter a new value to replace the stored secret'}
          placeholder="Enter new secret"
          autoComplete="new-password"
          onChange={(e) => onChange(e.target.value)}
          slotProps={{ htmlInput: { 'aria-label': setting.key } }}
        />
      );

    case 'text':
    default:
      return (
        <TextField
          size="small"
          fullWidth
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          error={Boolean(error)}
          helperText={helperText}
          onChange={(e) => onChange(e.target.value)}
          slotProps={{ htmlInput: { 'aria-label': setting.key } }}
        />
      );
  }
}
