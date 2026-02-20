import React, { useMemo } from "react";
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Toolbar,
  Typography,
} from "@mui/material";

const getColumns = (rows) => {
  const cols = new Set();
  rows.forEach((row) => {
    Object.keys(row || {}).forEach((key) => cols.add(key));
  });
  return Array.from(cols);
};

const formatValue = (value) => {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

const MumUserList = ({
  usersData = [],
  title = "Users Table",
  toolbarActions = null,
  renderRowActions = null,
  emptyState = "No rows to display.",
}) => {
  const columns = useMemo(() => getColumns(usersData), [usersData]);
  const showActions = typeof renderRowActions === "function";

  if (!usersData && !toolbarActions) {
    return null;
  }

  return (
    <Paper elevation={1}>
      <Toolbar>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {usersData.length ? `${usersData.length} users` : "No data yet"}
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
                  {columns.map((col) => (
                    <TableCell key={col}>{col}</TableCell>
                  ))}
                  {showActions && <TableCell key="__actions">actions</TableCell>}
                </>
              )}
            </TableRow>
          </TableHead>
          <TableBody>
            {usersData.length === 0 ? (
              <TableRow>
                <TableCell colSpan={Math.max(columns.length + (showActions ? 1 : 0), 1)}>
                  <Typography variant="body2" color="text.secondary">
                    {emptyState}
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              usersData.map((row, idx) => (
                <TableRow key={idx} hover>
                  {columns.map((col) => (
                    <TableCell key={col}>{formatValue(row?.[col])}</TableCell>
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
    </Paper>
  );
};

export default MumUserList;
