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

import { useState, useMemo } from 'react';
import AddIcon from '@mui/icons-material/Add';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import ScheduleIcon from '@mui/icons-material/Schedule';
import Alert from '@mui/material/Alert';
import Autocomplete from '@mui/material/Autocomplete';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import FormLabel from '@mui/material/FormLabel';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Radio from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import cronstrue from 'cronstrue';
import { useNavigate } from 'react-router-dom';
import {
  useScheduledTasksForApp,
  useCreateScheduledTask,
  useUpdateScheduledTask,
  useDeleteScheduledTask,
  type PeriodicTaskResponse,
  type PeriodicTaskCreate,
  type PeriodicTaskUpdate,
  type CrontabSchedule,
  type PeriodicTaskExecuteRequest,
} from '@sep/framework';
import { useAvailableSyncers, type Syncer } from './hooks';
import { isCronExpressionValid } from './cronValidation';

// ─── Timezone helpers (mirrors ScheduledTaskForm.tsx) ───────────────────────

const TIMEZONES = (() => {
  type IntlWithTz = typeof Intl & { supportedValuesOf?: (key: string) => string[] };
  const intl = Intl as IntlWithTz;
  if (typeof intl.supportedValuesOf === 'function') {
    try {
      return intl.supportedValuesOf('timeZone');
    } catch {
      return ['UTC'];
    }
  }
  return ['UTC'];
})();

function detectBrowserTimezone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz && TIMEZONES.includes(tz) ? tz : 'UTC';
  } catch {
    return 'UTC';
  }
}

// ─── Schedule description helpers ───────────────────────────────────────────

function cronToExpression(c: CrontabSchedule): string {
  return `${c.minute} ${c.hour} ${c.day_of_month} ${c.month_of_year} ${c.day_of_week}`;
}

function expressionToCron(expr: string, timezone: string): CrontabSchedule | null {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) {
    return null;
  }
  const [minute, hour, day_of_month, month_of_year, day_of_week] = parts;
  return { minute, hour, day_of_month, month_of_year, day_of_week, timezone };
}

function humanizeCron(expr: string): { text: string; valid: boolean } {
  if (!isCronExpressionValid(expr)) {
    return { text: 'Invalid cron expression', valid: false };
  }
  try {
    const text = cronstrue.toString(expr.trim());
    return { text: text.charAt(0).toLowerCase() + text.slice(1), valid: true };
  } catch {
    return { text: 'Invalid cron expression', valid: false };
  }
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return '—';
  }
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function describePeriod(task: PeriodicTaskResponse): { display: string; tooltip?: string } {
  if (task.crontab) {
    const expr = cronToExpression(task.crontab);
    try {
      const human = cronstrue.toString(expr);
      const text = human.charAt(0).toLowerCase() + human.slice(1);
      const tz = task.crontab.timezone;
      return { display: text, tooltip: tz ? `${expr} (${tz})` : expr };
    } catch {
      return { display: expr, tooltip: 'Invalid cron expression' };
    }
  }
  if (task.interval) {
    return { display: `every ${task.interval.every} ${task.interval.period}` };
  }
  return { display: task.period || '—' };
}

function syncerLabel(task: PeriodicTaskResponse, syncers: Syncer[]): string {
  const meta = task.execute_request?.meta as Record<string, unknown> | undefined;
  const name = meta?.syncer;
  if (!name || typeof name !== 'string') {
    return 'All syncers';
  }
  return syncers.find((s) => s.name === name)?.display_name ?? name;
}

// ─── Form ───────────────────────────────────────────────────────────────────

type IntervalPeriod = 'minutes' | 'hours' | 'days';

interface SyncScheduleFormProps {
  mode: 'create' | 'edit';
  initialTask?: PeriodicTaskResponse;
  taskName: string;
  availableSyncers: Syncer[];
  onSubmit: (body: PeriodicTaskCreate | PeriodicTaskUpdate, taskName: string) => Promise<void>;
  onCancel: () => void;
  submitting?: boolean;
  errorMessage?: string;
}

