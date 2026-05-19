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

import { Box, Typography } from '@mui/material';
import { Route, Routes, useParams } from 'react-router-dom';

function TasksListShell() {
  return (
    <Box>
      <Typography variant="h4" component="h1">
        Task Manager
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
        View task definitions, execution history, and running task logs. Task creation and execution
        remain on owning plugins and the legacy /tasks/ page.
      </Typography>
    </Box>
  );
}

function TaskDetailShell() {
  const { taskName } = useParams<{ taskName: string }>();

  return (
    <Box>
      <Typography variant="h4" component="h1">
        {taskName ?? 'Task'}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
        Task detail view (shell).
      </Typography>
    </Box>
  );
}

export function TasksPlugin() {
  return (
    <Routes>
      <Route index element={<TasksListShell />} />
      <Route path=":taskName" element={<TaskDetailShell />} />
    </Routes>
  );
}
