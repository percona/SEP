import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiClient } from '@sep/api';
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
  name: string;
  address: string;
}

const normalizeExecutorHosts = (rawHosts: unknown): ExecutorHost[] => {
  if (!Array.isArray(rawHosts)) return [];
  return rawHosts
    .map((host) => {
      if (typeof host === 'string') return { name: host, address: '' };
      if (host && typeof host === 'object') {
        const h = host as Record<string, unknown>;
        const name = String(
          h['name'] || h['Name'] || h['hostname'] || h['Hostname'] || h['id'] || h['address'] || h['Address'] || '',
        );
        if (!name) return null;
        return { name, address: String(h['address'] || h['Address'] || h['ip'] || h['IP'] || '') };
      }
      return null;
    })
    .filter((x): x is ExecutorHost => x !== null);
};

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
  const esRef = useRef<EventSource | null>(null);

  const listBusy = listBusyCount > 0;
  const [rolesBusy, setRolesBusy] = useState(false);

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const resp = await apiClient.get('/mum/ui/options');
        setExecutorHosts(normalizeExecutorHosts((resp.data as Record<string, unknown>)?.['executor_hosts']));
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
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  useEffect(() => () => stopStreaming(), [stopStreaming]);

  const streamListUsers = useCallback(
    (historyId: string) => {
      if (!historyId) { setStreamError('Missing execution history ID.'); return; }
      stopStreaming();
      setStreamError(null);
      setIsStreaming(true);
      stdoutBufferRef.current = '';

      try {
        const es = new EventSource(`/stream-logs/${encodeURIComponent(historyId)}`);
        esRef.current = es;

        es.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data as string) as Record<string, unknown>;
            const { msg, type, step } = data;
            if (type === 'stdout' && step === 'run-script' && typeof msg === 'string') {
              stdoutBufferRef.current += msg;
              const arr = extractJsonArray(stdoutBufferRef.current);
              if (arr) {
                setUsersData(arr as UserRow[]);
                setStreamError(null);
                stopStreaming();
              }
            }
          } catch (_) { /* ignore non-JSON */ }
        };

        es.addEventListener('finish', () => {
          stopStreaming();
          const arr = extractJsonArray(stdoutBufferRef.current);
          if (arr) setUsersData(arr as UserRow[]);
          else setStreamError('Could not parse output JSON.');
        });

        es.onerror = () => { setStreamError('Stream failed.'); stopStreaming(); };
      } catch (e) {
        setStreamError(String((e as Error)?.message ?? e));
        setIsStreaming(false);
      }
    },
    [stopStreaming],
  );

  const streamListRoles = useCallback((historyId: string) => {
    if (!historyId) { setRolesStreamError('Missing execution history ID.'); return; }
    if (rolesEsRef.current) { rolesEsRef.current.close(); rolesEsRef.current = null; }
    setRolesStreamError(null);
    setIsRolesStreaming(true);
    rolesStdoutBufferRef.current = '';

    try {
      const es = new EventSource(`/stream-logs/${encodeURIComponent(historyId)}`);
      rolesEsRef.current = es;

      const stopRoles = () => {
        es.close();
        rolesEsRef.current = null;
        setIsRolesStreaming(false);
      };

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string) as Record<string, unknown>;
          const { msg, type, step } = data;
          if (type === 'stdout' && step === 'run-script' && typeof msg === 'string') {
            rolesStdoutBufferRef.current += msg;
            const arr = extractJsonArray(rolesStdoutBufferRef.current);
            if (arr) { setRolesData(arr as RoleRow[]); setRolesStreamError(null); stopRoles(); }
          }
        } catch (_) { /* ignore */ }
      };

      es.addEventListener('finish', () => {
        stopRoles();
        const arr = extractJsonArray(rolesStdoutBufferRef.current);
        if (arr) setRolesData(arr as RoleRow[]);
        else setRolesStreamError('Could not parse output JSON.');
      });

      es.onerror = () => { setRolesStreamError('Stream failed.'); stopRoles(); };
    } catch (e) {
      setRolesStreamError(String((e as Error)?.message ?? e));
      setIsRolesStreaming(false);
    }
  }, []);

  const listRoles = useCallback(
    async (targetOverride?: string) => {
      const target = targetOverride ?? selectedTarget;
      if (!target) { setError('Select an executor host first.'); return; }
      setRolesBusy(true);
      setError(null);
      setRolesStreamError(null);
      setRolesData([]);
      try {
        const response = await apiClient.post('/mum/ui/list-roles', { target });
        const rolesHistoryData = (response.data as Record<string, unknown>)?.['history'] as Record<string, unknown> | undefined;
        streamListRoles(rolesHistoryData?.['id'] as string);
      } catch (err) {
        const e = err as { response?: { data?: { detail?: string } }; message?: string };
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
        const response = await apiClient.post('/mum/ui/list-users', { target });
        const historyData = (response.data as Record<string, unknown>)?.['history'] as Record<string, unknown> | undefined;
        streamListUsers(historyData?.['id'] as string);
      } catch (err) {
        const e = err as { response?: { data?: { detail?: string } }; message?: string };
        setError(e?.response?.data?.detail ?? e?.message ?? 'Failed to list users');
      } finally {
        setListBusyCount((c) => Math.max(c - 1, 0));
      }
    },
    [selectedTarget, streamListUsers, listRoles],
  );

  const handleUserMutation = useCallback(
    (meta?: { target?: string }) => { listUsers(meta?.target); },
    [listUsers],
  );

  const handleRoleMutation = useCallback(
    (meta?: { target?: string }) => { listRoles(meta?.target); },
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
                <option key={host.name} value={host.name}>
                  {host.address && host.address !== host.name
                    ? `${host.name} (${host.address})`
                    : host.name}
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