function SyncScheduleForm({
  mode,
  initialTask,
  taskName,
  availableSyncers,
  onSubmit,
  onCancel,
  submitting = false,
  errorMessage,
}: SyncScheduleFormProps) {
  const initialMeta = initialTask?.execute_request?.meta as Record<string, unknown> | undefined;
  const initialSyncer = typeof initialMeta?.syncer === 'string' ? initialMeta.syncer : '';

  const [syncerName, setSyncerName] = useState(initialSyncer);
  const [scheduleMode, setScheduleMode] = useState<'interval' | 'crontab'>(
    initialTask?.crontab ? 'crontab' : 'interval',
  );
  const [intervalEvery, setIntervalEvery] = useState(String(initialTask?.interval?.every ?? 5));
  const [intervalPeriod, setIntervalPeriod] = useState<IntervalPeriod>(
    (initialTask?.interval?.period as IntervalPeriod) ?? 'minutes',
  );
  const [cronExpression, setCronExpression] = useState(
    initialTask?.crontab ? cronToExpression(initialTask.crontab) : '',
  );
  const [cronTimezone, setCronTimezone] = useState(
    initialTask?.crontab?.timezone ?? detectBrowserTimezone(),
  );
  const [enabled, setEnabled] = useState(initialTask?.enabled ?? true);
  const [localError, setLocalError] = useState<string | undefined>();

  const cronPreview = useMemo(() => {
    if (scheduleMode !== 'crontab' || !cronExpression) {
      return null;
    }
    return humanizeCron(cronExpression);
  }, [scheduleMode, cronExpression]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(undefined);

    if (scheduleMode === 'interval') {
      const n = Number(intervalEvery);
      if (!Number.isFinite(n) || !Number.isInteger(n) || n < 1) {
        setLocalError('Interval must be a whole number of at least 1');
        return;
      }
    } else {
      if (!isCronExpressionValid(cronExpression)) {
        setLocalError(
          'Enter five space-separated cron fields with valid characters and non-zero step values.',
        );
        return;
      }
      const preview = humanizeCron(cronExpression);
      if (!preview.valid) {
        setLocalError('Invalid cron expression');
        return;
      }
    }

    const execute_request: PeriodicTaskExecuteRequest = {
      // codegen types meta as empty-only; runtime accepts arbitrary keys, cast to match
      meta: (syncerName ? { syncer: syncerName } : {}) as Record<string, never>,
      chain_task_names: initialTask?.execute_request?.chain_task_names ?? [],
      chain_on_failure: initialTask?.execute_request?.chain_on_failure ?? false,
    };

    const body: PeriodicTaskCreate | PeriodicTaskUpdate = {
      name: initialTask?.name ?? '',
      task: initialTask?.task ?? taskName,
      enabled,
      description: initialTask?.description ?? '',
      kwargs: '{}',
      start_time: initialTask?.start_time ?? null,
      interval:
        scheduleMode === 'interval'
          ? { every: Number(intervalEvery), period: intervalPeriod }
          : null,
      crontab: scheduleMode === 'crontab' ? expressionToCron(cronExpression, cronTimezone) : null,
      execute_request,
    };

    await onSubmit(body, initialTask?.task ?? taskName);
  };

  const displayError = errorMessage ?? localError;

  return (
    <Box
      component="form"
      onSubmit={handleSubmit}
      data-testid="inv-sched-form"
      sx={{ p: 2, bgcolor: 'action.hover' }}
    >
      {displayError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {displayError}
        </Alert>
      )}

      {mode === 'create' && (
        <FormControl sx={{ mb: 2 }}>
          <FormLabel>Syncer</FormLabel>
          <RadioGroup
            row
            value={syncerName}
            onChange={(e) => setSyncerName(e.target.value)}
            data-testid="inv-sched-syncer-group"
          >
            <FormControlLabel value="" control={<Radio size="small" />} label="All syncers" />
            {availableSyncers.map((s) => (
              <FormControlLabel
                key={s.name}
                value={s.name}
                control={<Radio size="small" />}
                label={s.display_name}
              />
            ))}
          </RadioGroup>
        </FormControl>
      )}

      <FormControl sx={{ mb: 2 }}>
        <FormLabel>Schedule mode</FormLabel>
        <RadioGroup
          row
          value={scheduleMode}
          onChange={(e) => setScheduleMode(e.target.value as 'interval' | 'crontab')}
          data-testid="inv-sched-mode-group"
        >
          <FormControlLabel value="interval" control={<Radio size="small" />} label="Interval" />
          <FormControlLabel value="crontab" control={<Radio size="small" />} label="Crontab" />
        </RadioGroup>
      </FormControl>

      {scheduleMode === 'interval' ? (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
          <TextField
            type="number"
            size="small"
            label="Every"
            required
            value={intervalEvery}
            onChange={(e) => setIntervalEvery(e.target.value)}
            slotProps={{
              htmlInput: { min: 1, step: 1, 'data-testid': 'inv-sched-interval-every' },
            }}
            sx={{ width: 100 }}
          />
          <TextField
            select
            size="small"
            label="Period"
            value={intervalPeriod}
            onChange={(e) => setIntervalPeriod(e.target.value as IntervalPeriod)}
            sx={{ width: 120 }}
          >
            <MenuItem value="minutes">minutes</MenuItem>
            <MenuItem value="hours">hours</MenuItem>
            <MenuItem value="days">days</MenuItem>
          </TextField>
        </Stack>
      ) : (
        <Stack spacing={0.5} sx={{ mb: 2, maxWidth: 560 }}>
          <Stack direction="row" spacing={1}>
            <TextField
              size="small"
              label="Cron expression"
              placeholder="0 0 * * *"
              required
              value={cronExpression}
              onChange={(e) => setCronExpression(e.target.value)}
              slotProps={{ htmlInput: { 'data-testid': 'inv-sched-cron' } }}
              sx={{ flex: 1 }}
            />
            <Autocomplete
              size="small"
              options={TIMEZONES}
              value={cronTimezone}
              onChange={(_, v) => setCronTimezone(v ?? 'UTC')}
              sx={{ width: 220 }}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Timezone"
                  slotProps={{
                    htmlInput: {
                      ...params.inputProps,
                      'data-testid': 'inv-sched-timezone',
                    },
                  }}
                />
              )}
            />
          </Stack>
          {cronPreview && (
            <Typography
              variant="caption"
              color={cronPreview.valid ? 'text.secondary' : 'error'}
              data-testid="inv-sched-cron-preview"
            >
              {cronPreview.text}
            </Typography>
          )}
        </Stack>
      )}

      <FormControlLabel
        sx={{ mb: 2, display: 'block' }}
        control={
          <Switch
            checked={enabled}
            onChange={(_, c) => setEnabled(c)}
            inputProps={
              { 'data-testid': 'inv-sched-enabled' } as React.InputHTMLAttributes<HTMLInputElement>
            }
          />
        }
        label="Enabled"
      />

      <Stack direction="row" spacing={1} justifyContent="flex-end">
        <Button onClick={onCancel} disabled={submitting} type="button">
          Cancel
        </Button>
        <Button type="submit" variant="contained" disabled={submitting}>
          {mode === 'create' ? 'Attach schedule' : 'Save'}
        </Button>
      </Stack>
    </Box>
  );
}

