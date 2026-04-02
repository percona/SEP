import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import apiClient from "../../../ui/apiClient";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Tab,
  Tabs,
  Toolbar,
  Typography,
} from "@mui/material";
import AddDatabaseUserButton from "./AddDatabaseUserButton";
import EditUserButton from "./EditUserButton";
import DeleteUserButton from "./DeleteUserButton";
import MumUserList from "./MumUserList";
import MumRoleList from "./MumRoleList";
import AddCustomRoleButton from "./AddCustomRoleButton";
import EditRoleButton from "./EditRoleButton";
import DeleteRoleButton from "./DeleteRoleButton";

// Build a MUI theme that mirrors CSS variables from base.css
function buildMuiThemeFromCssVars() {
  const css = getComputedStyle(document.body);
  const getVar = (name, fallback) =>
    (css.getPropertyValue(name) || fallback || "").trim();
  const mode =
    document.body.getAttribute("data-theme") === "dark" ? "dark" : "light";
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
        default: getVar(
          "--surfaceElevation0",
          mode === "dark" ? "#2C323E" : "#f0f1f4"
        ),
        paper: getVar(
          "--surfaceElevation1",
          mode === "dark" ? "#3A4151" : "#fff"
        ),
      },
      divider: getVar(
        "--lineDivider",
        mode === "dark" ? "rgba(255,255,255,0.25)" : "rgba(44,50,62,0.25)"
      ),
      text: {
        primary: getVar(
          "--textPrimary",
          mode === "dark" ? "#FBFBFB" : "#2C323E"
        ),
        secondary: getVar(
          "--textSecondary",
          mode === "dark" ? "rgba(251,251,251,0.72)" : "rgba(44,50,62,0.72)"
        ),
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
  if (
    typeof window === "undefined" ||
    typeof window.MUM_FEATURE_TOGGLES !== "object"
  ) {
    return DEFAULT_FEATURE_TOGGLES;
  }
  return { ...DEFAULT_FEATURE_TOGGLES, ...window.MUM_FEATURE_TOGGLES };
};

const normalizeExecutorHosts = (rawHosts) => {
  if (!Array.isArray(rawHosts)) {
    return [];
  }
  return rawHosts
    .map((host) => {
      if (typeof host === "string") {
        return { name: host, address: "" };
      }
      if (host && typeof host === "object") {
        const name =
          host.name ||
          host.Name ||
          host.hostname ||
          host.Hostname ||
          host.id ||
          host.address ||
          host.Address ||
          "";
        if (!name) {
          return null;
        }
        return {
          name,
          address: host.address || host.Address || host.ip || host.IP || "",
        };
      }
      return null;
    })
    .filter(Boolean);
};

