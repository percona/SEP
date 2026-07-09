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

import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Typography from '@mui/material/Typography';
import { useNavigate } from 'react-router-dom';
import type { ListView } from '@sep/api';
import { SchemaListView, useHosts, type HostOption } from '@sep/framework';

/**
 * Read-only view of the executor/target hosts available to run tasks.
 *
 * Sourced from the shared {@link useHosts} hook (``GET /api/sep/hosts/``) — the
 * same Tasks/Inventory merge that backs ``HostSelector``. No inventory-DB entity
 * is involved: these are transient Nomad executor nodes, so the page bypasses the
 * app entity machinery and renders the framework hook's data directly. Loading,
 * error, and empty states are first-class (React Query ``isLoading`` / ``isError``;
 * the table's own empty render handles a successful empty list).
 */

const TARGET_HOSTS_LIST_VIEW: ListView = {
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'address', label: 'Address' },
  ],
};

function toRows(hosts: HostOption[]): Record<string, unknown>[] {
  return hosts.map((h) => ({ name: h.name, address: h.address }));
}

export function TargetHostsPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useHosts();
  const rows = toRows(data ?? []);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
        <IconButton onClick={() => navigate('..')} aria-label="Back to list">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">Target Hosts</Typography>
      </Box>

      {isError ? (
        <Alert severity="error" data-testid="target-hosts-error">
          Failed to load target hosts: {error?.message ?? 'Unknown error'}
        </Alert>
      ) : (
        <SchemaListView listView={TARGET_HOSTS_LIST_VIEW} data={rows} isLoading={isLoading} />
      )}
    </Box>
  );
}
