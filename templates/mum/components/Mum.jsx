
import React, { useEffect, useMemo, useRef, useState } from 'react';
import apiClient from "../../../ui/apiClient";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  InputLabel,
  FormControl,
  OutlinedInput,
  Chip,
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

let cachedCsrfToken = null;
function getCsrfToken() {
  return cachedCsrfToken;
}

// Build a MUI theme that mirrors CSS variables from base.css
function buildMuiThemeFromCssVars() {
  const css = getComputedStyle(document.body);
  const getVar = (name, fallback) => (css.getPropertyValue(name) || fallback || "").trim();
  const mode = document.body.getAttribute("data-theme") === "dark" ? "dark" : "light";
  return createTheme({
    palette: {
      mode,
      primary: {
        main: getVar("--primaryMain", mode === "dark" ? "#FFA966" : "#E87318"),
        light: getVar("--primaryLight"),
        dark: getVar("--primaryDark"),
        contrastText: getVar("--primaryContrast"),
      },
      background: {
        default: getVar("--surfaceElevation0", mode === "dark" ? "#2C323E" : "#f0f1f4"),
        paper: getVar("--surfaceElevation1", mode === "dark" ? "#3A4151" : "#fff"),
      },
      divider: getVar("--lineDivider", mode === "dark" ? "rgba(255,255,255,0.25)" : "rgba(44,50,62,0.25)"),
      text: {
        primary: getVar("--textPrimary", mode === "dark" ? "#FBFBFB" : "#2C323E"),
        secondary: getVar("--textSecondary", mode === "dark" ? "rgba(251,251,251,0.72)" : "rgba(44,50,62,0.72)"),
      },
    },
    components: {
      MuiTableCell: {
        styleOverrides: {
          root: {
            borderColor: getVar("--lineDivider"),
          },
          head: {
            fontWeight: 600,
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
          },
        },
      },
    },
  });
}

