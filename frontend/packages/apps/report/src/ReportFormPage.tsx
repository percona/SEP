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

import { Controller, useForm } from 'react-hook-form';
import { useNavigate } from 'react-router';
import {
  Box,
  Button,
  FormControl,
  FormControlLabel,
  FormHelperText,
  FormLabel,
  InputLabel,
  MenuItem,
  Radio,
  RadioGroup,
  Select,
  Typography,
} from '@mui/material';
import type { ReportParams } from './types';

const SINCE_OPTIONS = [
  { value: 'now-1d', label: 'Last 24 hours' },
  { value: 'now-3d', label: 'Last 3 days' },
  { value: 'now-7d', label: 'Last 7 days' },
  { value: 'now-14d', label: 'Last 14 days' },
  { value: 'now-30d', label: 'Last 30 days' },
];

const UNTIL_OPTIONS = [
  { value: 'now', label: 'Now' },
  { value: 'now-1d', label: '1 day ago' },
  { value: 'now-3d', label: '3 days ago' },
  { value: 'now-7d', label: '7 days ago' },
];

const SECTION_OPTIONS = [
  { value: 'advisors', label: 'Advisors' },
  { value: 'alerts', label: 'Alerts' },
  { value: 'backups', label: 'Backups' },
  { value: 'storage', label: 'Disk Usage' },
  { value: 'uptime', label: 'Service Uptime' },
  { value: 'inventory', label: 'Included Services' },
];

interface ReportFormValues {
  since: string;
  until: string;
  full: string;
  refresh: string;
  sections: string[];
}

export function ReportFormPage() {
  const navigate = useNavigate();
  const { control, handleSubmit } = useForm<ReportFormValues>({
    defaultValues: {
      since: 'now-7d',
      until: 'now',
      full: 'true',
      refresh: 'false',
      sections: [],
    },
  });

  const onSubmit = (values: ReportFormValues) => {
    const params: ReportParams = {
      since: values.since,
      until: values.until,
      full: values.full === 'true',
      refresh: values.refresh === 'true',
      sections: values.sections.length > 0 ? values.sections : undefined,
    };
    navigate('result', { state: { params } });
  };

  return (
    <Box sx={{ maxWidth: 600 }}>
      <Typography variant="h4" sx={{ mb: 2 }}>
        Health &amp; Security Report
      </Typography>
      <Typography variant="body1" sx={{ mb: 3 }}>
        Generate a comprehensive report of database health, alerts, backups, disk usage, service
        uptime, and inventory from PMM.
      </Typography>

      <Box component="form" onSubmit={handleSubmit(onSubmit)}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Report Period
        </Typography>

        <Controller
          name="since"
          control={control}
          render={({ field }) => (
            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel id="since-label">From</InputLabel>
              <Select {...field} labelId="since-label" label="From">
                {SINCE_OPTIONS.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
        />

        <Controller
          name="until"
          control={control}
          render={({ field }) => (
            <FormControl fullWidth sx={{ mb: 3 }}>
              <InputLabel id="until-label">To</InputLabel>
              <Select {...field} labelId="until-label" label="To">
                {UNTIL_OPTIONS.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
        />

        <Typography variant="h6" sx={{ mb: 1 }}>
          Options
        </Typography>

        <Controller
          name="full"
          control={control}
          render={({ field }) => (
            <FormControl sx={{ mb: 2 }}>
              <FormLabel>Report Type</FormLabel>
              <RadioGroup {...field}>
                <FormControlLabel value="true" control={<Radio />} label="Full report" />
                <FormControlLabel
                  value="false"
                  control={<Radio />}
                  label="Summary only (failures and recent backups)"
                />
              </RadioGroup>
            </FormControl>
          )}
        />

        <Controller
          name="refresh"
          control={control}
          render={({ field }) => (
            <FormControl sx={{ mb: 3 }}>
              <FormLabel>Advisor Results</FormLabel>
              <RadioGroup {...field}>
                <FormControlLabel
                  value="false"
                  control={<Radio />}
                  label="Use cached advisor results"
                />
                <FormControlLabel
                  value="true"
                  control={<Radio />}
                  label="Refresh advisor checks before fetching results"
                />
              </RadioGroup>
            </FormControl>
          )}
        />

        <Controller
          name="sections"
          control={control}
          render={({ field }) => (
            <FormControl fullWidth sx={{ mb: 3 }}>
              <InputLabel id="sections-label">
                Sections (optional — all included if empty)
              </InputLabel>
              <Select
                {...field}
                labelId="sections-label"
                label="Sections (optional — all included if empty)"
                multiple
              >
                {SECTION_OPTIONS.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
              <FormHelperText>
                Filters the generated report, PDF, and ServiceNow upload.
              </FormHelperText>
            </FormControl>
          )}
        />

        <Button type="submit" variant="contained" size="large">
          Generate Report
        </Button>
      </Box>
    </Box>
  );
}
