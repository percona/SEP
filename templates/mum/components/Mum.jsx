
import React, { useEffect, useMemo, useRef, useState } from 'react';
import apiClient from "../../../ui/apiClient";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { Box, Button, CircularProgress, Paper, Toolbar, Typography } from "@mui/material";
import AddDatabaseUserButton from "./AddDatabaseUserButton";
import EditUserButton from "./EditUserButton";
import DeleteUserButton from "./DeleteUserButton";
import MumUserList from "./MumUserList";

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

const DEFAULT_FEATURE_TOGGLES = Object.freeze({
  addUser: true,
  editUser: true,
  deleteUser: true,
  listUsers: true,
});

const resolveFeatureToggles = () => {
  if (typeof window === "undefined" || typeof window.MUM_FEATURE_TOGGLES !== "object") {
    return DEFAULT_FEATURE_TOGGLES;
  }
  return { ...DEFAULT_FEATURE_TOGGLES, ...window.MUM_FEATURE_TOGGLES };
};

const Mum = () => {
  const [featureToggles, setFeatureToggles] = useState(() => resolveFeatureToggles());
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

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const handler = (event) => {
      const overrides = event?.detail;
      if (overrides && typeof overrides === "object") {
        setFeatureToggles((prev) => ({ ...prev, ...overrides }));
      } else {
        setFeatureToggles(resolveFeatureToggles());
      }
    };
    window.addEventListener("mum:feature-toggles", handler);
    return () => window.removeEventListener("mum:feature-toggles", handler);
  }, []);

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

    const handleUserMutation = () => {
      if (execution?.id) {
        checkScriptOutput();
      }
    };

    const rowActionsEnabled = featureToggles.editUser || featureToggles.deleteUser;
    const renderRowActions = rowActionsEnabled
      ? (row) => (
          <>
            {featureToggles.editUser && (
              <EditUserButton
                row={row}
                selectedTarget={selectedTarget}
                builtinRoles={builtinRoles}
                getCsrfToken={getCsrfToken}
                onSuccess={handleUserMutation}
              />
            )}
            {featureToggles.deleteUser && (
              <DeleteUserButton
                row={row}
                selectedTarget={selectedTarget}
                getCsrfToken={getCsrfToken}
                onSuccess={handleUserMutation}
              />
            )}
          </>
        )
      : null;

    const toolbarActions = featureToggles.addUser ? (
      <AddDatabaseUserButton
        selectedTarget={selectedTarget}
        builtinRoles={builtinRoles}
        getCsrfToken={getCsrfToken}
        onSuccess={handleUserMutation}
      />
    ) : null;

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

        {featureToggles.listUsers && (
          <MumUserList
            usersData={usersData}
            toolbarActions={toolbarActions}
            renderRowActions={renderRowActions}
          />
        )}
      </Box>
    </ThemeProvider>
  );
};

export default Mum;