// [MUM-REPLACE] This component's data-fetching layer (executor host options, list-users,
// list-roles and all CRUD operations) is currently implemented via SEP task-dispatch + SSE
// streaming.  When the SEP live-request API is available, replace every block marked
// [MUM-REPLACE] with a direct API call and remove the EventSource / stream-log logic.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiClient, getToken } from '@sep/api';
import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Tab,
  Tabs,
  Toolbar,
  Typography,
} from '@mui/material';
import { AddDatabaseUserButton } from './components/AddDatabaseUserButton';
import { EditUserButton } from './components/EditUserButton';
import { DeleteUserButton } from './components/DeleteUserButton';
import { MumUserList } from './MumUserList';
import { MumRoleList } from './MumRoleList';
import { AddCustomRoleButton } from './components/AddCustomRoleButton';
import { EditRoleButton } from './components/EditRoleButton';
import { DeleteRoleButton } from './components/DeleteRoleButton';
import type { UserRow } from './MumUserList';
import type { RoleRow } from './MumRoleList';

interface ExecutorHost {
  /** Executor node name used as the dispatch target */
  id: string;
  /** Human-readable label (inventory display name when available) */
  name: string;
  address: string;
}

export function MumPlugin() {
  const [error, setError] = useState<string | null>(null);
  const [executorHosts, setExecutorHosts] = useState<ExecutorHost[]>([]);
  const [selectedTarget, setSelectedTarget] = useState('');
  const [listBusyCount, setListBusyCount] = useState(0);
  const [activeTab, setActiveTab] = useState(0);

  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [usersData, setUsersData] = useState<UserRow[]>([]);

  const [isRolesStreaming, setIsRolesStreaming] = useState(false);
  const [rolesStreamError, setRolesStreamError] = useState<string | null>(null);
  const [rolesData, setRolesData] = useState<RoleRow[]>([]);
  const rolesStdoutBufferRef = useRef('');
  const rolesStderrBufferRef = useRef('');
  const rolesEsRef = useRef<EventSource | null>(null);

  const builtinRoles = useMemo(
    () => [
      'read', 'readWrite', 'dbAdmin', 'userAdmin', 'dbOwner',
      'readAnyDatabase', 'readWriteAnyDatabase', 'dbAdminAnyDatabase',
      'userAdminAnyDatabase', 'clusterAdmin', 'clusterManager',
      'clusterMonitor', 'hostManager', 'backup', 'restore', 'root',
    ],
    [],
  );

  const stdoutBufferRef = useRef('');
  const stderrBufferRef = useRef('');
  const esRef = useRef<EventSource | null>(null);
  const usersStreamGenRef = useRef(0);
  const rolesStreamGenRef = useRef(0);

  const listBusy = listBusyCount > 0;
  const [rolesBusy, setRolesBusy] = useState(false);

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const resp = await apiClient.get<{ id: string; name: string; address: string }[]>('/sep/hosts/');
        setExecutorHosts(resp.data.map((h) => ({ id: h.id, name: h.name, address: h.address })));
      } catch (_) {
        // swallow
      }
    };
    loadOptions();
  }, []);

  function extractJsonArray(text: string): unknown[] | null {
    const start = text.indexOf('[');
    const end = text.lastIndexOf(']');
    if (start !== -1 && end !== -1 && end > start) {
      try {
        const parsed = JSON.parse(text.slice(start, end + 1));
        if (Array.isArray(parsed)) return parsed;
      } catch (_) {
        return null;
      }
    }
    return null;
  }

  const stopStreaming = useCallback(() => {
    usersStreamGenRef.current++;
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  useEffect(() => () => stopStreaming(), [stopStreaming]);

  // [MUM-REPLACE] begin — SSE stream consumer for task-log output (list-users job)
  // Replace with a direct API call that returns user data synchronously.
  const streamListUsers = useCallback(
    (historyId: string) => {
      if (!historyId) { setStreamError('Missing execution history ID.'); return; }
      stopStreaming();
      const gen = usersStreamGenRef.current;
      setStreamError(null);
      setIsStreaming(true);
      stdoutBufferRef.current = '';
      stderrBufferRef.current = '';

      let retries = 0;
      const MAX_RETRIES = 8;
      const RETRY_DELAY = 2000;

      const connect = () => {
        if (usersStreamGenRef.current !== gen) return;
        try {
          const token = getToken();
          const streamUrl = `/stream-logs/${encodeURIComponent(historyId)}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
          const es = new EventSource(streamUrl);
          esRef.current = es;

          es.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data as string) as Record<string, unknown>;
              const { msg, type, step } = data;
              if (step === 'run-script' && typeof msg === 'string') {
                if (type === 'stdout') {
                  stdoutBufferRef.current += msg;
                  const arr = extractJsonArray(stdoutBufferRef.current);
                  if (arr) {
                    setUsersData(arr as UserRow[]);
                    setStreamError(null);
                    stopStreaming();
                  }
                } else if (type === 'stderr') {
                  stderrBufferRef.current += msg;
                }
              }
            } catch (_) { /* ignore non-JSON */ }
          };

          es.addEventListener('finish', () => {
            if (esRef.current !== es) return;
            const arr = extractJsonArray(stdoutBufferRef.current);
            if (arr) {
              setUsersData(arr as UserRow[]);
              stopStreaming();
            } else if (retries < MAX_RETRIES) {
              retries++;
              es.close();
              esRef.current = null;
              stdoutBufferRef.current = '';
              stderrBufferRef.current = '';
              setTimeout(connect, RETRY_DELAY);
            } else {
              const errDetail = stderrBufferRef.current.trim();
              stopStreaming();
              setStreamError(errDetail || 'Could not parse output JSON.');
            }
          });

          es.onerror = () => {
            if (usersStreamGenRef.current !== gen || esRef.current !== es) return;
            es.close();
            esRef.current = null;
            if (retries < MAX_RETRIES) {
              retries++;
              setTimeout(connect, RETRY_DELAY);
            } else {
              stopStreaming();
              setStreamError('Stream failed.');
            }
          };
        } catch (e) {
          setStreamError(String((e as Error)?.message ?? e));
          setIsStreaming(false);
        }
      };

      connect();
    },
    [stopStreaming],
  );
  // [MUM-REPLACE] end

  // [MUM-REPLACE] begin — SSE stream consumer for task-log output (list-roles job)
  // Replace with a direct API call that returns role data synchronously.
  const streamListRoles = useCallback((historyId: string) => {
    if (!historyId) { setRolesStreamError('Missing execution history ID.'); return; }
    if (rolesEsRef.current) { rolesEsRef.current.close(); rolesEsRef.current = null; }
    rolesStreamGenRef.current++;
    const gen = rolesStreamGenRef.current;
    setRolesStreamError(null);
    setIsRolesStreaming(true);
    rolesStdoutBufferRef.current = '';
    rolesStderrBufferRef.current = '';

    let retries = 0;
    const MAX_RETRIES = 8;
    const RETRY_DELAY = 2000;

    const connect = () => {
      if (rolesStreamGenRef.current !== gen) return;
      try {
        const token = getToken();
        const streamUrl = `/stream-logs/${encodeURIComponent(historyId)}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
        const es = new EventSource(streamUrl);
        rolesEsRef.current = es;

        const stopRoles = () => {
          rolesStreamGenRef.current++;
          if (rolesEsRef.current === es) {
            es.close();
            rolesEsRef.current = null;
          }
          setIsRolesStreaming(false);
        };

        es.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data as string) as Record<string, unknown>;
            const { msg, type, step } = data;
            if (step === 'run-script' && typeof msg === 'string') {
              if (type === 'stdout') {
                rolesStdoutBufferRef.current += msg;
                const arr = extractJsonArray(rolesStdoutBufferRef.current);
                if (arr) { setRolesData(arr as RoleRow[]); setRolesStreamError(null); stopRoles(); }
              } else if (type === 'stderr') {
                rolesStderrBufferRef.current += msg;
              }
            }
          } catch (_) { /* ignore */ }
        };

        es.addEventListener('finish', () => {
          if (rolesEsRef.current !== es) return;
          const arr = extractJsonArray(rolesStdoutBufferRef.current);
          if (arr) {
            setRolesData(arr as RoleRow[]);
            stopRoles();
          } else if (retries < MAX_RETRIES) {
            retries++;
            es.close();
            rolesEsRef.current = null;
            rolesStdoutBufferRef.current = '';
            rolesStderrBufferRef.current = '';
            setTimeout(connect, RETRY_DELAY);
          } else {
            const errDetail = rolesStderrBufferRef.current.trim();
            stopRoles();
            setRolesStreamError(errDetail || 'Could not parse output JSON.');
          }
        });

        es.onerror = () => {
          if (rolesStreamGenRef.current !== gen || rolesEsRef.current !== es) return;
          es.close();
          rolesEsRef.current = null;
          if (retries < MAX_RETRIES) {
            retries++;
            setTimeout(connect, RETRY_DELAY);
          } else {
            stopRoles();
            setRolesStreamError('Stream failed.');
          }
        };
      } catch (e) {
        setRolesStreamError(String((e as Error)?.message ?? e));
        setIsRolesStreaming(false);
      }
    };

    connect();
  }, []);
  // [MUM-REPLACE] end

  const listRoles = useCallback(
    async (targetOverride?: string) => {
      const target = targetOverride ?? selectedTarget;
      if (!target) { setError('Select an executor host first.'); return; }
      setRolesBusy(true);
      setError(null);
      setRolesStreamError(null);
      setRolesData([]);
      try {
        // [MUM-REPLACE] begin — dispatch list-roles task via SEP internal endpoint, then stream logs
        const response = await apiClient.post('/plugins/mum/ui/list-roles', { target });
        const rolesHistoryData = (response.data as Record<string, unknown>)?.['history'] as Record<string, unknown> | undefined;
        streamListRoles(rolesHistoryData?.['id'] as string);
        // [MUM-REPLACE] end
      } catch (err) {
        const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string };
        if (e?.response?.status === 409) return;
        setError(e?.response?.data?.detail ?? e?.message ?? 'Failed to list roles');
      } finally {
        setRolesBusy(false);
      }
    },
    [selectedTarget, streamListRoles],
  );

  const listUsers = useCallback(
    async (targetOverride?: string) => {
      const target = targetOverride ?? selectedTarget;
      if (!target) { setError('Select an executor host first.'); return; }
      setListBusyCount((c) => c + 1);
      setError(null);
      setStreamError(null);
      setUsersData([]);
      listRoles(target);
      try {
        // [MUM-REPLACE] begin — dispatch list-users task via SEP internal endpoint, then stream logs
        const response = await apiClient.post('/plugins/mum/ui/list-users', { target });
        const historyData = (response.data as Record<string, unknown>)?.['history'] as Record<string, unknown> | undefined;
        streamListUsers(historyData?.['id'] as string);
        // [MUM-REPLACE] end
      } catch (err) {
        const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string };
        if (e?.response?.status === 409) return;
        setError(e?.response?.data?.detail ?? e?.message ?? 'Failed to list users');
      } finally {
        setListBusyCount((c) => Math.max(c - 1, 0));
      }
    },
    [selectedTarget, streamListUsers, listRoles],
  );

  const handleUserMutation = useCallback(
    (meta?: { target?: string }) => {
      // Delay so any in-flight list-users task dispatched before the mutation
      // has time to finish; otherwise the fresh dispatch gets a 409 and reuses
      // a task that ran before the mutation, returning stale data.
      setTimeout(() => listUsers(meta?.target), 4000);
    },
    [listUsers],
  );

  const handleRoleMutation = useCallback(
    (meta?: { target?: string }) => {
      setTimeout(() => listRoles(meta?.target), 4000);
    },
    [listRoles],
  );

  const renderRowActions = (row: UserRow) => (
    <>
      <EditUserButton
        row={row}
        selectedTarget={selectedTarget}
        builtinRoles={builtinRoles}
        rolesData={rolesData}
        onSuccess={handleUserMutation}
      />
      <DeleteUserButton row={row} selectedTarget={selectedTarget} onSuccess={handleUserMutation} />
    </>
  );

  const toolbarActions = (
    <AddDatabaseUserButton
      selectedTarget={selectedTarget}
      builtinRoles={builtinRoles}
      rolesData={rolesData}
      onSuccess={handleUserMutation}
    />
  );

  return (
    <Box sx={{ display: 'grid', gap: 2 }}>
      <Paper elevation={1} sx={{ p: 2 }}>
        <Toolbar sx={{ px: 0 }}>
          <Typography variant="h6" sx={{ flex: 1 }}>
            MongoDB User Management (MUM)
          </Typography>
        </Toolbar>

        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
          <label>
            Executor host:&nbsp;
            <select value={selectedTarget} onChange={(e) => setSelectedTarget(e.target.value)}>
              <option value="">Select a host</option>
              {executorHosts.map((host) => (
                <option key={host.id} value={host.id}>
                  {host.name !== host.id ? `${host.name} (${host.id})` : host.id}
                </option>
              ))}
            </select>
          </label>
        </Box>

        <Tabs value={activeTab} onChange={(_, val: number) => setActiveTab(val)} sx={{ mb: 2 }}>
          <Tab label="Users" />
          <Tab label="Roles" />
        </Tabs>

        {activeTab === 0 && (
          <>
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
              <Button
                variant="contained"
                color="primary"
                onClick={() => listUsers()}
                disabled={listBusy || !selectedTarget}
              >
                {listBusy ? 'Listing users…' : 'List users'}
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
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
              <Button
                variant="contained"
                color="primary"
                onClick={() => listRoles()}
                disabled={rolesBusy || !selectedTarget}
              >
                {rolesBusy ? 'Listing roles…' : 'List roles'}
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

      {activeTab === 0 && (
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
  );
}
