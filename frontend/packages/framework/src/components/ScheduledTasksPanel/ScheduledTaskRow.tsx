import { useState } from 'react';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import TableCell from '@mui/material/TableCell';
import TableRow from '@mui/material/TableRow';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import cronstrue from 'cronstrue';
import { ScheduledTaskForm } from './ScheduledTaskForm';
import type { AvailableTask } from '../ChainBuilder';
import type { PeriodicTaskCreate, PeriodicTaskResponse, PeriodicTaskUpdate } from './hooks';

const COLUMN_COUNT = 9;

function formatDateTime(value: string | null): string {
  if (!value) {
    return '—';
  }
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function describePeriod(task: PeriodicTaskResponse): { display: string; tooltip?: string } {
  if (task.crontab) {
    const expr = `${task.crontab.minute} ${task.crontab.hour} ${task.crontab.day_of_month} ${task.crontab.month_of_year} ${task.crontab.day_of_week}`;
    try {
      const human = cronstrue.toString(expr);
      const text = human.charAt(0).toLowerCase() + human.slice(1);
      const tz = task.crontab.timezone;
      return {
        display: text,
        tooltip: tz ? `${expr} (${tz})` : expr,
      };
    } catch {
      return { display: expr, tooltip: 'Invalid cron expression' };
    }
  }
  if (task.interval) {
    return { display: `every ${task.interval.every} ${task.interval.period}` };
  }
  return { display: task.period || '—' };
}

export interface ScheduledTaskRowProps {
  task: PeriodicTaskResponse;
  availableTasks: AvailableTask[];
  isEditing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onToggleEnabled: (task: PeriodicTaskResponse, nextEnabled: boolean) => void;
  onSubmitEdit: (body: PeriodicTaskCreate | PeriodicTaskUpdate, taskName: string) => Promise<void>;
  onDelete: (task: PeriodicTaskResponse) => void;
  submitting?: boolean;
  toggling?: boolean;
  errorMessage?: string;
}

export function ScheduledTaskRow({
  task,
  availableTasks,
  isEditing,
  onStartEdit,
  onCancelEdit,
  onToggleEnabled,
  onSubmitEdit,
  onDelete,
  submitting,
  toggling,
  errorMessage,
}: ScheduledTaskRowProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const period = describePeriod(task);
  const chainNames = task.execute_request?.chain_task_names ?? [];

  if (isEditing) {
    return (
      <TableRow>
        <TableCell colSpan={COLUMN_COUNT} sx={{ p: 0 }}>
          <ScheduledTaskForm
            mode="edit"
            initialValue={task}
            availableTasks={availableTasks}
            onCancel={onCancelEdit}
            onSubmit={onSubmitEdit}
            submitting={submitting}
            errorMessage={errorMessage}
          />
        </TableCell>
      </TableRow>
    );
  }

  return (
    <>
      <TableRow data-testid={`scheduled-task-row-${task.id}`}>
        <TableCell>{task.task}</TableCell>
        <TableCell>
          {period.tooltip ? (
            <Tooltip title={period.tooltip}>
              <span>{period.display}</span>
            </Tooltip>
          ) : (
            period.display
          )}
        </TableCell>
        <TableCell>{formatDateTime(task.start_time)}</TableCell>
        <TableCell>{formatDateTime(task.last_run_at)}</TableCell>
        <TableCell>{formatDateTime(task.next_run_at ?? null)}</TableCell>
        <TableCell>{task.total_run_count}</TableCell>
        <TableCell>
          {chainNames.length > 0 ? (
            <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
              {chainNames.join(' → ')}
            </Typography>
          ) : (
            '—'
          )}
        </TableCell>
        <TableCell>
          <Switch
            checked={task.enabled}
            disabled={toggling}
            onChange={(_, checked) => onToggleEnabled(task, checked)}
            slotProps={{
              input: {
                'aria-label': `Enable ${task.task}`,
              },
            }}
          />
        </TableCell>
        <TableCell>
          <Stack direction="row" spacing={0.5}>
            <Tooltip title="Edit">
              <IconButton
                size="small"
                onClick={onStartEdit}
                aria-label={`Edit ${task.task}`}
                data-testid={`scheduled-task-edit-${task.id}`}
              >
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Delete">
              <IconButton
                size="small"
                onClick={() => setConfirmOpen(true)}
                aria-label={`Delete ${task.task}`}
                data-testid={`scheduled-task-delete-${task.id}`}
              >
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        </TableCell>
      </TableRow>

      <Dialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        aria-labelledby={`scheduled-task-delete-title-${task.id}`}
      >
        <DialogTitle id={`scheduled-task-delete-title-${task.id}`}>
          Delete periodic task
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            {`Delete the periodic task for "${task.task}" (${period.display})?`}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button
            onClick={() => {
              setConfirmOpen(false);
              onDelete(task);
            }}
            color="error"
            variant="contained"
            autoFocus
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
