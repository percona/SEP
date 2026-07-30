import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { apiClient } from '@sep/api';
import type { HostTopology, MongoRole } from './types';

interface DiscoverRun {
  host_id: string;
  host_name: string | null;
  task_history_id: string;
}

interface DiscoverResponse {
  runs: DiscoverRun[];
}

interface StatusResponse {
  host_id: string;
  task_history_id: string;
  status: string;
  role: MongoRole | null;
  set_name: string | null;
  me: string | null;
  mongod_version: string | null;
}

const ROLE_COLORS: Record<MongoRole, 'error' | 'success' | 'default' | 'warning' | 'info'> = {
  primary: 'error',
  secondary: 'success',
  arbiter: 'default',
  standalone: 'info',
  unreachable: 'warning',
};

function RoleBadge({ role }: { role: MongoRole | null }) {
  if (!role) return <CircularProgress size={16} />;
  return (
    <Chip
      label={role.charAt(0).toUpperCase() + role.slice(1)}
      color={ROLE_COLORS[role]}
      size="small"
    />
  );
}

interface Props {
  topology: HostTopology[];
  onTopologyDiscovered: (topology: HostTopology[]) => void;
}

export function TopologyPanel({ topology, onTopologyDiscovered }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<HostTopology[]>(topology);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const pollStatus = useCallback(
    async (current: HostTopology[]) => {
      const pending = current.filter((r) => r.status === 'pending' || r.status === 'running');
      if (pending.length === 0) {
        stopPolling();
        setBusy(false);
        return;
      }
      try {
        const ids = current.map((r) => r.task_history_id).join(',');
        const resp = await apiClient.get<StatusResponse[]>('/sep/mongo-upgrade/topology-status', {
          params: { ids },
        });
        const updated = current.map((row) => {
          const hit = resp.data.find((s) => s.task_history_id === row.task_history_id);
          if (!hit) return row;
          const s = hit.status.toLowerCase();
          const status =
            s === 'success' || s === 'failed' || s === 'stopped' || s === 'stale'
              ? 'done'
              : s === 'running'
                ? 'running'
                : 'pending';
          return {
            ...row,
            status: status as HostTopology['status'],
            role: hit.role,
            set_name: hit.set_name,
            me: hit.me,
            mongod_version: hit.mongod_version,
          } satisfies HostTopology;
        });
        setRows(updated);
        const allDone = updated.every((r) => r.status === 'done');
        if (allDone) {
          stopPolling();
          setBusy(false);
        }
      } catch {
        // keep polling on transient errors
      }
    },
    [stopPolling],
  );

  const discover = useCallback(async () => {
    stopPolling();
    setBusy(true);
    setError(null);
    setRows([]);
    try {
      const resp = await apiClient.post<DiscoverResponse>('/sep/mongo-upgrade/discover');
      const initial: HostTopology[] = resp.data.runs.map((r) => ({
        host_id: r.host_id,
        host_name: r.host_name,
        task_history_id: r.task_history_id,
        status: 'pending',
        role: null,
        set_name: null,
        me: null,
        mongod_version: null,
      }));
      setRows(initial);
      pollRef.current = setInterval(() => {
        setRows((current) => {
          void pollStatus(current);
          return current;
        });
      }, 3000);
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(e?.response?.data?.detail ?? e?.message ?? 'Discovery failed');
      setBusy(false);
    }
  }, [stopPolling, pollStatus]);

  const mongoHosts = rows.filter(
    (r) => r.role && r.role !== 'unreachable',
  );
  const hasResults = rows.length > 0;
  const allDone = rows.length > 0 && rows.every((r) => r.status === 'done');

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Runs an Ansible playbook on each executor host to query the local MongoDB instance and
        identify replica set topology. MongoDB nodes are the only hosts offered in the upgrade
        chain.
      </Typography>

      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 2 }}>
        <Button variant="contained" onClick={discover} disabled={busy}>
          {busy ? 'Discovering…' : hasResults ? 'Re-discover' : 'Discover Topology'}
        </Button>
        {busy && <CircularProgress size={20} />}
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {hasResults && (
        <>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Host</TableCell>
                <TableCell>Role</TableCell>
                <TableCell>Version</TableCell>
                <TableCell>Replica Set</TableCell>
                <TableCell>Member</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.host_id}>
                  <TableCell>{row.host_name || row.host_id}</TableCell>
                  <TableCell>
                    <RoleBadge role={row.role} />
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" fontFamily="monospace">
                      {row.mongod_version ?? (row.status === 'done' ? '—' : '')}
                    </Typography>
                  </TableCell>
                  <TableCell>{row.set_name ?? '—'}</TableCell>
                  <TableCell>{row.me ?? '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {allDone && mongoHosts.length > 0 && (
            <Alert
              severity="success"
              sx={{ mt: 2 }}
              action={
                <Button
                  color="inherit"
                  size="small"
                  variant="outlined"
                  onClick={() => onTopologyDiscovered(rows)}
                >
                  Proceed to Plan Upgrade →
                </Button>
              }
            >
              Found {mongoHosts.length} MongoDB node{mongoHosts.length !== 1 ? 's' : ''}.
            </Alert>
          )}

          {allDone && mongoHosts.length === 0 && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              No MongoDB nodes found on any executor host.
            </Alert>
          )}
        </>
      )}
    </Box>
  );
}
