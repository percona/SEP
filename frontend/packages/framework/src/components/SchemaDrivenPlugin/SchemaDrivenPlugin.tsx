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

import { Routes, Route } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Typography from '@mui/material/Typography';
import { usePluginSchema, type PluginSchema } from '@sep/api';
import { PluginListPage } from './PluginListPage';
import { PluginCreatePage } from './PluginCreatePage';
import { PluginDetailPage } from './PluginDetailPage';
import { PluginSchedulePage } from './PluginSchedulePage';

interface SchemaDrivenPluginProps {
  pluginName: string;
  mockSchema?: PluginSchema;
  mockTasks?: Record<string, unknown>[];
}

export function SchemaDrivenPlugin({ pluginName, mockSchema, mockTasks }: SchemaDrivenPluginProps) {
  const { data: schema, isLoading, error } = usePluginSchema(pluginName, mockSchema);

  if (isLoading && !schema) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error && !schema) {
    return (
      <Box sx={{ py: 4 }}>
        <Typography color="error">Failed to load plugin schema: {error.message}</Typography>
      </Box>
    );
  }

  if (!schema) {
    return null;
  }

  return (
    <Routes>
      <Route
        index
        element={<PluginListPage schema={schema} pluginName={pluginName} mockTasks={mockTasks} />}
      />
      <Route
        path="new"
        element={<PluginCreatePage schema={schema} pluginName={pluginName} mockTasks={mockTasks} />}
      />
      <Route path="schedule" element={<PluginSchedulePage pluginName={pluginName} />} />
      {/* Detail routes namespaced under `task/` so a task literally named
          `new`, `schedule`, or any other static sibling stays reachable. */}
      <Route
        path="task/:id/*"
        element={<PluginDetailPage schema={schema} pluginName={pluginName} mockTasks={mockTasks} />}
      />
    </Routes>
  );
}
