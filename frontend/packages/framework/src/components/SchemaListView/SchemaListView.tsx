import { useMemo, type ReactNode } from 'react';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { MaterialReactTable, type MRT_ColumnDef } from 'material-react-table';
import type { ListColumn, ListView } from '@sep/api';

interface SchemaListViewProps {
  listView: ListView;
  data: Record<string, unknown>[];
  isLoading?: boolean;
  onRowClick?: (row: Record<string, unknown>) => void;
  /** When set, ``format: 'actions'`` columns render a delete control for that row. */
  onDeleteRow?: (row: Record<string, unknown>) => void;
  /** Row id currently being deleted (disables that row's button). */
  deletingRowId?: string | null;
}

function formatCellValue(value: unknown, format: ListColumn['format']): ReactNode {
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
  onDeleteRow,
  deletingRowId,
}: SchemaListViewProps) {
  const columns = useMemo<MRT_ColumnDef<Record<string, unknown>>[]>(
    () =>
      listView.columns.map((col) => {
        if (col.format === 'actions') {
          return {
            id: col.key,
            accessorKey: col.key,
            header: col.label,
            enableSorting: false,
            size: 72,
            Cell: ({ row }) => {
              const id = row.original.id;
              if (id === undefined || id === null || !onDeleteRow) {
                return null;
              }
              const sid = String(id);
              return (
                <IconButton
                  size="small"
                  color="error"
                  aria-label="Delete"
                  disabled={deletingRowId === sid}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteRow(row.original);
                  }}
                >
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              );
            },
          };
        }
        return {
          accessorKey: col.key,
          header: col.label,
          enableSorting: col.sortable ?? true,
          Cell: ({ cell }) => formatCellValue(cell.getValue(), col.format),
        };
      }),
    [deletingRowId, listView.columns, onDeleteRow],
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
        sorting: listView.defaultSort
          ? [
              {
                id: listView.defaultSort.replace(/^-/, ''),
                desc: listView.defaultSort.startsWith('-'),
              },
            ]
          : [],
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
