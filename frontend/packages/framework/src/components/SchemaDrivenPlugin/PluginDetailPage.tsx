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

import { useState } from 'react';
import { Routes, Route, useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import Skeleton from '@mui/material/Skeleton';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Typography from '@mui/material/Typography';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DeleteIcon from '@mui/icons-material/Delete';
import { useSnackbar } from 'notistack';
import { useDeletePluginTask, usePluginTask, type PluginSchema } from '@sep/api';
import { TaskHistoryTable, type TaskHistoryEntry } from '../TaskHistoryTable';
import { TaskLogViewer } from '../TaskLogViewer';
import { useTaskHistoryByName } from '../../hooks';

interface PluginDetailPageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
}

function DetailField({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === '') {
    return null;
  }

  let display: React.ReactNode;
  if (typeof value === 'boolean') {
    display = value ? 'Yes' : 'No';
  } else if (typeof value === 'object') {
    display = (
      <Typography
        component="pre"
        variant="body2"
        sx={{ fontFamily: "'Roboto Mono', monospace", whiteSpace: 'pre-wrap' }}
      >
        {JSON.stringify(value, null, 2) as string}
      </Typography>
    );
  } else {
    display = String(value);
  }

  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      {typeof value === 'object' ? display : <Typography variant="body1">{display}</Typography>}
    </Box>
  );
}

interface OverviewTabProps {
  schema: PluginSchema;
  task: Record<string, unknown>;
  pluginName: string;
  taskId: string;
}

function OverviewTab({ schema, task, pluginName, taskId }: OverviewTabProps) {
  const navigate = useNavigate();
  const { enqueueSnackbar } = useSnackbar();
  const deleteTask = useDeletePluginTask(pluginName);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const handleDelete = async () => {
    try {
      await deleteTask.mutateAsync(taskId);
      enqueueSnackbar(`${schema.displayName} task deleted`, { variant: 'success' });
      navigate('../..');
    } catch (e) {
      enqueueSnackbar(e instanceof Error ? e.message : 'Failed to delete task', {
        variant: 'error',
      });
    } finally {
      setConfirmOpen(false);
    }
  };

  return (
    <>
      <Paper sx={{ p: 3 }}>
        {schema.listView.columns.map((col) => (
          <DetailField key={col.key} label={col.label} value={task[col.key]} />
        ))}

        {/* Show any extra fields not in listView columns */}
        {Object.entries(task)
          .filter(([key]) => !schema.listView.columns.some((c) => c.key === key) && key !== 'id')
          .map(([key, value]) => (
            <DetailField key={key} label={key} value={value} />
          ))}
      </Paper>

      <Box sx={{ mt: 3, display: 'flex', justifyContent: 'flex-end' }}>
        <Button
          variant="outlined"
          color="error"
          startIcon={<DeleteIcon />}
          onClick={() => setConfirmOpen(true)}
          disabled={deleteTask.isPending}
          data-testid="plugin-task-delete"
        >
          Delete
        </Button>
      </Box>

      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <DialogTitle>Delete {schema.displayName} task?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will permanently remove the task definition. Past run history is unaffected.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)} disabled={deleteTask.isPending}>
            Cancel
          </Button>
          <Button
            onClick={handleDelete}
            color="error"
            variant="contained"
            disabled={deleteTask.isPending}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

interface LogsTabProps {
  taskName: string;
}

function LogsTab({ taskName }: LogsTabProps) {
  const historyQuery = useTaskHistoryByName(taskName);
  const [logsEntry, setLogsEntry] = useState<TaskHistoryEntry | null>(null);

  return (
    <>
      <TaskHistoryTable
        data={historyQuery.data?.items ?? []}
        isLoading={historyQuery.isLoading}
        hideTaskNameColumn
        onViewLogs={setLogsEntry}
      />

      <Dialog open={logsEntry !== null} onClose={() => setLogsEntry(null)} fullWidth maxWidth="lg">
        <DialogTitle>
          Logs — {taskName}
          {logsEntry?.id !== null && logsEntry?.id !== undefined ? ` #${logsEntry.id}` : ''}
        </DialogTitle>
        <DialogContent dividers sx={{ p: 0 }}>
          {logsEntry?.id !== null && logsEntry?.id !== undefined && (
            <TaskLogViewer
              taskHistoryId={logsEntry.id}
              taskStatus={logsEntry.status}
              height={520}
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

export function PluginDetailPage({ schema, pluginName, mockTasks }: PluginDetailPageProps) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { data: task, isLoading } = usePluginTask(pluginName, id, mockTasks);

  // Tab value derived from the trailing path segment.
  const tabValue = location.pathname.endsWith('/logs') ? 'logs' : 'overview';

  if (isLoading) {
    return (
      <Box>
        <Skeleton variant="text" width={300} height={40} />
        <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (!task || !id) {
    return (
      <Box>
        <Typography variant="h5">Task not found</Typography>
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <IconButton onClick={() => navigate('..')} aria-label="Back to list">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">
          {schema.displayName} #{id}
        </Typography>
        {typeof task.status === 'string' && (
          <Chip
            label={task.status}
            size="small"
            color={
              task.status === 'completed' || task.status === 'success'
                ? 'success'
                : task.status === 'failed'
                  ? 'error'
                  : 'default'
            }
          />
        )}
      </Box>

      <Tabs value={tabValue} sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Overview" value="overview" component={Link} to="" replace />
        <Tab label="Logs" value="logs" component={Link} to="logs" replace />
      </Tabs>

      <Routes>
        <Route
          index
          element={<OverviewTab schema={schema} task={task} pluginName={pluginName} taskId={id} />}
        />
        <Route
          path="logs"
          element={<LogsTab taskName={typeof task.name === 'string' ? task.name : id} />}
        />
      </Routes>
    </Box>
  );
}
