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
import { Routes, Route, useParams, useNavigate, Link } from 'react-router-dom';
import Alert from '@mui/material/Alert';
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
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import ScheduleIcon from '@mui/icons-material/Schedule';
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

// Fields hidden from the auto-rendered "extras" loop on the Overview tab.
// Numeric `id`, internal worker plumbing (`backend`, `protected`), and
// timestamps already shown in the list_view columns. The `data` payload is
// rendered as the structured "Execution" section.
const OVERVIEW_HIDDEN_FIELDS = new Set([
  'id',
  'backend',
  'protected',
  'data',
  'updated_at',
  'last_updated_by',
  'connectivity_warning',
]);

function formatLabel(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function DetailField({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === '') {
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
        sx={{ fontFamily: "'Roboto Mono', monospace", whiteSpace: 'pre-wrap', m: 0 }}
      >
        {JSON.stringify(value, null, 2) as string}
      </Typography>
    );
  } else {
    display = String(value);
  }

  return (
    <Box sx={{ mb: 2, '&:last-child': { mb: 0 } }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
        {label}
      </Typography>
      {typeof value === 'object' ? display : <Typography variant="body1">{display}</Typography>}
    </Box>
  );
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        {title}
      </Typography>
      {children}
    </Paper>
  );
}

interface ExecutionData {
  command?: unknown;
  args?: unknown;
  target?: unknown;
}

export function pickExecutionData(task: Record<string, unknown>): ExecutionData | null {
  // Backend task model nests the executed command under `data.meta` (see
  // e.g. `app/sep/plugins/checksums/deps.py`). Older flows may put the
  // same keys at `data.*` directly, so check both for forward-compat.
  const data = task.data;
  if (!data || typeof data !== 'object') {
    return null;
  }
  const dataObj = data as { meta?: unknown } & ExecutionData;
  const meta =
    dataObj.meta && typeof dataObj.meta === 'object' ? (dataObj.meta as ExecutionData) : null;
  const command = meta?.command ?? dataObj.command;
  const args = meta?.args ?? dataObj.args;
  const target = meta?.target ?? dataObj.target;
  if (command === undefined && args === undefined && target === undefined) {
    return null;
  }
  return { command, args, target };
}

export function resolveTabFromSplat(splat: string | undefined): 'overview' | 'logs' {
  return splat?.replace(/\/+$/, '').startsWith('logs') ? 'logs' : 'overview';
}

interface OverviewTabProps {
  schema: PluginSchema;
  task: Record<string, unknown>;
}

