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

import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import ScheduleIcon from '@mui/icons-material/Schedule';
import { usePluginTasks, type PluginSchema } from '@sep/api';
import { SchemaListView } from '../SchemaListView';

interface PluginListPageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
}

export function PluginListPage({ schema, pluginName, mockTasks }: PluginListPageProps) {
  const navigate = useNavigate();
  const { data: tasks = [], isLoading } = usePluginTasks(pluginName, mockTasks);

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4">{schema.displayName}</Typography>
          {schema.description && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {schema.description}
            </Typography>
          )}
        </Box>
        <Stack direction="row" spacing={1}>
          {schema.capabilities?.scheduling && (
            <Button
              variant="outlined"
              startIcon={<ScheduleIcon />}
              onClick={() => navigate('schedule')}
              data-testid="plugin-schedule-link"
            >
              Schedules
            </Button>
          )}
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => navigate('new')}>
            New {schema.displayName}
          </Button>
        </Stack>
      </Box>

      <SchemaListView
        listView={schema.listView}
        data={tasks}
        isLoading={isLoading}
        onRowClick={(row) => {
          // Backend per-plugin detail/delete routes look up by `task_name`
          // (string), not numeric `id`. The first listView column is
          // typically `name`; fall back to id only if name is absent.
          // `encodeURIComponent` escapes characters that would otherwise
          // change URL structure (`/`, `?`, `#`, space, ...).
          const key = row.name ?? row.id;
          if (key !== undefined && key !== null) {
            navigate(`task/${encodeURIComponent(String(key))}`);
          }
        }}
      />
    </Box>
  );
}
