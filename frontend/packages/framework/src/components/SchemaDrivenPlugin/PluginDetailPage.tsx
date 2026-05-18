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

import { lazy, Suspense, useMemo, useState, type ReactNode } from 'react';
import { Routes, Route, useParams, useNavigate, useLocation, Link } from 'react-router-dom';
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
import {
  useDeletePluginEntity,
  useDeletePluginTask,
  usePluginEntityDetail,
  usePluginTask,
  type PluginEntitySchema,
  type PluginSchema,
} from '@sep/api';
import { TaskHistoryTable, type TaskHistoryEntry } from '../TaskHistoryTable';
import { TaskLogViewer } from '../TaskLogViewer';
import { useExecuteTask, useTaskHistoryByName } from '../../hooks';
import { DeleteConfirmDialog } from './DeleteConfirmDialog';
import { detailSyntaxBlockSx, type DetailSyntaxLanguage } from './detailSyntaxStyles';

const DetailSyntaxHighlighter = lazy(() => import('./DetailSyntaxHighlighter'));

export interface PluginDetailPageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
  /** Hide edit/delete (browse-only mode for multi-entity plugins). */
  browseOnly?: boolean;
  /** Omit these keys from the auto-rendered detail section (e.g. nested relations shown elsewhere). */
  suppressDetailKeys?: string[];
  /** Extra content under the main detail card (e.g. child entity tables). */
  renderEntityDetailChildren?: (args: {
    entityName: string;
    record: Record<string, unknown>;
    schema: PluginSchema;
    pathname: string;
    pluginName: string;
    mockEntityItems?: Record<string, Record<string, unknown>[]>;
    allowListEntityDelete?: boolean;
  }) => ReactNode;
  /** Nested inventory: resolve ``entityName`` / ``id`` from named params (e.g. ``nodeId``). */
  detailEntityName?: string;
  detailIdParam?: string;
  /** Optional callback that resolves a custom back/delete target from current pathname. */
  resolveParentPath?: (pathname: string) => string | null;
  /** When true, omit the header row (back button, ``{title} #{id}``, status chip, edit/delete). */
  hideDetailChrome?: boolean;
  /** When true, nested list tables may show row delete (inventory ``actions`` column). */
  allowListEntityDelete?: boolean;
}

/** Screen title when the back/status row is hidden (browse-only multi-entity plugins). */
function detailScreenHeading(
  entityName: string | undefined,
  entityDisplayName: string | undefined,
): string | null {
  if (!entityName) {
    return null;
  }
  return `${entityDisplayName ?? entityName} detail`;
}

/** List URL for the current entity tab (path segment before ``:id``), e.g. ``/inventory/services``. */
export function pathToEntityList(pathname: string, entityName: string): string {
  const parts = pathname.split('/').filter(Boolean);
  const idx = parts.lastIndexOf(entityName);
  if (idx < 0) {
    return '/';
  }
  return `/${parts.slice(0, idx + 1).join('/')}`;
}

