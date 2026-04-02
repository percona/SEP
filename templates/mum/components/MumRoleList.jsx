import React, { useMemo, useState, useEffect } from "react";
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
  Tooltip,
  Typography,
} from "@mui/material";

const ROWS_PER_PAGE = 10;

const EXCLUDED_COLUMNS = new Set(["isBuiltin", "_id"]);

const getColumns = (rows) => {
  const cols = new Set();
  rows.forEach((row) => {
    Object.keys(row || {}).forEach((key) => {
      if (!EXCLUDED_COLUMNS.has(key)) cols.add(key);
    });
  });
  return Array.from(cols);
};

const InheritedPrivilegesChips = ({ privileges }) => {
  if (!Array.isArray(privileges) || privileges.length === 0)
    return <span>—</span>;
  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
      {privileges.map((p, i) => (
        <Chip key={i} label={p.role || JSON.stringify(p)} size="small" variant="outlined" />
      ))}
    </Box>
  );
};

const formatCell = (col, value) => {
  if (value === null || value === undefined) return "";
  if (col === "inheritedRoles" || col === "roles")
    return <InheritedPrivilegesChips privileges={value} />;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

const MumRoleList = ({
  rolesData = [],
  toolbarActions = null,
  renderRowActions = null,
  emptyState = "No roles to display.",
}) => {
  const columns = useMemo(() => getColumns(rolesData), [rolesData]);
  const showActions = typeof renderRowActions === "function";
  const [page, setPage] = useState(0);

  useEffect(() => { setPage(0); }, [rolesData]);

  const pageRows = rolesData.slice(page * ROWS_PER_PAGE, (page + 1) * ROWS_PER_PAGE);

  return (
    <Paper elevation={1}>
      <Toolbar>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>
          Roles Table
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {rolesData.length ? `${rolesData.length} roles` : "No data yet"}
        </Typography>
        {toolbarActions && <Box sx={{ ml: 2 }}>{toolbarActions}</Box>}
      </Toolbar>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              {/* Always show a Type column first */}
              <TableCell>Type</TableCell>
              {columns.map((col) => (
                <TableCell key={col}>{col}</TableCell>
              ))}
              {showActions && <TableCell>actions</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {rolesData.length === 0 ? (
              <TableRow>
                <TableCell colSpan={Math.max(columns.length + (showActions ? 2 : 1), 1)}>
                  <Typography variant="body2" color="text.secondary">
                    {emptyState}
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              pageRows.map((row, idx) => (
                <TableRow
                  key={idx}
                  hover
                  sx={row.isBuiltin ? { opacity: 0.75 } : undefined}
                >
                  <TableCell>
                    <Tooltip
                      title={
                        row.isBuiltin
                          ? "Built-in MongoDB role"
                          : "Custom user-defined role"
                      }
                    >
                      <Chip
                        label={row.isBuiltin ? "built-in" : "custom"}
                        size="small"
                        color={row.isBuiltin ? "default" : "primary"}
                        variant={row.isBuiltin ? "outlined" : "filled"}
                      />
                    </Tooltip>
                  </TableCell>
                  {columns.map((col) => (
                    <TableCell key={col}>{formatCell(col, row?.[col])}</TableCell>
                  ))}
                  {showActions && (
                    <TableCell>
                      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
                        {renderRowActions(row)}
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
};

export default MumRoleList;
