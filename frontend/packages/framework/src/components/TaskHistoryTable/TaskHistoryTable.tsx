import { useMemo } from 'react';
import Chip from '@mui/material/Chip';
import { MaterialReactTable, type MRT_ColumnDef } from 'material-react-table';

interface TaskHistoryEntry {
  id: string;
  status: string;
  startedAt: string;
  completedAt?: string;
  duration?: string;
  triggeredBy?: string;
}

interface TaskHistoryTableProps {
  tasks?: TaskHistoryEntry[];
  isLoading?: boolean;
  onRowClick?: (task: TaskHistoryEntry) => void;
}

// TODO: connect to real API for task execution history
export function TaskHistoryTable({
  tasks = [],
  isLoading = false,
  onRowClick,
}: TaskHistoryTableProps) {
  const columns = useMemo<MRT_ColumnDef<TaskHistoryEntry>[]>(
    () => [
      { accessorKey: 'id', header: 'Run ID', size: 100 },
      {
        accessorKey: 'status',
        header: 'Status',
        size: 120,
        Cell: ({ cell }) => {
          const status = cell.getValue<string>();
          return (
            <Chip
              label={status}
              size="small"
              color={
                status === 'completed'
                  ? 'success'
                  : status === 'failed'
                    ? 'error'
                    : status === 'running'
                      ? 'info'
                      : 'default'
              }
            />
          );
        },
      },
      { accessorKey: 'startedAt', header: 'Started', size: 180 },
      { accessorKey: 'completedAt', header: 'Completed', size: 180 },
      { accessorKey: 'duration', header: 'Duration', size: 100 },
      { accessorKey: 'triggeredBy', header: 'Triggered By', size: 140 },
    ],
    [],
  );

  return (
    <MaterialReactTable
      columns={columns}
      data={tasks}
      state={{ isLoading }}
      enableColumnActions={false}
      enableDensityToggle={false}
      enableFullScreenToggle={false}
      initialState={{ density: 'compact' }}
      muiTableBodyRowProps={
        onRowClick
          ? ({ row }) => ({
              onClick: () => onRowClick(row.original),
              sx: { cursor: 'pointer' },
            })
          : undefined
      }
    />
  );
}
