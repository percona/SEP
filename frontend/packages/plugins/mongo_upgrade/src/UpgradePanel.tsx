import { useCallback, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemText,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import { apiClient } from '@sep/api';
import type { HostTopology, MongoRole } from './types';

const ROLE_ORDER: Record<MongoRole, number> = {
  secondary: 0,
  arbiter: 1,
  standalone: 2,
  primary: 3,
  unreachable: 99,
};

interface Props {
  topology: HostTopology[];
  onBack: () => void;
}

export function UpgradePanel({ topology, onBack }: Props) {
  const mongoHosts = topology
    .filter((h) => h.role && h.role !== 'unreachable')
    .sort((a, b) => ROLE_ORDER[a.role!] - ROLE_ORDER[b.role!]);

  const [orderedHosts, setOrderedHosts] = useState<HostTopology[]>(mongoHosts);
  const [mongoRelease, setMongoRelease] = useState('psmdb-80');
  const [mongoVersion, setMongoVersion] = useState('');
  const [restartService, setRestartService] = useState('mongod');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dispatchedId, setDispatchedId] = useState<string | null>(null);

  const moveUp = useCallback((idx: number) => {
    if (idx === 0) return;
    setOrderedHosts((prev) => {
      const next = [...prev];
      [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
      return next;
    });
  }, []);

  const moveDown = useCallback((idx: number) => {
    setOrderedHosts((prev) => {
      if (idx === prev.length - 1) return prev;
      const next = [...prev];
      [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
      return next;
    });
  }, []);

  const dispatch = useCallback(async () => {
    if (orderedHosts.length === 0) return;
    setBusy(true);
    setError(null);
    setDispatchedId(null);

    const [first, ...rest] = orderedHosts;

    const body = {
      target: first.host_id,
      mongo_release: mongoRelease.trim(),
      mongo_version: mongoVersion.trim(),
      restart_service: restartService.trim(),
      chain_targets: rest.map((h) => h.host_id),
    };

    try {
      const resp = await apiClient.post<{ task_history_id: string }>(
        '/sep/mongo-upgrade/upgrade',
        body,
      );
      setDispatchedId(resp.data.task_history_id ?? 'dispatched');
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(e?.response?.data?.detail ?? e?.message ?? 'Dispatch failed');
    } finally {
      setBusy(false);
    }
  }, [orderedHosts, mongoRelease, mongoVersion, restartService]);

  if (dispatchedId) {
    return (
      <Alert severity="success">
        Rolling upgrade dispatched. The chain will proceed host-by-host; each step starts only
        after the previous one succeeds.
        {dispatchedId !== 'dispatched' && (
          <>
            {' '}
            Track progress in{' '}
            <a href={`/tasks`} target="_blank" rel="noreferrer">
              Task Manager
            </a>
            .
          </>
        )}
      </Alert>
    );
  }

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Arrange the upgrade order. Secondaries and arbiters run before the primary — the safest
        pattern for a replica set rolling upgrade. Each host upgrades only after the previous host
        finishes successfully.
      </Typography>

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Upgrade order
      </Typography>

      <List dense disablePadding sx={{ mb: 3, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
        {orderedHosts.map((host, idx) => (
          <ListItem
            key={host.host_id}
            divider={idx < orderedHosts.length - 1}
            secondaryAction={
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <Tooltip title="Move up">
                  <span>
                    <IconButton size="small" onClick={() => moveUp(idx)} disabled={idx === 0}>
                      <ArrowUpwardIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title="Move down">
                  <span>
                    <IconButton
                      size="small"
                      onClick={() => moveDown(idx)}
                      disabled={idx === orderedHosts.length - 1}
                    >
                      <ArrowDownwardIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
            }
          >
            <ListItemText
              primary={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="body2" color="text.secondary">
                    {idx + 1}.
                  </Typography>
                  <span>{host.host_name || host.host_id}</span>
                  {host.role && (
                    <Chip
                      label={host.role}
                      size="small"
                      color={host.role === 'primary' ? 'error' : 'default'}
                    />
                  )}
                  {host.set_name && (
                    <Typography variant="caption" color="text.secondary">
                      {host.set_name}
                    </Typography>
                  )}
                </Box>
              }
            />
          </ListItem>
        ))}
      </List>

      <Divider sx={{ mb: 3 }} />

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Options
      </Typography>

      <Box sx={{ display: 'grid', gap: 2, maxWidth: 480, mb: 3 }}>
        <TextField
          label="Release channel"
          value={mongoRelease}
          onChange={(e) => setMongoRelease(e.target.value)}
          helperText='Percona release channel — e.g. "psmdb-80" for PSMDB 8.0'
          size="small"
          required
        />
        <TextField
          label="Specific version (optional)"
          value={mongoVersion}
          onChange={(e) => setMongoVersion(e.target.value)}
          helperText='Package version prefix — e.g. "8.0.12-7". Leave blank to install latest in the channel.'
          size="small"
        />
        <TextField
          label="Service to restart"
          value={restartService}
          onChange={(e) => setRestartService(e.target.value)}
          helperText="systemd unit restarted after each upgrade step"
          size="small"
        />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Box sx={{ display: 'flex', gap: 2 }}>
        <Button variant="outlined" onClick={onBack} disabled={busy}>
          Back to Topology
        </Button>
        <Button
          variant="contained"
          color="error"
          onClick={dispatch}
          disabled={busy || orderedHosts.length === 0}
        >
          {busy ? <CircularProgress size={18} color="inherit" /> : 'Start Rolling Upgrade'}
        </Button>
      </Box>
    </Box>
  );
}
