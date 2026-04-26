import { useCallback, useMemo } from 'react';
import DownloadIcon from '@mui/icons-material/Download';
import StopCircleIcon from '@mui/icons-material/StopCircle';
import VisibilityIcon from '@mui/icons-material/Visibility';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { MaterialReactTable, type MRT_ColumnDef } from 'material-react-table';
import {
  isRunningStatus,
  useStopTaskHistory,
  useTaskHistory,
  useTaskHistoryByName,
} from '../../hooks/useTaskHistory';
import { ChainDisplay } from './ChainDisplay';
import { StatusBadge } from './StatusBadge';
import type { TaskHistoryEntry, TaskHistoryTableProps } from './TaskHistoryTable.types';

function formatDateTime(value?: string | null): string {
  if (!value) {
    return '—';
  }
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '—';
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${s}s`;
}

interface MetaShape {
  _chain_task_names?: string[];
  _chain_depth?: number;
}

function readMeta(entry: TaskHistoryEntry): MetaShape {
  const meta = entry.execution_request?.meta as MetaShape | null | undefined;
  return meta ?? {};
}

function hasDownloadableArtifacts(entry: TaskHistoryEntry): boolean {
  if (entry.has_logs) {
    return true;
  }
  const maybeFiles = (entry as { available_files?: unknown }).available_files;
  return !!maybeFiles && typeof maybeFiles === 'object' && Object.keys(maybeFiles).length > 0;
}

interface ViewProps {
  rows: TaskHistoryEntry[];
  isLoading: boolean;
  resolveUserName: TaskHistoryTableProps['resolveUserName'];
  onViewLogs: TaskHistoryTableProps['onViewLogs'];
  onDownloadFiles: TaskHistoryTableProps['onDownloadFiles'];
  onChainItemClick: TaskHistoryTableProps['onChainItemClick'];
  hideTaskNameColumn?: boolean;
  onStop: (entry: TaskHistoryEntry) => void;
  isStopping: boolean;
  /** True when the row's stop action will resolve to a real handler (callback or internal mutation). */
  canStop: (entry: TaskHistoryEntry) => boolean;
}

function TaskHistoryTableView({
  rows,
  isLoading,
  resolveUserName,
  onViewLogs,
  onDownloadFiles,
  onChainItemClick,
  hideTaskNameColumn,
  onStop,
  isStopping,
  canStop,
}: ViewProps) {
  const columns = useMemo<MRT_ColumnDef<TaskHistoryEntry>[]>(() => {
    const cols: MRT_ColumnDef<TaskHistoryEntry>[] = [
      {
        id: 'status',
        header: 'Status',
        size: 130,
        accessorFn: (row) => row.status,
        Cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      ...(hideTaskNameColumn
        ? []
        : [
            {
              id: 'task',
              header: 'Task',
              accessorFn: (row: TaskHistoryEntry) => row.task?.name ?? '',
              size: 180,
            } satisfies MRT_ColumnDef<TaskHistoryEntry>,
          ]),
      {
        id: 'host',
        header: 'Host',
        accessorFn: (row) => row.execution_request?.target ?? '',
        size: 160,
      },
      {
        id: 'chain',
        header: 'Chain',
        enableSorting: false,
        size: 220,
        Cell: ({ row }) => {
          const meta = readMeta(row.original);
          return (
            <ChainDisplay
              chainNames={meta._chain_task_names}
              chainDepth={meta._chain_depth}
              onChainItemClick={
                onChainItemClick
                  ? (name, index) => onChainItemClick(name, index, row.original)
                  : undefined
              }
            />
          );
        },
      },
      {
        id: 'started_at',
        header: 'Started',
        size: 180,
        accessorFn: (row) => row.started_at ?? '',
        sortingFn: 'datetime',
        Cell: ({ row }) => (
          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
            {formatDateTime(row.original.started_at)}
          </Typography>
        ),
      },
      {
        id: 'duration',
        header: 'Duration',
        size: 110,
        accessorFn: (row) => row.duration ?? -1,
        Cell: ({ row }) => (
          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
            {formatDuration(row.original.duration)}
          </Typography>
        ),
      },
      {
        id: 'executed_by',
        header: 'Executed By',
        size: 150,
        accessorFn: (row) =>
          (resolveUserName ? resolveUserName(row.executed_by) : (row.executed_by ?? '')) || '',
      },
      {
        id: 'actions',
        header: 'Actions',
        enableSorting: false,
        enableColumnFilter: false,
        size: 150,
        Cell: ({ row }) => {
          const entry = row.original;
          const running = isRunningStatus(entry.status);
          const downloadable = hasDownloadableArtifacts(entry);
          return (
            <Stack direction="row" spacing={0.5}>
              <Tooltip title="View logs">
                <span>
                  <IconButton
                    size="small"
                    aria-label="View logs"
                    disabled={!onViewLogs || (!entry.has_logs && !running)}
                    onClick={() => onViewLogs?.(entry)}
                  >
                    <VisibilityIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              {running && (
                <Tooltip title="Stop task">
                  <span>
                    <IconButton
                      size="small"
                      color="warning"
                      aria-label="Stop task"
                      onClick={() => onStop(entry)}
                      disabled={isStopping || !canStop(entry)}
                    >
                      <StopCircleIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              )}
              {!running && downloadable && (
                <Tooltip title="Download files">
                  <span>
                    <IconButton
                      size="small"
                      aria-label="Download files"
                      disabled={!onDownloadFiles}
                      onClick={() => onDownloadFiles?.(entry)}
                    >
                      <DownloadIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              )}
            </Stack>
          );
        },
      },
    ];
    return cols;
  }, [
    hideTaskNameColumn,
    onChainItemClick,
    onDownloadFiles,
    onViewLogs,
    onStop,
    isStopping,
    canStop,
    resolveUserName,
  ]);

  return (
    <MaterialReactTable
      columns={columns}
      data={rows}
      state={{ isLoading }}
      enableColumnActions={false}
      enableDensityToggle={false}
      enableFullScreenToggle={false}
      enableHiding={false}
      enablePagination
      enableSorting
      initialState={{
        density: 'compact',
        sorting: [{ id: 'started_at', desc: true }],
        pagination: { pageIndex: 0, pageSize: 10 },
      }}
      getRowId={(row) => String(row.id ?? `${row.task?.name ?? ''}-${row.started_at ?? ''}`)}
      muiTableBodyRowProps={({ row }) =>
        isRunningStatus(row.original.status)
          ? { 'data-running': 'true', sx: { backgroundColor: 'action.hover' } }
          : {}
      }
      renderEmptyRowsFallback={() => (
        <Typography variant="body2" sx={{ p: 2, textAlign: 'center' }} color="text.secondary">
          No task history
        </Typography>
      )}
    />
  );
}

interface ConnectedProps extends Omit<TaskHistoryTableProps, 'data' | 'isLoading'> {}

function ConnectedTaskHistoryTable({
  taskName,
  statusFilter,
  pollingIntervalMs,
  disablePolling,
  resolveUserName,
  onViewLogs,
  onStopTask,
  onDownloadFiles,
  onChainItemClick,
  hideTaskNameColumn,
}: ConnectedProps) {
  const allHistory = useTaskHistory({
    status: statusFilter,
    pollingIntervalMs,
    disablePolling,
    enabled: !taskName,
  });
  const byNameHistory = useTaskHistoryByName(taskName, {
    status: statusFilter,
    pollingIntervalMs,
    disablePolling,
  });
  const stopMutation = useStopTaskHistory();

  const queryResult = taskName ? byNameHistory : allHistory;
  const rows: TaskHistoryEntry[] = queryResult.data?.items ?? [];
  const isLoading = queryResult.isLoading;

  const handleStop = useCallback(
    (entry: TaskHistoryEntry) => {
      const taskLabel = entry.task?.name ?? `#${entry.id ?? ''}`;
      const confirmed =
        typeof window === 'undefined'
          ? true
          : window.confirm(`Are you sure you want to stop the task ${taskLabel}?`);
      if (!confirmed) {
        return;
      }
      if (onStopTask) {
        onStopTask(entry);
        return;
      }
      if (entry.id !== null && entry.id !== undefined) {
        stopMutation.mutate(entry.id);
      }
    },
    [onStopTask, stopMutation],
  );

  const canStop = useCallback(
    (entry: TaskHistoryEntry) => !!onStopTask || (entry.id !== null && entry.id !== undefined),
    [onStopTask],
  );

  return (
    <TaskHistoryTableView
      rows={rows}
      isLoading={isLoading}
      resolveUserName={resolveUserName}
      onViewLogs={onViewLogs}
      onDownloadFiles={onDownloadFiles}
      onChainItemClick={onChainItemClick}
      hideTaskNameColumn={hideTaskNameColumn}
      onStop={handleStop}
      isStopping={stopMutation.isPending}
      canStop={canStop}
    />
  );
}