const Mum = () => {
  const [createdTask, setCreatedTask] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [executorHosts, setExecutorHosts] = useState([]);
  const [services, setServices] = useState([]);
  const [selectedTarget, setSelectedTarget] = useState("");
  const [selectedService, setSelectedService] = useState("");
  const [execution, setExecution] = useState(null);

  // Output streaming state
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState(null);
  const [usersData, setUsersData] = useState([]);

  // User dialog (create/edit) state
  const [createOpen, setCreateOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState(null);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRoles, setNewRoles] = useState([]);
  const [rolesDb, setRolesDb] = useState("admin");
  const [isEditing, setIsEditing] = useState(false);

  // Delete dialog state
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleteUserInfo, setDeleteUserInfo] = useState({ username: "", db: "admin" });
  const builtinRoles = useMemo(() => ([
    "read",
    "readWrite",
    "dbAdmin",
    "userAdmin",
    "dbOwner",
    "readAnyDatabase",
    "readWriteAnyDatabase",
    "dbAdminAnyDatabase",
    "userAdminAnyDatabase",
    "clusterAdmin",
    "clusterManager",
    "clusterMonitor",
    "hostManager",
    "backup",
    "restore",
    "root",
  ]), []);

  // Track theme changes by observing data-theme attribute on <body>
  const [themeKey, setThemeKey] = useState(document.body.getAttribute("data-theme") || "dark");
  useEffect(() => {
    const obs = new MutationObserver(() => {
      setThemeKey(document.body.getAttribute("data-theme") || "dark");
    });
    obs.observe(document.body, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  const theme = useMemo(() => buildMuiThemeFromCssVars(), [themeKey]);

  // stdout buffer assembled from SSE messages
  const stdoutBufferRef = useRef("");
  const esRef = useRef(null);

  // Build a valid JSON body and include CSRF token where backend expects it
  const buildPayload = () => ({
    name: "mum-get-users",
    // This becomes meta.config in the PROXY run-python mapping
    payload: JSON.stringify({ action: "list_users" }),
    fmt: "json",
    alert_on_fail: false,
    ["csrf-token"]: getCsrfToken(),
  });

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const resp = await apiClient.get('/mum/ui/options');
        setExecutorHosts(resp.data.executor_hosts || []);
        setServices(resp.data.services || []);
        cachedCsrfToken = resp.data.csrf_token || null;
      } catch (e) {
        // swallow for now
      }
    };
    loadOptions();
  }, []);

  const createTask = async () => {
    setLoading(true);
    setError(null);
    setCreatedTask(null);

    try {
      const response = await apiClient.post('/mum/ui/usertask', buildPayload());
      setCreatedTask(response.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const executeTask = async () => {
    if (!createdTask?.name || !selectedTarget) {
      setError('Select a target and create the task first.');
      return;
    }
    setLoading(true);
    setError(null);
    setExecution(null);
    try {
      const response = await apiClient.post(
        `/mum/ui/execute/${createdTask.name}`,
        { target: selectedTarget, ["csrf-token"]: getCsrfToken() }
      );
      setExecution(response.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  function extractJsonArray(text) {
    // Attempt to extract a JSON array even if extra text is present
    const start = text.indexOf("[");
    const end = text.lastIndexOf("]");
    if (start !== -1 && end !== -1 && end > start) {
      const candidate = text.slice(start, end + 1);
      try {
        return JSON.parse(candidate);
      } catch (_) {
        return null;
      }
    }
    return null;
  }

  const stopStreaming = () => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setIsStreaming(false);
  };

  const checkScriptOutput = async () => {
    if (!execution?.id) {
      setStreamError("Execute the task first to obtain an execution ID.");
      return;
    }
    setStreamError(null);
    setIsStreaming(true);
    setUsersData([]);
    stdoutBufferRef.current = "";

    // Subscribe to SSE stream for this history id
    try {
      const es = new EventSource(`/stream-logs/${encodeURIComponent(execution.id)}`);
      esRef.current = es;
      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const { msg, type } = data || {};
          if (type === 'stdout' && typeof msg === 'string') {
            stdoutBufferRef.current += msg;
          }
        } catch (_) {
          // ignore non-JSON chunks
        }
      };
      es.addEventListener('finish', () => {
        stopStreaming();
        const arr = extractJsonArray(stdoutBufferRef.current);
        if (Array.isArray(arr)) setUsersData(arr);
        else setStreamError('Could not parse output JSON.');
      });
      es.onerror = () => {
        setStreamError('Stream failed.');
        stopStreaming();
      };
    } catch (e) {
      setStreamError(String(e?.message || e));
      setIsStreaming(false);
    }
  };

  const allColumns = useMemo(() => {
    const cols = new Set();
    usersData.forEach((row) => Object.keys(row || {}).forEach((k) => cols.add(k)));
    return Array.from(cols);
  }, [usersData]);

  const openCreateDialog = () => {
    setIsEditing(false);
    setCreateError(null);
    setNewUsername("");
    setNewPassword("");
    setNewRoles([]);
    setRolesDb("admin");
    setCreateOpen(true);
  };

  const openEditDialog = (row) => {
    const username = row?.user || row?.username || "";
    const dbName = row?.db || "admin";
    const rolesFromRow = Array.isArray(row?.roles) ? row.roles : [];
    const roleNames = rolesFromRow.map((r) => (typeof r === 'string' ? r : r?.role)).filter(Boolean);
    setIsEditing(true);
    setCreateError(null);
    setNewUsername(username);
    setNewPassword("");
    setNewRoles(roleNames);
    setRolesDb(dbName);
    setCreateOpen(true);
  };

  const submitUserDialog = async () => {
    if (!selectedTarget) {
      setCreateError('Select an executor host first.');
      return;
    }
    if (!newUsername) {
      setCreateError('Username is required.');
      return;
    }
    if (!isEditing) {
      if (!newPassword || newRoles.length === 0) {
        setCreateError('Password and at least one role are required.');
        return;
      }
    }
    setCreateLoading(true);
    setCreateError(null);
    try {
      if (isEditing) {
        const body = {
          target: selectedTarget,
          username: newUsername,
          db: rolesDb || 'admin',
          roles: newRoles,
          ["csrf-token"]: getCsrfToken(),
        };
        if (newPassword) body.password = newPassword;
        await apiClient.post('/mum/ui/update-user', body);
      } else {
        await apiClient.post('/mum/ui/create-user', {
          target: selectedTarget,
          username: newUsername,
          password: newPassword,
          roles: newRoles,
          db: rolesDb,
          ["csrf-token"]: getCsrfToken(),
        });
      }
      setCreateOpen(false);
      setNewUsername("");
      setNewPassword("");
      setNewRoles([]);
      setRolesDb("admin");
    } catch (e) {
      const actionText = isEditing ? 'update' : 'create';
      setCreateError(e?.response?.data?.detail || e?.message || `Failed to ${actionText} user`);
    } finally {
      setCreateLoading(false);
    }
  };

  const openDeleteDialog = (row) => {
    const username = row?.user || row?.username || "";
    const dbName = row?.db || "admin";
    setDeleteUserInfo({ username, db: dbName });
    setDeleteConfirmText("");
    setDeleteError(null);
    setDeleteOpen(true);
  };

  const submitDeleteUser = async () => {
    if (!selectedTarget) {
      setDeleteError('Select an executor host first.');
      return;
    }
    if (deleteConfirmText !== 'confirm') {
      setDeleteError("Type 'confirm' to proceed.");
      return;
    }
    setDeleteLoading(true);
    setDeleteError(null);
    try {
      await apiClient.post('/mum/ui/delete-user', {
        target: selectedTarget,
        username: deleteUserInfo.username,
        db: deleteUserInfo.db || 'admin',
        ["csrf-token"]: getCsrfToken(),
      });
      setDeleteOpen(false);
      setDeleteConfirmText("");
    } catch (e) {
      setDeleteError(e?.response?.data?.detail || e?.message || 'Failed to delete user');
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <ThemeProvider theme={theme}>
      <Box sx={{ display: 'grid', gap: 2 }}>
        <Paper elevation={1} sx={{ p: 2 }}>
          <Toolbar sx={{ px: 0 }}>
            <Typography variant="h6" sx={{ flex: 1 }}>MongoDB Users (MUM)</Typography>
          </Toolbar>

          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
            <label>
              Executor host:&nbsp;
              <select value={selectedTarget} onChange={(e) => setSelectedTarget(e.target.value)}>
                <option value="">Select a host</option>
                {executorHosts.map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </label>
            <label>
              Service:&nbsp;
              <select value={selectedService} onChange={(e) => setSelectedService(e.target.value)}>
                <option value="">Select a service</option>
                {services.map((s) => (
                  <option key={s.id} value={s.id}>{s.name || s.id}</option>
                ))}
              </select>
            </label>
          </Box>

          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button variant="contained" color="primary" onClick={createTask} disabled={loading}>
              {loading ? 'Working…' : 'Create “get users” Task'}
            </Button>
            <Button variant="outlined" onClick={executeTask} disabled={loading || !createdTask || !selectedTarget}>
              Execute Task
            </Button>
            <Button variant="text" onClick={checkScriptOutput} disabled={!execution?.id || isStreaming}>
              {isStreaming ? 'Streaming…' : 'Check Run-Script Output'}
            </Button>
            {isStreaming && <CircularProgress size={20} />}
          </Box>

          {error && (
            <Typography color="error" sx={{ mt: 1 }}>Error: {error}</Typography>
          )}
          {streamError && (
            <Typography color="error" sx={{ mt: 1 }}>Output error: {streamError}</Typography>
          )}

          {createdTask && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="body2">
                <strong>Task Name:</strong> <code>{createdTask.name}</code>
              </Typography>
              <Typography variant="body2">
                <strong>Task ID:</strong> <code>{createdTask.id}</code>
              </Typography>
            </Box>
          )}

          {execution && (
            <Box sx={{ mt: 1 }}>
              <Typography variant="body2">
                <strong>History ID:</strong> <code>{execution.id}</code>
              </Typography>
              <Typography variant="body2">
                <strong>Status:</strong> <code>{execution.status}</code>
              </Typography>
            </Box>
          )}
        </Paper>

        <Paper elevation={1}>
          <Toolbar>
            <Typography variant="subtitle1" sx={{ flex: 1 }}>Users Table</Typography>
            <Typography variant="body2" color="text.secondary">
              {usersData.length ? `${usersData.length} users` : 'No data yet'}
            </Typography>
            <Box sx={{ ml: 2 }}>
              <Button
                variant="contained"
                color="success"
                onClick={openCreateDialog}
              >
                + add database user
              </Button>
            </Box>
          </Toolbar>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {allColumns.length === 0 ? (
                    <TableCell>No columns</TableCell>
                  ) : (
                    <>
                      {allColumns.map((col) => (
                        <TableCell key={col}>{col}</TableCell>
                      ))}
                      <TableCell key="__actions">actions</TableCell>
                    </>
                  )}
                </TableRow>
              </TableHead>
              <TableBody>
                {usersData.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={Math.max(allColumns.length + 1, 1)}>
                      <Typography variant="body2" color="text.secondary">No rows to display.</Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  usersData.map((row, idx) => (
                    <TableRow key={idx} hover>
                      {allColumns.map((col) => {
                        const val = row?.[col];
                        const display = (val === null || val === undefined)
                          ? ''
                          : (typeof val === 'object' ? JSON.stringify(val) : String(val));
                        return <TableCell key={col}>{display}</TableCell>;
                      })}
                      <TableCell>
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          <Button size="small" variant="outlined" onClick={() => openEditDialog(row)}>EDIT</Button>
                          <Button size="small" color="error" variant="outlined" onClick={() => openDeleteDialog(row)}>DELETE</Button>
                        </Box>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      </Box>
      <Dialog open={createOpen} onClose={() => !createLoading && setCreateOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{isEditing ? 'Edit MongoDB user' : 'Create MongoDB user'}</DialogTitle>
        <DialogContent sx={{ display: 'grid', gap: 2, pt: 2 }}>
          <TextField
            label="Username"
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            disabled={createLoading || isEditing}
            required
            fullWidth
          />
          <TextField
            label="Password"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            disabled={createLoading}
            required={!isEditing}
            fullWidth
          />
          <FormControl fullWidth>
            <InputLabel id="roles-label">Built-in roles</InputLabel>
            <Select
              labelId="roles-label"
              multiple
              value={newRoles}
              onChange={(e) => setNewRoles(typeof e.target.value === 'string' ? e.target.value.split(',') : e.target.value)}
              input={<OutlinedInput id="select-multiple-chip" label="Built-in roles" />}
              renderValue={(selected) => (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {selected.map((value) => (
                    <Chip key={value} label={value} />
                  ))}
                </Box>
              )}
              disabled={createLoading}
            >
              {builtinRoles.map((role) => (
                <MenuItem key={role} value={role}>{role}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Role database"
            value={rolesDb}
            onChange={(e) => setRolesDb(e.target.value)}
            disabled={createLoading}
            helperText="Database where roles apply (default admin)"
            fullWidth
          />
          {createError && (
            <Typography color="error" variant="body2">{createError}</Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)} disabled={createLoading}>Cancel</Button>
          <Button onClick={submitUserDialog} variant="contained" color="success" disabled={createLoading}>
            {createLoading ? (isEditing ? 'Saving…' : 'Creating…') : (isEditing ? 'Save' : 'Create')}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteOpen} onClose={() => !deleteLoading && setDeleteOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Delete MongoDB user</DialogTitle>
        <DialogContent sx={{ display: 'grid', gap: 2, pt: 2 }}>
          <Typography variant="body2">
            You are about to delete user <strong>{deleteUserInfo.username}</strong> from DB <code>{deleteUserInfo.db}</code>.
          </Typography>
          <TextField
            label="Type 'confirm' to proceed"
            value={deleteConfirmText}
            onChange={(e) => setDeleteConfirmText(e.target.value)}
            disabled={deleteLoading}
            fullWidth
          />
          {deleteError && (
            <Typography color="error" variant="body2">{deleteError}</Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)} disabled={deleteLoading}>Cancel</Button>
          <Button onClick={submitDeleteUser} variant="contained" color="error" disabled={deleteLoading}>
            {deleteLoading ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </ThemeProvider>
  );
};

export default Mum;