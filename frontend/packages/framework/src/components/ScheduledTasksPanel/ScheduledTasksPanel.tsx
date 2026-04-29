import { useMemo, useState } from 'react';
import AddIcon from '@mui/icons-material/Add';
import ScheduleIcon from '@mui/icons-material/Schedule';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import { ScheduledTaskForm } from './ScheduledTaskForm';
import { ScheduledTaskRow } from './ScheduledTaskRow';
import {
  useCreateScheduledTask,
  useDeleteScheduledTask,
  useScheduledTasksForPlugin,
  useUpdateScheduledTask,
  type PeriodicTaskCreate,
  type PeriodicTaskResponse,
  type PeriodicTaskUpdate,
} from './hooks';

interface ScheduledTasksPanelProps {
  pluginName: string;
}

const COLUMN_HEADERS = [
  'Task',
  'Period',
  'Start Time',
  'Last Run',
  'Next Run',
  'Runs',
  'Chain',
  'Enabled',
  'Actions',
];

export function ScheduledTasksPanel({ pluginName }: ScheduledTasksPanelProps) {
  const { periodicTasks, pluginTasks, isLoading, isError, error } =
    useScheduledTasksForPlugin(pluginName);

  const createMut = useCreateScheduledTask();
  const updateMut = useUpdateScheduledTask();
  const deleteMut = useDeleteScheduledTask();

  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | undefined>(undefined);

  const availableTasks = useMemo(() => pluginTasks.map((t) => ({ name: t.name })), [pluginTasks]);

  const handleToggleEnabled = (task: PeriodicTaskResponse, nextEnabled: boolean) => {
    // PeriodicTaskUpdate requires `kwargs` and `description`, but
    // PeriodicTaskResponse exposes only `description`. Tasks created elsewhere
    // with non-default kwargs will have them reset to '{}' on toggle. Tracked
    // upstream as a backend schema gap.
    const body: PeriodicTaskUpdate = {
      name: task.name,
      task: task.task,
      enabled: nextEnabled,
      description: task.description,
      kwargs: '{}',
      start_time: task.start_time,
      interval: task.interval ?? null,
      crontab: task.crontab ?? null,
      execute_request: task.execute_request ?? null,
    };
    updateMut.mutate({ id: task.id, body });
  };

  const handleDelete = (task: PeriodicTaskResponse) => {
    deleteMut.mutate(task.id);
  };

  const handleCreate = async (body: PeriodicTaskCreate | PeriodicTaskUpdate, taskName: string) => {
    setFormError(undefined);
    try {
      await createMut.mutateAsync({ taskName, body: body as PeriodicTaskCreate });
      setCreating(false);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Failed to create scheduled task');
    }
  };

  const handleEditSubmit = (task: PeriodicTaskResponse) => {
    return async (body: PeriodicTaskCreate | PeriodicTaskUpdate) => {
      setFormError(undefined);
      try {
        await updateMut.mutateAsync({ id: task.id, body: body as PeriodicTaskUpdate });
        setEditingId(null);
      } catch (e) {
        setFormError(e instanceof Error ? e.message : 'Failed to update scheduled task');
      }
    };
  };

  const startCreate = () => {
    setEditingId(null);
    setFormError(undefined);
    setCreating(true);
  };

  const startEdit = (id: number) => {
    setCreating(false);
    setFormError(undefined);
    setEditingId(id);
  };

  const headerRow = (
    <TableHead>
      <TableRow>
        {COLUMN_HEADERS.map((h) => (
          <TableCell key={h}>{h}</TableCell>
        ))}
      </TableRow>
    </TableHead>
  );

  if (isLoading) {
    return (
      <Paper variant="outlined" sx={{ p: 3, textAlign: 'center' }}>
        <CircularProgress size={24} />
      </Paper>
    );
  }

  if (isError) {
    return (
      <Alert severity="error">
        Failed to load scheduled tasks{error ? `: ${error.message}` : ''}
      </Alert>
    );
  }

  const isEmpty = periodicTasks.length === 0 && !creating;

  return (
    <Paper variant="outlined" data-testid="scheduled-tasks-panel">
      <Box sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
        <ScheduleIcon fontSize="small" />
        <Typography variant="h6">Scheduled Tasks</Typography>
      </Box>

      {isEmpty ? (
        <Box sx={{ p: 3, textAlign: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            No scheduled tasks for {pluginName}.
          </Typography>
        </Box>
      ) : (
        <TableContainer>
          <Table size="small">
            {headerRow}
            <TableBody>
              {periodicTasks.map((task) => (
                <ScheduledTaskRow
                  key={task.id}
                  task={task}
                  availableTasks={availableTasks}
                  isEditing={editingId === task.id}
                  onStartEdit={() => startEdit(task.id)}
                  onCancelEdit={() => setEditingId(null)}
                  onToggleEnabled={handleToggleEnabled}
                  onSubmitEdit={handleEditSubmit(task)}
                  onDelete={handleDelete}
                  submitting={updateMut.isPending}
                  toggling={updateMut.isPending}
                  errorMessage={editingId === task.id ? formError : undefined}
                />
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {creating && (
        <Box sx={{ borderTop: 1, borderColor: 'divider' }}>
          <ScheduledTaskForm
            mode="create"
            availableTasks={availableTasks}
            defaultTaskName={availableTasks[0]?.name}
            onCancel={() => setCreating(false)}
            onSubmit={handleCreate}
            submitting={createMut.isPending}
            errorMessage={formError}
          />
        </Box>
      )}

      {!creating && (
        <Stack
          direction="row"
          justifyContent="flex-end"
          sx={{ p: 1, borderTop: 1, borderColor: 'divider' }}
        >
          <Button
            startIcon={<AddIcon />}
            onClick={startCreate}
            disabled={availableTasks.length === 0}
            data-testid="scheduled-tasks-add"
          >
            Add new
          </Button>
        </Stack>
      )}
    </Paper>
  );
}