interface PresentationalProps extends Omit<
  TaskHistoryTableProps,
  'taskName' | 'statusFilter' | 'pollingIntervalMs' | 'disablePolling'
> {
  data: TaskHistoryEntry[];
}

function PresentationalTaskHistoryTable({
  data,
  isLoading,
  resolveUserName,
  onViewLogs,
  onStopTask,
  onDownloadFiles,
  onChainItemClick,
  hideTaskNameColumn,
}: PresentationalProps) {
  const handleStop = useCallback(
    (entry: TaskHistoryEntry) => {
      const taskLabel = entry.task?.name ?? `#${entry.id ?? ''}`;
      const confirmed =
        typeof window === 'undefined'
          ? true
          : window.confirm(`Are you sure you want to stop the task ${taskLabel}?`);
      if (!confirmed) {
        return;
      }
      onStopTask?.(entry);
    },
    [onStopTask],
  );

  const canStop = useCallback(() => !!onStopTask, [onStopTask]);

  return (
    <TaskHistoryTableView
      rows={data}
      isLoading={!!isLoading}
      resolveUserName={resolveUserName}
      onViewLogs={onViewLogs}
      onDownloadFiles={onDownloadFiles}
      onChainItemClick={onChainItemClick}
      hideTaskNameColumn={hideTaskNameColumn}
      onStop={handleStop}
      isStopping={false}
      canStop={canStop}
    />
  );
}

/**
 * Render task-history rows.
 *
 * Two modes:
 * - Connected: when `data` is omitted, the component fetches via React Query
 *   (requires a `QueryClientProvider`) and polls while running rows exist.
 * - Presentational: when `data` is provided, the component renders the rows
 *   verbatim with no React Query usage — safe for stories, tests, and any
 *   consumer that already owns the data.
 */
export function TaskHistoryTable(props: TaskHistoryTableProps) {
  if (props.data !== undefined) {
    return <PresentationalTaskHistoryTable {...props} data={props.data} />;
  }
  return <ConnectedTaskHistoryTable {...props} />;
}
