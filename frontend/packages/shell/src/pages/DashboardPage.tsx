import { useState } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Grid from '@mui/material/Grid';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import {
  OverviewCard,
  Table,
  SuccessIcon,
  ErrorIcon,
  PendingIcon,
  WarningIcon,
  LoadableChildren,
  DatabaseIcon,
} from '@percona/percona-ui';
import type { MRT_ColumnDef } from 'material-react-table';
import DnsIcon from '@mui/icons-material/Dns';
import AssignmentIcon from '@mui/icons-material/Assignment';
import CodeIcon from '@mui/icons-material/Code';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/auth';

// -- Mock data (will be replaced with React Query hooks against real API) --

interface StatCard {
  title: string;
  value: number;
  icon: React.ElementType;
  color: string;
  to: string;
}

const stats: StatCard[] = [
  { title: 'Nodes', value: 42, icon: DnsIcon, color: 'primary.main', to: '/inventory' },
  { title: 'Active Tasks', value: 7, icon: AssignmentIcon, color: 'warning.main', to: '/tasks' },
  { title: 'Snippets', value: 23, icon: CodeIcon, color: 'info.main', to: '/snippets' },
  {
    title: 'Alerts',
    value: 3,
    icon: NotificationsActiveIcon,
    color: 'error.main',
    to: '/alerts/templates',
  },
];

interface RecentTask {
  id: number;
  name: string;
  target: string;
  status: 'running' | 'completed' | 'failed' | 'pending';
  started: string;
}

const recentTasks: RecentTask[] = [
  {
    id: 1,
    name: 'pt-online-schema-change',
    target: 'prod-db-01',
    status: 'running',
    started: '2 min ago',
  },
  { id: 2, name: 'xtrabackup', target: 'prod-db-03', status: 'completed', started: '15 min ago' },
  {
    id: 3,
    name: 'pt-table-checksum',
    target: 'staging-db-01',
    status: 'completed',
    started: '1 hour ago',
  },
  { id: 4, name: 'archive-tables', target: 'prod-db-02', status: 'failed', started: '3 hours ago' },
];

const StatusIconMap = {
  running: PendingIcon,
  completed: SuccessIcon,
  failed: ErrorIcon,
  pending: WarningIcon,
} as const;

const statusColorMap: Record<string, 'info' | 'success' | 'error' | 'warning'> = {
  running: 'info',
  completed: 'success',
  failed: 'error',
  pending: 'warning',
};

const columns: MRT_ColumnDef<RecentTask>[] = [
  {
    accessorKey: 'name',
    header: 'Task',
    Cell: ({ cell }) => (
      <Typography variant="body2" fontFamily="'Roboto Mono', monospace">
        {cell.getValue<string>()}
      </Typography>
    ),
  },
  {
    accessorKey: 'target',
    header: 'Target',
    Cell: ({ cell }) => <Chip label={cell.getValue<string>()} size="small" variant="outlined" />,
  },
  {
    accessorKey: 'status',
    header: 'Status',
    Cell: ({ cell }) => {
      const status = cell.getValue<RecentTask['status']>();
      const StatusIcon = StatusIconMap[status];
      return (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <StatusIcon size="small" />
          <Chip label={status} size="small" color={statusColorMap[status]} />
        </Box>
      );
    },
  },
  {
    accessorKey: 'started',
    header: 'Started',
  },
];

export default function DashboardPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [loading] = useState(false); // will be driven by React Query

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

      {/* Stats Cards — using percona-ui's OverviewCard */}
      <LoadableChildren loading={loading}>
        <Grid container spacing={3} sx={{ mb: 3 }}>
          {stats.map((stat) => (
            <Grid key={stat.title} size={{ xs: 12, sm: 6, lg: 3 }}>
              <OverviewCard
                dataTestId={`stat-${stat.title.toLowerCase().replace(/\s+/g, '-')}`}
                cardHeaderProps={{
                  title: stat.title,
                  avatar: <DatabaseIcon sx={{ color: stat.color }} />,
                }}
                sx={{ cursor: 'pointer', '&:hover': { boxShadow: 4 } }}
                onClick={() => navigate(stat.to)}
              >
                <Typography variant="h3" fontWeight={700}>
                  {stat.value}
                </Typography>
              </OverviewCard>
            </Grid>
          ))}
        </Grid>
      </LoadableChildren>

      {/* Recent Tasks — using percona-ui's Table (material-react-table wrapper) */}
      <Box>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">Recent Tasks</Typography>
          <Button size="small" onClick={() => navigate('/tasks')}>
            View All
          </Button>
        </Box>
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
      </Box>
    </>
  );
}
