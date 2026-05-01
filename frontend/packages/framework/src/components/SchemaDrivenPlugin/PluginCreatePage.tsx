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
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useSnackbar } from 'notistack';
import { useCreatePluginTask, type PluginSchema } from '@sep/api';
import { SchemaFormRenderer } from '../SchemaFormRenderer';

interface PluginCreatePageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
}

export function PluginCreatePage({ schema, pluginName, mockTasks }: PluginCreatePageProps) {
  const navigate = useNavigate();
  const { enqueueSnackbar } = useSnackbar();
  const createTask = useCreatePluginTask(pluginName, mockTasks);

  const handleSubmit = (data: Record<string, unknown>) => {
    createTask.mutate(data, {
      onSuccess: () => {
        enqueueSnackbar(`${schema.displayName} task created`, { variant: 'success' });
        navigate('..');
      },
      onError: (error) => {
        enqueueSnackbar(error.message || 'Failed to create task', { variant: 'error' });
      },
    });
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
        <IconButton onClick={() => navigate('..')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">New {schema.displayName}</Typography>
      </Box>

      <SchemaFormRenderer
        sections={schema.forms}
        onSubmit={handleSubmit}
        loading={createTask.isPending}
        submitLabel={`Create ${schema.displayName}`}
      />
    </Box>
  );
}
