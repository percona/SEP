import { useMemo, useState, useEffect } from 'react';
import {
  Box,
  Button,
  Chip,
  Paper,
  Popover,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import type { ReactNode } from 'react';

export interface RoleRef { role: string; db: string }
export interface Privilege { resource?: { cluster?: boolean; db?: string; collection?: string }; actions?: string[] }
export interface RoleRow {
  isBuiltin?: boolean;
  privileges?: Privilege[];
  inheritedPrivileges?: Privilege[];
  inheritedRoles?: RoleRef[];
  roles?: RoleRef[];
  [key: string]: unknown;
}

const ROWS_PER_PAGE = 10;
const EXCLUDED_COLUMNS = new Set(['isBuiltin', '_id', 'privileges', 'inheritedPrivileges']);

const getColumns = (rows: RoleRow[]): string[] => {
  const cols = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row ?? {}).forEach((key) => {
      if (!EXCLUDED_COLUMNS.has(key)) cols.add(key);
    });
  });
  return Array.from(cols);
};

const formatResource = (resource: Privilege['resource']): string => {
  if (!resource) return '?';
  if (resource.cluster) return 'cluster';
  const db = resource.db !== undefined ? (resource.db || '*') : '*';
  const col = resource.collection !== undefined ? (resource.collection || '*') : '*';
  return `${db}.${col}`;
};

const privKey = (p: Privilege): string =>
  `${formatResource(p.resource)}|${[...(p.actions ?? [])].sort().join(',')}`;

const findGrantingRoles = (privilege: Privilege, inheritedRoleRefs: RoleRef[], rolesData: RoleRow[]): string[] => {
  const resource = formatResource(privilege.resource);
  const actions = new Set(privilege.actions ?? []);
  const found: string[] = [];
  for (const ref of inheritedRoleRefs) {
    const roleObj = rolesData.find((r) => r.role === ref.role && r.db === ref.db);
    if (!roleObj) continue;
    const contributes = (roleObj.privileges ?? []).some(
      (p) =>
        formatResource(p.resource) === resource &&
        (p.actions ?? []).some((a) => actions.has(a)),
    );
    if (contributes) found.push(`${ref.role} @ ${ref.db}`);
  }
  return found;
};

interface PrivilegeGroupProps {
  privileges: Privilege[];
  label: string;
  chipColor: string;
  inheritedRoleRefs: RoleRef[];
  rolesData: RoleRow[];
}

const PrivilegeGroup = ({ privileges, label, chipColor, inheritedRoleRefs, rolesData }: PrivilegeGroupProps) => {
  if (!privileges.length) return null;
  const isInherited = chipColor !== 'primary';
  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography
        variant="caption"
        sx={{ fontWeight: 700, display: 'block', mb: 0.75, textTransform: 'uppercase', letterSpacing: 0.5 }}
        color={chipColor === 'primary' ? 'primary.main' : 'text.secondary'}
      >
        {label} ({privileges.length})
      </Typography>
      <Box sx={{ display: 'grid', gap: 0.75 }}>
        {privileges.map((p, i) => {
          const grantingRoles = isInherited ? findGrantingRoles(p, inheritedRoleRefs, rolesData) : [];
          return (
            <Box
              key={i}
              sx={{ pl: 1, borderLeft: '3px solid', borderColor: chipColor === 'primary' ? 'primary.main' : 'divider' }}
            >
              <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, flexWrap: 'wrap' }}>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>{formatResource(p.resource)}</Typography>
                {grantingRoles.length > 0 && (
                  <Typography variant="caption" color="text.secondary">via {grantingRoles.join(', ')}</Typography>
                )}
              </Box>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.25, mt: 0.25 }}>
                {(p.actions ?? []).map((a) => (
                  <Chip key={a} label={a} size="small" sx={{ height: 18, fontSize: '0.65rem' }} />
                ))}
              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
};

interface PrivilegesCellProps {
  direct: Privilege[];
  allInherited: Privilege[];
  inheritedRoleRefs: RoleRef[];
  rolesData: RoleRow[];
}

