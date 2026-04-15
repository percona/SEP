import { useMemo } from 'react';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import { MaterialReactTable, type MRT_ColumnDef } from 'material-react-table';
import type { ListColumn, ListView } from '@sep/api';

interface SchemaListViewProps {
  listView: ListView;
  data: Record<string, unknown>[];
  isLoading?: boolean;
  onRowClick?: (row: Record<string, unknown>) => void;
}

function formatCellValue(value: unknown, format: ListColumn['format']): React.ReactNode {
  if (value === null) {
    return '—';
  }
  const str = String(value);

  switch (format) {
    case 'chip':
      return <Chip label={str} size="small" />;
    case 'status':
      return (
        <Chip
          label={str}
          size="small"
          color={
            str === 'completed' || str === 'success'
              ? 'success'
              : str === 'failed' || str === 'error'
                ? 'error'
                : str === 'running' || str === 'in_progress'
                  ? 'info'
                  : 'default'
          }
        />
      );
    case 'date':
      return new Date(str).toLocaleDateString();
    case 'relative': {
      const diff = Date.now() - new Date(str).getTime();
      const mins = Math.floor(diff / 60000);
      if (mins < 1) {
        return 'just now';
      }
      if (mins < 60) {
        return `${mins}m ago`;
      }
      const hours = Math.floor(mins / 60);
      if (hours < 24) {
        return `${hours}h ago`;
      }
      const days = Math.floor(hours / 24);
      return `${days}d ago`;
    }
    case 'code':
      return (
        <Typography variant="body2" sx={{ fontFamily: "'Roboto Mono', monospace" }}>
          {str}
        </Typography>
      );
    default:
      return str;
  }
}

export function SchemaListView({
  listView,
  data,
  isLoading = false,
  onRowClick,
}: SchemaListViewProps) {
  const columns = useMemo<MRT_ColumnDef<Record<string, unknown>>[]>(
    () =>
      listView.columns.map((col) => ({
        accessorKey: col.key,
        header: col.label,
        enableSorting: col.sortable ?? true,
        Cell: ({ cell }) => formatCellValue(cell.getValue(), col.format),
      })),
    [listView.columns],
  );

  return (
    <MaterialReactTable
      columns={columns}
      data={data}
      state={{ isLoading }}
      enableColumnActions={false}
      enableDensityToggle={false}
      enableFullScreenToggle={false}
      initialState={{
        sorting: listView.defaultSort ? [{ id: listView.defaultSort, desc: true }] : [],
        density: 'compact',
      }}
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
