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

import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import ScheduleIcon from '@mui/icons-material/Schedule';

interface ScheduledTasksPanelProps {
  pluginName: string;
}

// TODO: implement scheduled tasks management UI
export function ScheduledTasksPanel({ pluginName }: ScheduledTasksPanelProps) {
  return (
    <Paper variant="outlined" sx={{ p: 3, textAlign: 'center' }}>
      <ScheduleIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
      <Typography variant="h6" gutterBottom>
        Scheduled Tasks
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Configure recurring {pluginName} tasks with cron-based scheduling. This feature will be
        available when the backend supports task scheduling.
      </Typography>
    </Paper>
  );
}