function OverviewTab({ schema, task }: OverviewTabProps) {
  const execution = pickExecutionData(task);
  const connectivityWarning = task.connectivity_warning;

  // Extra fields beyond the schema's list_view columns, excluding internal
  // noise. Lets future plugin schemas surface fields without listing them
  // in `list_view.columns` (which is meant for the table view).
  const extraEntries = Object.entries(task).filter(
    ([key]) =>
      !schema.list_view.columns.some((c) => c.key === key) && !OVERVIEW_HIDDEN_FIELDS.has(key),
  );

  return (
    <>
      {connectivityWarning !== null &&
        connectivityWarning !== undefined &&
        typeof connectivityWarning === 'object' && (
          <Alert severity="warning" sx={{ mb: 3 }}>
            {('message' in connectivityWarning &&
              typeof connectivityWarning.message === 'string' &&
              connectivityWarning.message) ||
              'Connectivity check returned a warning for this task.'}
          </Alert>
        )}

      <SectionCard title="Task information">
        {schema.list_view.columns.map((col) => (
          <DetailField key={col.key} label={col.label} value={task[col.key]} />
        ))}
        {extraEntries.map(([key, value]) => (
          <DetailField key={key} label={formatLabel(key)} value={value} />
        ))}
      </SectionCard>

      {execution && (
        <SectionCard title="Execution">
          {execution.command !== undefined && (
            <DetailField label="Command" value={execution.command} />
          )}
          {execution.args !== undefined && <DetailField label="Args" value={execution.args} />}
          {execution.target !== undefined && (
            <DetailField label="Target" value={execution.target} />
          )}
        </SectionCard>
      )}
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
      {historyQuery.error ? (
        <Alert severity="error" sx={{ mb: 3 }}>
          Failed to load execution history: {historyQuery.error.message}
        </Alert>
      ) : (
        <Paper variant="outlined" sx={{ p: 0, mb: 3 }}>
          <TaskHistoryTable
            data={historyQuery.data?.items ?? []}
            isLoading={historyQuery.isLoading}
            hideTaskNameColumn
            onViewLogs={setLogsEntry}
          />
        </Paper>
      )}

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

interface ActionBarProps {
  schema: PluginSchema;
  pluginName: string;
  taskId: string;
}

function ActionBar({ schema, pluginName, taskId }: ActionBarProps) {
  const navigate = useNavigate();
  const { enqueueSnackbar } = useSnackbar();
  const deleteTask = useDeletePluginTask(pluginName);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const handleDelete = async () => {
    try {
      await deleteTask.mutateAsync(taskId);
      enqueueSnackbar(`${schema.display_name} task deleted`, { variant: 'success' });
      // Anchor to the plugin root explicitly. Relative `..` chains depend
      // on which tab the user is on (Overview vs. Logs renders a deeper
      // sub-route via nested `<Routes>`), so use an absolute path.
      navigate(`/plugins/${pluginName}`);
    } catch (e) {
      enqueueSnackbar(e instanceof Error ? e.message : 'Failed to delete task', {
        variant: 'error',
      });
    } finally {
      setConfirmOpen(false);
    }
  };

  const blocked = 'Backend support pending';

  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 3 }}>
        {schema.capabilities?.scheduling && (
          <Button
            variant="outlined"
            startIcon={<ScheduleIcon />}
            onClick={() => navigate(`/plugins/${pluginName}/schedule`)}
            data-testid="plugin-task-schedule"
          >
            Schedule
          </Button>
        )}

        <Tooltip title={blocked}>
          <span>
            <Button
              variant="outlined"
              startIcon={<PlayArrowIcon />}
              disabled
              data-testid="plugin-task-execute"
            >
              Execute
            </Button>
          </span>
        </Tooltip>

        <Tooltip title={blocked}>
          <span>
            <Button
              variant="outlined"
              startIcon={<EditIcon />}
              disabled
              data-testid="plugin-task-edit"
            >
              Edit
            </Button>
          </span>
        </Tooltip>

        <Box sx={{ flexGrow: 1 }} />

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
      </Stack>

      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <DialogTitle>Delete {schema.display_name} task?</DialogTitle>
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

export function PluginDetailPage({ schema, pluginName, mockTasks }: PluginDetailPageProps) {
  const { id, '*': splat } = useParams<{ id: string; '*': string }>();
  const navigate = useNavigate();
  const { data: task, isLoading } = usePluginTask(pluginName, id, mockTasks);

  // Derive the active tab from the splat (the path segment(s) after `:id`)
  // rather than scanning the full pathname. Using the splat avoids a
  // false-positive when the task itself is literally named `logs`
  // (`/plugins/<name>/task/logs` would otherwise highlight the Logs tab
  // while the inner `<Routes>` correctly renders Overview).
  const tabValue = resolveTabFromSplat(splat);

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

  const taskName = typeof task.name === 'string' ? task.name : id;
  const detailBase = `/plugins/${pluginName}/task/${encodeURIComponent(id)}`;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <IconButton onClick={() => navigate(`/plugins/${pluginName}`)} aria-label="Back to list">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="overline" color="text.secondary">
          {schema.display_name}
        </Typography>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3, ml: 5 }}>
        <Typography variant="h4">{taskName}</Typography>
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

      <ActionBar schema={schema} pluginName={pluginName} taskId={id} />

      <Tabs value={tabValue} sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Overview" value="overview" component={Link} to={detailBase} replace />
        <Tab label="Logs" value="logs" component={Link} to={`${detailBase}/logs`} replace />
      </Tabs>

      <Routes>
        <Route index element={<OverviewTab schema={schema} task={task} />} />
        <Route path="logs" element={<LogsTab taskName={taskName} />} />
      </Routes>
    </Box>
  );
}