const Mum = () => {
  const [featureToggles, setFeatureToggles] = useState(() =>
    resolveFeatureToggles()
  );
  const [defaultTask, setDefaultTask] = useState(null);
  const [error, setError] = useState(null);
  const [executorHosts, setExecutorHosts] = useState([]);
  const [selectedTarget, setSelectedTarget] = useState("");
  const [execution, setExecution] = useState(null);
  const [listBusyCount, setListBusyCount] = useState(0);

  // Tab state: 0 = Users, 1 = Roles
  const [activeTab, setActiveTab] = useState(0);

  // Output streaming state
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState(null);
  const [usersData, setUsersData] = useState([]);
  const [lastListTarget, setLastListTarget] = useState("");

  // Roles streaming state
  const [isRolesStreaming, setIsRolesStreaming] = useState(false);
  const [rolesStreamError, setRolesStreamError] = useState(null);
  const [rolesData, setRolesData] = useState([]);
  const rolesStdoutBufferRef = useRef("");
  const rolesEsRef = useRef(null);
  const builtinRoles = useMemo(
    () => [
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
    ],
    []
  );

  // Track theme changes by observing data-theme attribute on <body>
  const [themeKey, setThemeKey] = useState(
    document.body.getAttribute("data-theme") || "dark"
  );
  useEffect(() => {
    const updateThemeKey = () => {
      setThemeKey(document.body.getAttribute("data-theme") || "dark");
    };
    // Ensure we pick up changes that might have happened before the observer was ready
    updateThemeKey();
    const obs = new MutationObserver(updateThemeKey);
    obs.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
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

  const listBusy = listBusyCount > 0;

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const resp = await apiClient.get("/mum/ui/options");
        setExecutorHosts(normalizeExecutorHosts(resp.data?.executor_hosts));
        // The backend always ensures the default task exists, so we can safely use it
        if (resp.data?.default_task) {
          setDefaultTask(resp.data.default_task);
        }
      } catch (e) {
        // swallow for now
      }
    };
    loadOptions();
  }, []);

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

  const stopStreaming = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  useEffect(() => () => stopStreaming(), [stopStreaming]);

  const streamListUsers = useCallback(
    (historyId) => {
      if (!historyId) {
        setStreamError("Missing execution history ID.");
        return;
      }
      stopStreaming();
      setStreamError(null);
      setIsStreaming(true);
      stdoutBufferRef.current = "";

      try {
        const es = new EventSource(
          `/stream-logs/${encodeURIComponent(historyId)}`
        );
        esRef.current = es;

        es.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            const { msg, type, step } = data || {};

            if (
              type === "stdout" &&
              step === "run-script" &&
              typeof msg === "string"
            ) {
              stdoutBufferRef.current += msg;

              // Attempt to parse the buffer
              const arr = extractJsonArray(stdoutBufferRef.current);

              if (Array.isArray(arr)) {
                setUsersData(arr);
                setStreamError(null);

                // Close immediately upon success ---
                stopStreaming();
              }
            }
          } catch (_) {
            // ignore non-JSON chunks
          }
        };

        // The 'finish' listener remains as a fallback, but won't be reached
        // if we successfully parsed the data and called stopStreaming() above.
        es.addEventListener("finish", () => {
          stopStreaming();
          const arr = extractJsonArray(stdoutBufferRef.current);
          if (Array.isArray(arr)) {
            setUsersData(arr);
          } else {
            setStreamError("Could not parse output JSON.");
          }
        });

        es.onerror = () => {
          setStreamError("Stream failed.");
          stopStreaming();
        };
      } catch (e) {
        setStreamError(String(e?.message || e));
        setIsStreaming(false);
      }
    },
    [stopStreaming]
  );

  const streamListRoles = useCallback(
    (historyId) => {
      if (!historyId) {
        setRolesStreamError("Missing execution history ID.");
        return;
      }
      if (rolesEsRef.current) {
        rolesEsRef.current.close();
        rolesEsRef.current = null;
      }
      setRolesStreamError(null);
      setIsRolesStreaming(true);
      rolesStdoutBufferRef.current = "";

      try {
        const es = new EventSource(
          `/stream-logs/${encodeURIComponent(historyId)}`
        );
        rolesEsRef.current = es;

        const stopRoles = () => {
          es.close();
          rolesEsRef.current = null;
          setIsRolesStreaming(false);
        };

        es.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            const { msg, type, step } = data || {};
            if (
              type === "stdout" &&
              step === "run-script" &&
              typeof msg === "string"
            ) {
              rolesStdoutBufferRef.current += msg;
              const arr = extractJsonArray(rolesStdoutBufferRef.current);
              if (Array.isArray(arr)) {
                setRolesData(arr);
                setRolesStreamError(null);
                stopRoles();
              }
            }
          } catch (_) {
            // ignore non-JSON chunks
          }
        };

        es.addEventListener("finish", () => {
          stopRoles();
          const arr = extractJsonArray(rolesStdoutBufferRef.current);
          if (Array.isArray(arr)) {
            setRolesData(arr);
          } else {
            setRolesStreamError("Could not parse output JSON.");
          }
        });

        es.onerror = () => {
          setRolesStreamError("Stream failed.");
          stopRoles();
        };
      } catch (e) {
        setRolesStreamError(String(e?.message || e));
        setIsRolesStreaming(false);
      }
    },
    []
  );

  const [rolesBusy, setRolesBusy] = useState(false);

  const listRoles = useCallback(
    async (targetOverride) => {
      const target = targetOverride || selectedTarget;
      if (!target) {
        setError("Select an executor host first.");
        return;
      }
      setRolesBusy(true);
      setError(null);
      setRolesStreamError(null);
      setRolesData([]);
      try {
        const response = await apiClient.post(`/mum/ui/list-roles`, {
          target,
        });
        streamListRoles(response.data?.history?.id);
      } catch (err) {
        const detail =
          err?.response?.data?.detail || err?.message || "Failed to list roles";
        setError(detail);
      } finally {
        setRolesBusy(false);
      }
    },
    [selectedTarget, streamListRoles]
  );

  const listUsers = useCallback(
    async (targetOverride) => {
      const target = targetOverride || selectedTarget;
      if (!target) {
        setError("Select an executor host first.");
        return;
      }
      setListBusyCount((count) => count + 1);
      setError(null);
      setStreamError(null);
      setExecution(null);
      setUsersData([]);
      // Fetch roles in parallel: pre-populates Roles tab and role selectors.
      listRoles(target);
      try {
        const response = await apiClient.post(`/mum/ui/list-users`, {
          target,
        });
        setLastListTarget(target);
        setExecution(response.data?.history);
        streamListUsers(response.data?.history?.id);
      } catch (err) {
        const detail =
          err?.response?.data?.detail || err?.message || "Failed to list users";
        setError(detail);
      } finally {
        setListBusyCount((count) => Math.max(count - 1, 0));
      }
    },
    [selectedTarget, streamListUsers, listRoles]
  );

  const handleUserMutation = useCallback(
    (meta) => {
      listUsers(meta?.target);
    },
    [listUsers]
  );

  const handleRoleMutation = useCallback(
    (meta) => {
      listRoles(meta?.target);
    },
    [listRoles]
  );

  const rowActionsEnabled =
    featureToggles.editUser || featureToggles.deleteUser;
  const renderRowActions = rowActionsEnabled
    ? (row) => (
        <>
          {featureToggles.editUser && (
            <EditUserButton
              row={row}
              selectedTarget={selectedTarget}
              builtinRoles={builtinRoles}
              rolesData={rolesData}
              onSuccess={handleUserMutation}
            />
          )}
          {featureToggles.deleteUser && (
            <DeleteUserButton
              row={row}
              selectedTarget={selectedTarget}
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
      rolesData={rolesData}
      onSuccess={handleUserMutation}
    />
  ) : null;

  return (
    <ThemeProvider theme={theme}>
      <Box sx={{ display: "grid", gap: 2 }}>
        <Paper elevation={1} sx={{ p: 2 }}>
          <Toolbar sx={{ px: 0 }}>
            <Typography variant="h6" sx={{ flex: 1 }}>
              MongoDB User Management (MUM)
            </Typography>
          </Toolbar>

          <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", mb: 2 }}>
            <label>
              Executor host:&nbsp;
              <select
                value={selectedTarget}
                onChange={(e) => setSelectedTarget(e.target.value)}
              >
                <option value="">Select a host</option>
                {executorHosts.map((host) => (
                  <option key={host.name} value={host.name}>
                    {host.address && host.address !== host.name
                      ? `${host.name} (${host.address})`
                      : host.name}
                  </option>
                ))}
              </select>
            </label>
          </Box>

          <Tabs
            value={activeTab}
            onChange={(_, val) => setActiveTab(val)}
            sx={{ mb: 2 }}
          >
            <Tab label="Users" />
            <Tab label="Roles" />
          </Tabs>

          {activeTab === 0 && (
            <>
              <Box
                sx={{
                  display: "flex",
                  gap: 1,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <Button
                  variant="contained"
                  color="primary"
                  onClick={() => listUsers()}
                  disabled={listBusy || !selectedTarget}
                >
                  {listBusy ? "Listing users…" : "List users"}
                </Button>
                {isStreaming && <CircularProgress size={20} />}
              </Box>
              {streamError && (
                <Typography color="error" sx={{ mt: 1 }}>
                  Output error: {streamError}
                </Typography>
              )}
            </>
          )}

          {activeTab === 1 && (
            <>
              <Box
                sx={{
                  display: "flex",
                  gap: 1,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <Button
                  variant="contained"
                  color="primary"
                  onClick={() => listRoles()}
                  disabled={rolesBusy || !selectedTarget}
                >
                  {rolesBusy ? "Listing roles…" : "List roles"}
                </Button>
                {isRolesStreaming && <CircularProgress size={20} />}
              </Box>
              {rolesStreamError && (
                <Typography color="error" sx={{ mt: 1 }}>
                  Output error: {rolesStreamError}
                </Typography>
              )}
            </>
          )}

          {error && (
            <Typography color="error" sx={{ mt: 1 }}>
              Error: {error}
            </Typography>
          )}
        </Paper>

        {activeTab === 0 && featureToggles.listUsers && (
          <MumUserList
            usersData={usersData}
            toolbarActions={toolbarActions}
            renderRowActions={renderRowActions}
          />
        )}

        {activeTab === 1 && (
          <MumRoleList
            rolesData={rolesData}
            toolbarActions={
              <AddCustomRoleButton
                selectedTarget={selectedTarget}
                rolesData={rolesData}
                onSuccess={handleRoleMutation}
              />
            }
            renderRowActions={(row) =>
              row.isBuiltin ? null : (
                <>
                  <EditRoleButton
                    row={row}
                    selectedTarget={selectedTarget}
                    rolesData={rolesData}
                    onSuccess={handleRoleMutation}
                  />
                  <DeleteRoleButton
                    row={row}
                    selectedTarget={selectedTarget}
                    onSuccess={handleRoleMutation}
                  />
                </>
              )
            }
          />
        )}
      </Box>
    </ThemeProvider>
  );
};

export default Mum;
