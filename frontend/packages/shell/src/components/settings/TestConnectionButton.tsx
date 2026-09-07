/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import NetworkCheckIcon from '@mui/icons-material/NetworkCheck';
import {
  useConnectivityCheck,
  type ConnectivityCheckRequest,
  type ConnectivityResult,
  type ConnectivityStatus,
} from '@sep/api';

/** Probe every external / inter-service endpoint on each click. */
const ALL_TARGETS: ConnectivityCheckRequest['targets'] = [
  'pmm',
  'inventory',
  'tasks',
  'nomad',
  'delivery',
];

type ChipColor = 'success' | 'error' | 'warning' | 'default';

/**
 * Label + colour per machine-readable outcome state. The backend classifies
 * each probe into one of these; unknown future values fall back to the
 * ``reachable`` boolean so a contract change never crashes the UI.
 */
const STATUS_CHIP: Record<ConnectivityStatus, { label: string; color: ChipColor }> = {
  reachable: { label: 'Reachable', color: 'success' },
  auth_failed: { label: 'Auth failed', color: 'error' },
  ssl_error: { label: 'SSL error', color: 'error' },
  timeout: { label: 'Timeout', color: 'warning' },
  unreachable: { label: 'Unreachable', color: 'warning' },
  error: { label: 'Error', color: 'error' },
  not_configured: { label: 'Not configured', color: 'default' },
  inputs_drifted: { label: 'Inputs drifted', color: 'warning' },
  probe_undeclared: { label: 'No probe declared', color: 'default' },
};

function chipFor(result: ConnectivityResult): { label: string; color: ChipColor } {
  return (
    STATUS_CHIP[result.status] ??
    (result.reachable
      ? { label: 'Reachable', color: 'success' }
      : { label: 'Not reachable', color: 'error' })
  );
}

function ConnectivityResults({ results }: { results: ConnectivityResult[] }) {
  if (results.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" data-testid="connectivity-empty">
        No endpoints were checked.
      </Typography>
    );
  }

  return (
    <Stack spacing={1} data-testid="connectivity-results">
      {results.map((result) => {
        const chip = chipFor(result);
        return (
          <Box
            key={result.service}
            data-testid={`conn-result-${result.service}`}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.5,
              py: 1,
              px: 1,
              borderBottom: 1,
              borderColor: 'divider',
            }}
          >
            <Typography variant="subtitle2" sx={{ minWidth: 96, fontWeight: 500 }}>
              {result.service}
            </Typography>
            <Chip
              size="small"
              label={chip.label}
              color={chip.color}
              data-testid={`conn-status-${result.service}`}
            />
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{
                flex: 1,
                minWidth: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                overflowWrap: 'anywhere',
              }}
            >
              {result.detail}
            </Typography>
            {result.version !== null && result.version !== undefined && (
              <Typography variant="caption" color="text.secondary">
                v{result.version}
              </Typography>
            )}
          </Box>
        );
      })}
    </Stack>
  );
}

/**
 * Toolbar action that probes the configured external endpoints on demand and
 * renders a per-service reachability result inline.
 *
 * Admin-gated by the enclosing page; the backend endpoint is admin-only too.
 */
export default function TestConnectionButton() {
  const check = useConnectivityCheck();

  const showPanel = check.isError || check.isSuccess;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
      <Button
        variant="outlined"
        startIcon={<NetworkCheckIcon />}
        onClick={() => check.mutate({ targets: ALL_TARGETS })}
        disabled={check.isPending}
      >
        {check.isPending ? 'Testing…' : 'Test connection'}
      </Button>

      {showPanel && (
        <Box sx={{ mt: 2, width: '100%', minWidth: { xs: 280, sm: 460 }, textAlign: 'left' }}>
          {check.isError ? (
            <Alert severity="error" data-testid="connectivity-error">
              Failed to run connectivity check: {check.error?.message}
            </Alert>
          ) : (
            <ConnectivityResults results={check.data} />
          )}
        </Box>
      )}
    </Box>
  );
}
