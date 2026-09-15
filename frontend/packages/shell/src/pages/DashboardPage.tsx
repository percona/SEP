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

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Grid from '@mui/material/Grid';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import { OverviewCard, Table, LoadableChildren, DatabaseIcon } from '@percona/percona-ui';
import type { MRT_ColumnDef } from 'material-react-table';
import { useNavigate } from 'react-router';
import { formatDistanceToNow } from 'date-fns';
import { useDashboardStats } from '@sep/api';
import {
  useTaskHistory,
  TaskHistoryStatusBadge,
  type TaskHistoryEntry,
  type TaskHistoryStatus,
} from '@sep/framework';
import { useAuth } from '../contexts/auth';

interface RecentTask {
  id: number;
  name: string;
  link: string;
  target: string;
  status: TaskHistoryStatus;
  started: string;
}

const OWNER_ROUTE_MAP: Record<string, (taskName: string) => string> = {
  ALTERS: (n) => `/schema-change/alters/task/${encodeURIComponent(n)}`,
  ARCHIVER: (n) => `/apps/archives/task/${encodeURIComponent(n)}`,
  BACKUPS: (n) => `/apps/mysql_backups/task/${encodeURIComponent(n)}`,
  RESTORES: (n) => `/tasks/${encodeURIComponent(n)}`,
  CHECKSUMS: (n) => `/apps/checksums/task/${encodeURIComponent(n)}`,
  BACKUP_MONGO: (n) => `/backups/mongodb/backups/task/${encodeURIComponent(n)}`,
  RESTORE_MONGO: (n) => `/backups/mongodb/restores/task/${encodeURIComponent(n)}`,
  BACKUP_PG: (n) => `/backups/postgresql/task/${encodeURIComponent(n)}`,
  ANY: (n) => `/tasks/${encodeURIComponent(n)}`,
};

function TaskNameCell({ link, name }: { link: string; name: string }) {
  const navigate = useNavigate();
  return (
    <Button
      size="small"
      sx={{ fontFamily: "'Roboto Mono', monospace", textTransform: 'none', p: 0 }}
      onClick={() => navigate(link)}
      data-task-link={link}
    >
      {name}
    </Button>
  );
}

const columns: MRT_ColumnDef<RecentTask>[] = [
  {
    accessorKey: 'name',
    header: 'Task',
    Cell: ({ row }) => <TaskNameCell link={row.original.link} name={row.original.name} />,
  },
  {
    accessorKey: 'target',
    header: 'Target',
    Cell: ({ cell }) => <Chip label={cell.getValue<string>()} size="small" variant="outlined" />,
  },
  {
    accessorKey: 'status',
    header: 'Status',
    Cell: ({ cell }) => <TaskHistoryStatusBadge status={cell.getValue<TaskHistoryStatus>()} />,
  },
  {
    accessorKey: 'started',
    header: 'Started',
  },
];

function mapHistoryToRecentTask(item: TaskHistoryEntry): RecentTask {
  const taskName = item.task.name;
  const owner = item.task.owner as string;
  const builder = OWNER_ROUTE_MAP[owner] ?? OWNER_ROUTE_MAP['ANY'];
  return {
    id: item.id ?? 0,
    name: item.display_name,
    link: builder(taskName),
    target: item.execution_request.target,
    status: item.status ?? 'pending',
    started: item.started_at
      ? formatDistanceToNow(new Date(item.started_at), { addSuffix: true })
      : '—',
  };
}

export default function DashboardPage() {
  const auth = useAuth();
  const navigate = useNavigate();

  const statsQuery = useDashboardStats();
  const historyQuery = useTaskHistory({ limit: 5, excludeInternal: true });

  // Nodes and Targets carry no `to`: SEP ships no inventory browser page for
  // them to open, so they render as plain counts.
  const stats: {
    title: string;
    value: number;
    color: string;
    to?: string;
  }[] = [
    {
      title: 'Nodes',
      value: statsQuery.data?.nodes ?? 0,
      color: 'primary.main',
    },
    {
      title: 'Active Tasks',
      value: statsQuery.data?.tasks ?? 0,
      color: 'warning.main',
      to: '/tasks',
    },
    {
      title: 'Snippets',
      value: statsQuery.data?.snippets ?? 0,
      color: 'info.main',
      to: '/snippets',
    },
    {
      title: 'Targets',
      value: statsQuery.data?.targets ?? 0,
      color: 'error.main',
    },
  ];

  const recentTasks = (historyQuery.data?.items ?? []).map(mapHistoryToRecentTask);

  return (
    <>
      <Typography
        variant="h5"
        sx={{ fontFamily: '"Poppins", sans-serif', fontWeight: 500, mb: 0.5 }}
      >
        Dashboard
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Welcome back, {auth.user?.username}
      </Typography>

      {statsQuery.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load dashboard stats: {statsQuery.error?.message}
        </Alert>
      )}
      {statsQuery.data?.degraded && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Some counts may be unavailable: {statsQuery.data.degraded.join(', ')}
        </Alert>
      )}

      {/* Stats Cards — using percona-ui's OverviewCard */}
      <LoadableChildren loading={statsQuery.isLoading}>
        <Grid container spacing={3} sx={{ mb: 3, alignItems: 'stretch' }}>
          {stats.map(({ title, value, color, to }) => (
            <Grid
              key={title}
              size={{ xs: 12, sm: 6, lg: 3 }}
              sx={{
                minWidth: 0,
                display: 'flex',
              }}
            >
              <OverviewCard
                dataTestId={`stat-${title.toLowerCase().replace(/\s+/g, '-')}`}
                cardHeaderProps={{
                  title,
                  avatar: <DatabaseIcon sx={{ color }} />,
                }}
                sx={{
                  cursor: to ? 'pointer' : 'default',
                  width: '100%',
                  height: '100%',
                  flexGrow: 1,
                  minWidth: 0,
                  ...(to ? { '&:hover': { boxShadow: 4 } } : {}),
                }}
                onClick={to ? () => navigate(to) : undefined}
              >
                <Typography variant="h3" sx={{ fontWeight: 700 }}>
                  {value}
                </Typography>
              </OverviewCard>
            </Grid>
          ))}
        </Grid>
      </LoadableChildren>

      {historyQuery.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load recent tasks: {historyQuery.error?.message}
        </Alert>
      )}

      {/* Recent Tasks — using percona-ui's Table (material-react-table wrapper) */}
      <Box>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">Recent Tasks</Typography>
          <Button size="small" onClick={() => navigate('/tasks')}>
            View All
          </Button>
        </Box>
        <LoadableChildren loading={historyQuery.isLoading}>
          <Table<RecentTask>
            columns={columns}
            data={recentTasks}
            tableName="dashboard-recent-tasks"
            noDataMessage="No recent tasks"
            enableTopToolbar={false}
            enableColumnActions={false}
            enableSorting={false}
            enablePagination={false}
            enableBottomToolbar={false}
          />
        </LoadableChildren>
      </Box>
    </>
  );
}