const PrivilegesCell = ({ direct, allInherited, inheritedRoleRefs, rolesData }: PrivilegesCellProps) => {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  const purelyInherited = useMemo(() => {
    const directSet = new Set(direct.map(privKey));
    return allInherited.filter((p) => !directSet.has(privKey(p)));
  }, [direct, allInherited]);

  const total = direct.length + purelyInherited.length;
  if (total === 0) return <Typography variant="body2" color="text.secondary">—</Typography>;

  return (
    <>
      <Button size="small" variant="outlined" onClick={(e) => setAnchor(e.currentTarget)} sx={{ minWidth: 36 }}>
        {total}
      </Button>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
      >
        <Box sx={{ p: 2, minWidth: 280, maxWidth: 440, maxHeight: 480, overflowY: 'auto' }}>
          <Typography variant="subtitle2" sx={{ mb: 1.5 }}>Privileges ({total})</Typography>
          <PrivilegeGroup privileges={direct} label="Direct" chipColor="primary" inheritedRoleRefs={[]} rolesData={[]} />
          <PrivilegeGroup privileges={purelyInherited} label="Inherited" chipColor="default" inheritedRoleRefs={inheritedRoleRefs} rolesData={rolesData} />
        </Box>
      </Popover>
    </>
  );
};

const InheritedRolesChips = ({ roles }: { roles: unknown }) => {
  if (!Array.isArray(roles) || roles.length === 0) return <span>—</span>;
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
      {(roles as RoleRef[]).map((r, i) => (
        <Chip key={i} label={r.role || JSON.stringify(r)} size="small" variant="outlined" />
      ))}
    </Box>
  );
};

const formatCell = (col: string, value: unknown): ReactNode => {
  if (value === null || value === undefined) return '';
  if (col === 'inheritedRoles' || col === 'roles') return <InheritedRolesChips roles={value} />;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

interface MumRoleListProps {
  rolesData?: RoleRow[];
  toolbarActions?: ReactNode;
  renderRowActions?: ((row: RoleRow) => ReactNode) | null;
  emptyState?: string;
}

export function MumRoleList({
  rolesData = [],
  toolbarActions = null,
  renderRowActions = null,
  emptyState = 'No roles to display.',
}: MumRoleListProps) {
  const columns = useMemo(() => getColumns(rolesData), [rolesData]);
  const showActions = typeof renderRowActions === 'function';
  const [page, setPage] = useState(0);

  useEffect(() => { setPage(0); }, [rolesData]);

  const pageRows = rolesData.slice(page * ROWS_PER_PAGE, (page + 1) * ROWS_PER_PAGE);

  return (
    <Paper elevation={1}>
      <Toolbar>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>Roles Table</Typography>
        <Typography variant="body2" color="text.secondary">
          {rolesData.length ? `${rolesData.length} roles` : 'No data yet'}
        </Typography>
        {toolbarActions && <Box sx={{ ml: 2 }}>{toolbarActions}</Box>}
      </Toolbar>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Type</TableCell>
              {columns.map((col) => <TableCell key={col}>{col}</TableCell>)}
              <TableCell>Privileges</TableCell>
              {showActions && <TableCell>actions</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {rolesData.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length + (showActions ? 3 : 2)}>
                  <Typography variant="body2" color="text.secondary">{emptyState}</Typography>
                </TableCell>
              </TableRow>
            ) : (
              pageRows.map((row, idx) => (
                <TableRow key={idx} hover sx={row.isBuiltin ? { opacity: 0.75 } : undefined}>
                  <TableCell>
                    {row.isBuiltin ? (
                      <Tooltip title="Built-in MongoDB role">
                        <Chip label="built-in" size="small" color="default" variant="outlined" />
                      </Tooltip>
                    ) : (
                      <Tooltip title="Custom user-defined role">
                        <Chip label="custom" size="small" color="info" variant="filled" />
                      </Tooltip>
                    )}
                  </TableCell>
                  {columns.map((col) => (
                    <TableCell key={col}>{formatCell(col, row?.[col])}</TableCell>
                  ))}
                  <TableCell>
                    <PrivilegesCell
                      direct={row.privileges ?? []}
                      allInherited={row.inheritedPrivileges ?? []}
                      inheritedRoleRefs={row.inheritedRoles ?? row.roles ?? []}
                      rolesData={rolesData}
                    />
                  </TableCell>
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
        count={rolesData.length}
        page={page}
        rowsPerPage={ROWS_PER_PAGE}
        rowsPerPageOptions={[ROWS_PER_PAGE]}
        onPageChange={(_, newPage) => setPage(newPage)}
      />
    </Paper>
  );
}
