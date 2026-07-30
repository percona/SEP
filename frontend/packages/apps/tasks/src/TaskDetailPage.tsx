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

import { useState, type ReactNode } from 'react';
import CloseIcon from '@mui/icons-material/Close';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Link as MuiLink,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { useNavigate, useParams } from 'react-router';
import {
  ChainDisplay,
  RUNNING_STATUSES,
  SEP_TABLE_CLASS,
  TaskHistoryTable,
  TaskLogViewer,
  useStopTaskHistory,
  type TaskHistoryEntry,
} from '@sep/framework';
import { useTaskDetail } from './hooks';
import { TaskSpecificationSection } from './TaskSpecificationSection';
import type { PeriodicTaskSummaryRow } from './types';

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function DetailField({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', sm: '160px 1fr' },
        gap: 1,
        py: 0.75,
      }}
    >
      <Typography variant="body2" color="text.secondary" component="dt">
        {label}
      </Typography>
      <Typography variant="body2" component="dd" sx={{ m: 0 }}>
        {value ?? '—'}
      </Typography>
    </Box>
  );
}

function PeriodicSummaryTable({ rows }: { rows: PeriodicTaskSummaryRow[] }) {
  // TODO(sep-frontend): Fold this read-only periodic schedule view into the framework
  // when another app needs the same surface.
  if (rows.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No periodic schedules for this task.
      </Typography>
    );
  }

  return (
    <TableContainer component={Paper} variant="outlined" className={SEP_TABLE_CLASS}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Name</TableCell>
            <TableCell>Period</TableCell>
            <TableCell>Next run</TableCell>
            <TableCell>Last run</TableCell>
            <TableCell>Runs</TableCell>
            <TableCell>Chain</TableCell>
            <TableCell>Enabled</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell>{row.name}</TableCell>
              <TableCell>{row.period ?? '—'}</TableCell>
              <TableCell>{formatTimestamp(row.next_run_at)}</TableCell>
              <TableCell>{formatTimestamp(row.last_run_at)}</TableCell>
              <TableCell>{row.total_run_count ?? '—'}</TableCell>
              <TableCell>
                <ChainDisplay chainNames={row.chain_task_names} />
              </TableCell>
              <TableCell>
                <Chip
                  label={row.enabled ? 'Yes' : 'No'}
                  size="small"
                  color={row.enabled ? 'success' : 'default'}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

export function TaskDetailPage() {
  const navigate = useNavigate();
  const { taskName: rawTaskName } = useParams<{ taskName: string }>();
  const taskName = rawTaskName;
  const { data, isLoading, error } = useTaskDetail(taskName);
  const stop = useStopTaskHistory();
  const [logsEntry, setLogsEntry] = useState<TaskHistoryEntry | null>(null);

  const handleStopTask = (entry: TaskHistoryEntry) => {
    if (entry.id !== null && entry.id !== undefined) {
      stop.mutate(entry.id);
    }
  };

  const task = data?.task;
  const isTemplate = task?.is_template ?? false;
  const historyItems = data?.execution_history.items ?? [];
  const runningTasks = historyItems.filter((item) => RUNNING_STATUSES.has(item.status));
  const periodicSummary = data?.periodic_summary ?? [];

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error || !task || !taskName) {
    return (
      <Alert severity="error">
        {error instanceof Error ? error.message : `Failed to load task "${taskName ?? 'unknown'}".`}
      </Alert>
    );
  }

  const displayName = task.name || taskName;

  return (
    <Box>
      <MuiLink
        component="button"
        type="button"
        onClick={() => navigate('..')}
        sx={{ mb: 2, display: 'inline-block' }}
      >
        ← Back to Task Manager
      </MuiLink>

      <Typography variant="h4" component="h1" sx={{ mb: 3 }}>
        {displayName}
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Task information
        </Typography>
        <Box component="dl" sx={{ m: 0 }}>
          <DetailField label="Engine" value={task.backend || '—'} />
          <DetailField label="Created" value={formatTimestamp(task.created_at)} />
          {task.created_by ? <DetailField label="Created by" value={task.created_by} /> : null}
          {task.last_updated_by ? (
            <DetailField label="Last modified by" value={task.last_updated_by} />
          ) : null}
          <DetailField label="Owner" value={task.owner || '—'} />
          {task.is_template ? <DetailField label="Template" value="Yes" /> : null}
        </Box>
      </Paper>

      <TaskSpecificationSection task={task} />

      {!isTemplate ? (
        <>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Running
          </Typography>
          <Box sx={{ mb: 3 }}>
            <TaskHistoryTable
              data={runningTasks}
              hideTaskNameColumn
              disablePolling
              onViewLogs={setLogsEntry}
              onStopTask={handleStopTask}
              isStopping={stop.isPending}
            />
          </Box>

          <Divider sx={{ my: 3 }} />

          <Typography variant="h6" sx={{ mb: 1 }}>
            Periodic schedules
          </Typography>
          <Box sx={{ mb: 3 }}>
            <PeriodicSummaryTable rows={periodicSummary} />
          </Box>

          <Divider sx={{ my: 3 }} />

          <Typography variant="h6" sx={{ mb: 1 }}>
            History
          </Typography>
          <TaskHistoryTable
            data={historyItems}
            hideTaskNameColumn
            disablePolling
            onViewLogs={setLogsEntry}
            onStopTask={handleStopTask}
            isStopping={stop.isPending}
            onChainItemClick={(chainTaskName) => {
              navigate(`../${encodeURIComponent(chainTaskName)}`);
            }}
          />
        </>
      ) : null}

      <Dialog open={logsEntry !== null} onClose={() => setLogsEntry(null)} fullWidth maxWidth="lg">
        <DialogTitle
          id="task-logs-dialog-title"
          sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
        >
          <span>
            Task logs
            {logsEntry?.task?.name ? ` — ${logsEntry.task.name}` : ''}
            {logsEntry?.id !== null && logsEntry?.id !== undefined ? ` #${logsEntry.id}` : ''}
          </span>
          <IconButton
            aria-label="Close logs dialog"
            onClick={() => setLogsEntry(null)}
            size="small"
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers sx={{ p: 0 }}>
          {logsEntry?.id !== null && logsEntry?.id !== undefined ? (
            <TaskLogViewer
              taskHistoryId={logsEntry.id}
              taskStatus={logsEntry.status}
              height={520}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </Box>
  );
}
