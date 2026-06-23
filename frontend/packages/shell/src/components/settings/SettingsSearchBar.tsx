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

import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import InputAdornment from '@mui/material/InputAdornment';
import SearchIcon from '@mui/icons-material/Search';

import type { SettingsFilters } from './filters';

export interface SettingsSearchBarProps {
  filters: SettingsFilters;
  onChange: (filters: SettingsFilters) => void;
  /** Setting classes present in the data, used to populate the class filter. */
  settingClasses: string[];
}

/** Search box plus class / reload / override-present / advanced filter controls. */
export default function SettingsSearchBar({
  filters,
  onChange,
  settingClasses,
}: SettingsSearchBarProps) {
  const update = (patch: Partial<SettingsFilters>) => onChange({ ...filters, ...patch });

  return (
    <Stack
      direction={{ xs: 'column', md: 'row' }}
      spacing={2}
      sx={{ mb: 3 }}
      alignItems={{ md: 'center' }}
    >
      <TextField
        size="small"
        label="Search settings"
        placeholder="Filter by key…"
        value={filters.search}
        onChange={(e) => update({ search: e.target.value })}
        sx={{ minWidth: 240, flexGrow: 1 }}
        slotProps={{
          input: {
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          },
          htmlInput: { 'aria-label': 'Search settings' },
        }}
      />

      <TextField
        select
        size="small"
        label="Class"
        value={filters.settingClass}
        onChange={(e) => update({ settingClass: e.target.value })}
        sx={{ minWidth: 180 }}
        slotProps={{ htmlInput: { 'aria-label': 'Filter by class' } }}
      >
        <MenuItem value="all">All classes</MenuItem>
        {settingClasses.map((cls) => (
          <MenuItem key={cls} value={cls}>
            {cls}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        select
        size="small"
        label="Reload"
        value={filters.reload}
        onChange={(e) => update({ reload: e.target.value as SettingsFilters['reload'] })}
        sx={{ minWidth: 160 }}
        slotProps={{ htmlInput: { 'aria-label': 'Filter by reload' } }}
      >
        <MenuItem value="all">All</MenuItem>
        <MenuItem value="hot">Hot</MenuItem>
        <MenuItem value="not_overridable">Not overridable</MenuItem>
      </TextField>

      <TextField
        select
        size="small"
        label="Override"
        value={filters.override}
        onChange={(e) => update({ override: e.target.value as SettingsFilters['override'] })}
        sx={{ minWidth: 160 }}
        slotProps={{ htmlInput: { 'aria-label': 'Filter by override' } }}
      >
        <MenuItem value="all">All</MenuItem>
        <MenuItem value="yes">Override present</MenuItem>
        <MenuItem value="no">No override</MenuItem>
      </TextField>

      <TextField
        select
        size="small"
        label="Advanced"
        value={filters.advanced}
        onChange={(e) => update({ advanced: e.target.value as SettingsFilters['advanced'] })}
        sx={{ minWidth: 160 }}
        slotProps={{ htmlInput: { 'aria-label': 'Filter by advanced' } }}
      >
        <MenuItem value="hidden">Hidden</MenuItem>
        <MenuItem value="shown">Shown</MenuItem>
      </TextField>
    </Stack>
  );
}