// ─── Row ────────────────────────────────────────────────────────────────────

const ROW_COLUMNS = 7;

interface ScheduleRowProps {
  task: PeriodicTaskResponse;
  availableSyncers: Syncer[];
  taskName: string;
  isEditing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onToggleEnabled: (task: PeriodicTaskResponse, nextEnabled: boolean) => void;
  onSubmitEdit: (body: PeriodicTaskCreate | PeriodicTaskUpdate) => Promise<void>;
  onDelete: (task: PeriodicTaskResponse) => void;
  submitting?: boolean;
  toggling?: boolean;
  errorMessage?: string;
}

function InventoryScheduleRow({
  task,
  availableSyncers,
  taskName,
  isEditing,
  onStartEdit,
  onCancelEdit,
  onToggleEnabled,
  onSubmitEdit,
  onDelete,
  submitting,
  toggling,
  errorMessage,
}: ScheduleRowProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const label = syncerLabel(task, availableSyncers);
  const period = describePeriod(task);

  if (isEditing) {
    return (
      <TableRow>
        <TableCell colSpan={ROW_COLUMNS} sx={{ p: 0 }}>
          <SyncScheduleForm
            mode="edit"
            initialTask={task}
            taskName={taskName}
            availableSyncers={availableSyncers}
            onCancel={onCancelEdit}
            onSubmit={async (body) => onSubmitEdit(body)}
            submitting={submitting}
            errorMessage={errorMessage}
          />
        </TableCell>
      </TableRow>
    );
  }

  return (
    <>
      <TableRow data-testid={`inv-sched-row-${task.id}`}>
        <TableCell>{label}</TableCell>
        <TableCell>
          {period.tooltip ? (
            <Tooltip title={period.tooltip}>
              <span>{period.display}</span>
            </Tooltip>
          ) : (
            period.display
          )}
        </TableCell>
        <TableCell>{formatDateTime(task.last_run_at)}</TableCell>
        <TableCell>{formatDateTime(task.next_run_at ?? null)}</TableCell>
        <TableCell>{task.total_run_count}</TableCell>
        <TableCell>
          <Switch
            checked={task.enabled}
            disabled={toggling}
            onChange={(_, checked) => onToggleEnabled(task, checked)}
            slotProps={{ input: { 'aria-label': `Enable schedule for ${label}` } }}
          />
        </TableCell>
        <TableCell>
          <Stack direction="row" spacing={0.5}>
            <Tooltip title="Edit schedule">
              <IconButton
                size="small"
                onClick={onStartEdit}
                aria-label={`Edit schedule for ${label}`}
                data-testid={`inv-sched-edit-${task.id}`}
              >
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Clear schedule">
              <IconButton
                size="small"
                onClick={() => setConfirmOpen(true)}
                aria-label={`Clear schedule for ${label}`}
                data-testid={`inv-sched-delete-${task.id}`}
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
        aria-labelledby={`inv-sched-delete-title-${task.id}`}
      >
        <DialogTitle id={`inv-sched-delete-title-${task.id}`}>Clear schedule</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {`Clear the inventory-sync schedule for "${label}"? The inventory-sync task itself is not deleted.`}
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
            data-testid={`inv-sched-confirm-delete-${task.id}`}
          >
            Clear
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

interface InventorySchedulePageProps {
  schedulingEnabled: boolean;
}

export function InventorySchedulePage({ schedulingEnabled }: InventorySchedulePageProps) {
  const navigate = useNavigate();
  const { periodicTasks, appTasks, isLoading, isError, error } =
    useScheduledTasksForApp('inventory');
  const syncersQuery = useAvailableSyncers();
  const availableSyncers = syncersQuery.data ?? [];

  const taskName = appTasks[0]?.name ?? '';

  const createMut = useCreateScheduledTask();
  const updateMut = useUpdateScheduledTask();
  const deleteMut = useDeleteScheduledTask();

  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | undefined>();
  const [actionError, setActionError] = useState<string | undefined>();

  const handleToggleEnabled = async (task: PeriodicTaskResponse, nextEnabled: boolean) => {
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
    setActionError(undefined);
    try {
      await updateMut.mutateAsync({ id: task.id, body });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Failed to toggle schedule');
    }
  };

  const handleDelete = async (task: PeriodicTaskResponse) => {
    setActionError(undefined);
    try {
      await deleteMut.mutateAsync(task.id);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Failed to clear schedule');
    }
  };

  const handleCreate = async (body: PeriodicTaskCreate | PeriodicTaskUpdate, name: string) => {
    setFormError(undefined);
    try {
      await createMut.mutateAsync({ taskName: name, body: body as PeriodicTaskCreate });
      setCreating(false);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Failed to attach schedule');
    }
  };

  const handleEditSubmit =
    (task: PeriodicTaskResponse) => async (body: PeriodicTaskCreate | PeriodicTaskUpdate) => {
      setFormError(undefined);
      try {
        await updateMut.mutateAsync({ id: task.id, body: body as PeriodicTaskUpdate });
        setEditingId(null);
      } catch (e) {
        setFormError(e instanceof Error ? e.message : 'Failed to update schedule');
      }
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

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (isError) {
    return (
      <Alert severity="error">Failed to load schedules{error ? `: ${error.message}` : ''}</Alert>
    );
  }

  const isEmpty = periodicTasks.length === 0 && !creating;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
        <IconButton onClick={() => navigate('..')} aria-label="Back to list">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">Inventory Sync Schedules</Typography>
      </Box>

      {!schedulingEnabled && (
        <Alert severity="warning" sx={{ mb: 2 }} data-testid="inv-sched-unavailable">
          Scheduled inventory sync is currently unavailable. Set <code>SEP_INTERNAL_TOKEN</code> in
          the settings to enable.
        </Alert>
      )}

      <Paper variant="outlined" data-testid="inv-sched-panel">
        <Box sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <ScheduleIcon fontSize="small" />
          <Typography variant="h6">Sync Schedules</Typography>
        </Box>

        {actionError && (
          <Alert
            severity="error"
            onClose={() => setActionError(undefined)}
            sx={{ mx: 2, mb: 1 }}
            data-testid="inv-sched-action-error"
          >
            {actionError}
          </Alert>
        )}

        {isEmpty ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              No inventory-sync schedules configured.
            </Typography>
          </Box>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Syncer</TableCell>
                  <TableCell>Period</TableCell>
                  <TableCell>Last Run</TableCell>
                  <TableCell>Next Run</TableCell>
                  <TableCell>Runs</TableCell>
                  <TableCell>Enabled</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {periodicTasks.map((task) => (
                  <InventoryScheduleRow
                    key={task.id}
                    task={task}
                    availableSyncers={availableSyncers}
                    taskName={taskName}
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
            <SyncScheduleForm
              mode="create"
              taskName={taskName}
              availableSyncers={availableSyncers}
              onCancel={() => setCreating(false)}
              onSubmit={handleCreate}
              submitting={createMut.isPending}
              errorMessage={formError}
            />
          </Box>
        )}

        {schedulingEnabled && !creating && (
          <Stack
            direction="row"
            justifyContent="flex-end"
            sx={{ p: 1, borderTop: 1, borderColor: 'divider' }}
          >
            <Button
              startIcon={<AddIcon />}
              onClick={startCreate}
              disabled={!taskName}
              data-testid="inv-sched-attach"
            >
              Attach schedule
            </Button>
          </Stack>
        )}
      </Paper>
    </Box>
  );
}