function EntityDetailField({
  label,
  value,
  highlightLanguage,
}: {
  label: string;
  value: unknown;
  highlightLanguage?: DetailSyntaxLanguage;
}) {
  if (value === null || value === undefined || value === '') {
    return null;
  }

  const syntaxFallback = (
    <Skeleton variant="rectangular" height={120} sx={{ ...detailSyntaxBlockSx, mt: 0.5 }} />
  );

  if (highlightLanguage) {
    return (
      <Box sx={{ mb: 2 }}>
        <Typography variant="caption" color="text.secondary">
          {label}
        </Typography>
        <Suspense fallback={syntaxFallback}>
          <DetailSyntaxHighlighter value={value} language={highlightLanguage} />
        </Suspense>
      </Box>
    );
  }

  let display: React.ReactNode;
  if (typeof value === 'boolean') {
    display = value ? 'Yes' : 'No';
  } else if (typeof value === 'object') {
    display = (
      <Suspense fallback={syntaxFallback}>
        <DetailSyntaxHighlighter value={value} language="json" />
      </Suspense>
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

function TaskOverviewDetailField({ label, value }: { label: string; value: unknown }) {
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

interface OverviewTabProps {
  schema: PluginSchema;
  task: Record<string, unknown>;
}

function OverviewTab({ schema, task }: OverviewTabProps) {
  const execution = pickExecutionData(task);
  const connectivityWarning = task.connectivity_warning;
  const columns = schema.list_view!.columns;

  // Extra fields beyond the schema's list_view columns, excluding internal
  // noise. Lets future plugin schemas surface fields without listing them
  // in `list_view.columns` (which is meant for the table view).
  const extraEntries = Object.entries(task).filter(
    ([key]) => !columns.some((c) => c.key === key) && !OVERVIEW_HIDDEN_FIELDS.has(key),
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
        {columns.map((col) => (
          <TaskOverviewDetailField key={col.key} label={col.label} value={task[col.key]} />
        ))}
        {extraEntries.map(([key, value]) => (
          <TaskOverviewDetailField key={key} label={formatLabel(key)} value={value} />
        ))}
      </SectionCard>

      {execution && (
        <SectionCard title="Execution">
          {execution.command !== undefined && (
            <TaskOverviewDetailField label="Command" value={execution.command} />
          )}
          {execution.args !== undefined && (
            <TaskOverviewDetailField label="Args" value={execution.args} />
          )}
          {execution.target !== undefined && (
            <TaskOverviewDetailField label="Target" value={execution.target} />
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
  taskName: string;
}

function ActionBar({ schema, pluginName, taskName }: ActionBarProps) {
  const navigate = useNavigate();
  const { enqueueSnackbar } = useSnackbar();
  const deleteTask = useDeletePluginTask(pluginName);
  const executeTask = useExecuteTask();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [executeConfirmOpen, setExecuteConfirmOpen] = useState(false);

  const handleExecute = async () => {
    try {
      await executeTask.mutateAsync({ taskName });
      enqueueSnackbar(`${schema.display_name} task "${taskName}" started`, { variant: 'success' });
    } catch (e) {
      enqueueSnackbar(e instanceof Error ? e.message : 'Failed to execute task', {
        variant: 'error',
      });
    } finally {
      setExecuteConfirmOpen(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteTask.mutateAsync(taskName);
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

  const editBlocked = 'Edit is not yet available in the new UI';

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

        <Button
          variant="outlined"
          startIcon={<PlayArrowIcon />}
          onClick={() => setExecuteConfirmOpen(true)}
          disabled={executeTask.isPending}
          data-testid="plugin-task-execute"
        >
          Execute
        </Button>

        <Tooltip title={editBlocked}>
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

      <Dialog open={executeConfirmOpen} onClose={() => setExecuteConfirmOpen(false)}>
        <DialogTitle>Execute {schema.display_name} task?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to execute the task {taskName} now?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setExecuteConfirmOpen(false)} disabled={executeTask.isPending}>
            Cancel
          </Button>
          <Button
            onClick={handleExecute}
            variant="contained"
            disabled={executeTask.isPending}
            data-testid="plugin-task-execute-confirm"
          >
            Execute
          </Button>
        </DialogActions>
      </Dialog>

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

export function PluginDetailPage({
  schema,
  pluginName,
  mockTasks,
  mockEntityItems,
  browseOnly = false,
  suppressDetailKeys = [],
  renderEntityDetailChildren,
  detailEntityName,
  detailIdParam,
  resolveParentPath,
  hideDetailChrome = false,
  allowListEntityDelete = false,
}: PluginDetailPageProps) {
  const params = useParams<Record<string, string | undefined>>();
  const id = (detailIdParam && params[detailIdParam]) ?? params.id;
  const entityName = detailEntityName ?? params.entityName;
  const splat = params['*'];
  const navigate = useNavigate();
  const location = useLocation();
  const entitySchema = useMemo(
    () => schema.entities?.find((e: PluginEntitySchema) => e.name === entityName),
    [schema.entities, entityName],
  );
  const multi = Boolean(schema.entities?.length && entityName && entitySchema);

  const customParentPath = useMemo(() => {
    if (!resolveParentPath) {
      return null;
    }
    return resolveParentPath(location.pathname);
  }, [location.pathname, resolveParentPath]);

  const taskQuery = usePluginTask(pluginName, id, mockTasks, { enabled: !multi && Boolean(id) });
  const entityQuery = usePluginEntityDetail(
    pluginName,
    entityName ?? '',
    id,
    multi ? mockEntityItems?.[entityName!] : undefined,
    { enabled: multi && Boolean(id) },
  );

  const { data: task, isLoading } = multi ? entityQuery : taskQuery;
  const listView = multi ? entitySchema!.list_view : schema.list_view!;
  const title = multi ? entitySchema!.display_name : schema.display_name;
  const headingWhenChromeHidden = useMemo(
    () =>
      hideDetailChrome && multi
        ? detailScreenHeading(entityName, entitySchema?.display_name)
        : null,
    [hideDetailChrome, multi, entityName, entitySchema?.display_name],
  );

  const deleteEntity = useDeletePluginEntity(
    pluginName,
    entityName ?? '',
    multi ? mockEntityItems?.[entityName!] : undefined,
  );

  const [entityDeleteOpen, setEntityDeleteOpen] = useState(false);

  const confirmEntityDelete = () => {
    setEntityDeleteOpen(false);
    if (!id || !multi) {
      return;
    }
    deleteEntity.mutate(id, {
      onSuccess: () =>
        customParentPath
          ? navigate(customParentPath)
          : entityName
            ? navigate(pathToEntityList(location.pathname, entityName))
            : navigate('..', { relative: 'path' }),
    });
  };

  if (multi) {
    if (isLoading) {
      return (
        <Box>
          {headingWhenChromeHidden ? (
            <Typography component="h1" variant="h4" sx={{ mb: 2, fontWeight: 600 }}>
              {headingWhenChromeHidden}
            </Typography>
          ) : (
            <Skeleton variant="text" width={300} height={40} />
          )}
          <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
        </Box>
      );
    }

    if (!task) {
      return (
        <Box>
          {headingWhenChromeHidden ? (
            <Typography component="h1" variant="h4" sx={{ mb: 2, fontWeight: 600 }}>
              {headingWhenChromeHidden}
            </Typography>
          ) : null}
          <Typography variant="h5">Not found</Typography>
        </Box>
      );
    }

    const recordName =
      typeof task.name === 'string' && task.name.trim()
        ? task.name.trim()
        : typeof task.name === 'number'
          ? String(task.name)
          : undefined;

    return (
      <Box>
        <DeleteConfirmDialog
          open={entityDeleteOpen}
          onClose={() => setEntityDeleteOpen(false)}
          onConfirm={confirmEntityDelete}
          title={`Delete from ${schema.display_name}?`}
          description={
            recordName
              ? `Permanently delete ${title} "${recordName}" (id ${id}) from ${schema.display_name}? This cannot be undone.`
              : `Permanently delete ${title} (id ${id}) from ${schema.display_name}? This cannot be undone.`
          }
        />

        {headingWhenChromeHidden ? (
          <Typography component="h1" variant="h4" sx={{ mb: 2, fontWeight: 600 }}>
            {headingWhenChromeHidden}
          </Typography>
        ) : null}
        {!hideDetailChrome && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3, flexWrap: 'wrap' }}>
            <IconButton
              onClick={() =>
                customParentPath
                  ? navigate(customParentPath)
                  : multi && entityName
                    ? navigate(pathToEntityList(location.pathname, entityName))
                    : navigate('..', { relative: 'path' })
              }
            >
              <ArrowBackIcon />
            </IconButton>
            <Typography variant="h4">
              {title} #{id}
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
            {multi && !browseOnly && (
              <>
                <Button
                  component={Link}
                  to="edit"
                  relative="path"
                  startIcon={<EditIcon />}
                  variant="outlined"
                  size="small"
                >
                  Edit
                </Button>
                <Button
                  color="error"
                  variant="outlined"
                  size="small"
                  onClick={() => setEntityDeleteOpen(true)}
                  disabled={deleteEntity.isPending}
                >
                  Delete
                </Button>
              </>
            )}
          </Box>
        )}

        <Paper sx={{ p: 3 }}>
          {listView.columns
            .filter((col) => col.format !== 'actions' && col.key !== '_actions')
            .map((col) => (
              <EntityDetailField
                key={col.key}
                highlightLanguage={entitySchema?.detail_highlights?.[col.key]}
                label={col.label}
                value={task[col.key]}
              />
            ))}

          {Object.entries(task)
            .filter(
              ([key]) =>
                !listView.columns.some((c) => c.key === key) &&
                key !== 'id' &&
                key !== '_actions' &&
                !suppressDetailKeys.includes(key),
            )
            .map(([key, value]) => (
              <EntityDetailField
                key={key}
                highlightLanguage={entitySchema?.detail_highlights?.[key]}
                label={key}
                value={value}
              />
            ))}
        </Paper>

        {multi &&
          entityName &&
          renderEntityDetailChildren &&
          renderEntityDetailChildren({
            entityName,
            record: task as Record<string, unknown>,
            schema,
            pathname: location.pathname,
            pluginName,
            mockEntityItems,
            allowListEntityDelete,
          })}
      </Box>
    );
  }

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

      <ActionBar schema={schema} pluginName={pluginName} taskName={taskName} />

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
