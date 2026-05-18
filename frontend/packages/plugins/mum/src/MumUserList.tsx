import { useMemo, useState, useEffect } from 'react';
import {
  Box,
  Chip,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Toolbar,
  Typography,
} from '@mui/material';
import type { ReactNode } from 'react';

export type UserRow = Record<string, unknown>;

const ROWS_PER_PAGE = 10;
const EXCLUDED_COLUMNS = new Set(['_id', 'userId', 'UserId']);

const getColumns = (rows: UserRow[]): string[] => {
  const cols = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row ?? {}).forEach((key) => {
      if (!EXCLUDED_COLUMNS.has(key)) cols.add(key);
    });
  });
  return Array.from(cols);
};

interface RoleRef { role?: string; db?: string }

const RoleChips = ({ roles }: { roles: unknown }) => {
  if (!Array.isArray(roles) || roles.length === 0) return <span>—</span>;
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
      {(roles as RoleRef[]).map((r, i) => (
        <Chip
          key={i}
          label={r.db && r.db !== r.role ? `${r.role} @ ${r.db}` : r.role}
          size="small"
          variant="outlined"
        />
      ))}
    </Box>
  );
};

const MechanismChips = ({ mechanisms }: { mechanisms: unknown }) => {
  if (!Array.isArray(mechanisms) || mechanisms.length === 0) return <span>—</span>;
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
      {(mechanisms as string[]).map((m, i) => (
        <Chip key={i} label={m} size="small" />
      ))}
    </Box>
  );
};

const formatCell = (col: string, value: unknown): ReactNode => {
  if (value === null || value === undefined) return '';
  if (col === 'roles') return <RoleChips roles={value} />;
  if (col === 'mechanisms') return <MechanismChips mechanisms={value} />;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

interface MumUserListProps {
  usersData?: UserRow[];
  title?: string;
  toolbarActions?: ReactNode;
  renderRowActions?: ((row: UserRow) => ReactNode) | null;
  emptyState?: string;
}

export function MumUserList({
  usersData = [],
  title = 'Users Table',
  toolbarActions = null,
  renderRowActions = null,
  emptyState = 'No rows to display.',
}: MumUserListProps) {
  const columns = useMemo(() => getColumns(usersData), [usersData]);
  const showActions = typeof renderRowActions === 'function';
  const [page, setPage] = useState(0);

  useEffect(() => { setPage(0); }, [usersData]);

  const pageRows = usersData.slice(page * ROWS_PER_PAGE, (page + 1) * ROWS_PER_PAGE);

  return (
    <Paper elevation={1}>
      <Toolbar>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {usersData.length ? `${usersData.length} users` : 'No data yet'}
        </Typography>
        {toolbarActions && <Box sx={{ ml: 2 }}>{toolbarActions}</Box>}
      </Toolbar>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              {columns.length === 0 ? (
                <TableCell>No columns</TableCell>
              ) : (
                <>
                  {columns.map((col) => <TableCell key={col}>{col}</TableCell>)}
                  {showActions && <TableCell key="__actions">actions</TableCell>}
                </>
              )}
            </TableRow>
          </TableHead>
          <TableBody>
            {usersData.length === 0 ? (
              <TableRow>
                <TableCell colSpan={Math.max(columns.length + (showActions ? 1 : 0), 1)}>
                  <Typography variant="body2" color="text.secondary">{emptyState}</Typography>
                </TableCell>
              </TableRow>
            ) : (
              pageRows.map((row, idx) => (
                <TableRow key={idx} hover>
                  {columns.map((col) => (
                    <TableCell key={col}>{formatCell(col, row?.[col])}</TableCell>
                  ))}
                  {showActions && (
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                        {renderRowActions!(row)}
                      </Box>
                    </TableCell>
                  )}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
      <TablePagination
        component="div"
        count={usersData.length}
        page={page}
        rowsPerPage={ROWS_PER_PAGE}
        rowsPerPageOptions={[ROWS_PER_PAGE]}
        onPageChange={(_, newPage) => setPage(newPage)}
      />
    </Paper>
  );
}
