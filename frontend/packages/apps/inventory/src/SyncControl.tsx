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

import { useState } from 'react';
import { Button, ButtonGroup, CircularProgress, Menu, MenuItem } from '@mui/material';
import AutorenewIcon from '@mui/icons-material/Autorenew';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { ApiError } from '@sep/api';
import { useSnackbar } from 'notistack';
import {
  useAvailableSyncers,
  useRefreshEntitiesOnSyncComplete,
  useSyncStatus,
  useTriggerSync,
} from './hooks';

export function SyncControl() {
  const { data: syncers = [], isLoading: syncersLoading } = useAvailableSyncers();
  const hasSyncers = !syncersLoading && syncers.length > 0;
  const { data: syncStatus } = useSyncStatus(hasSyncers);
  // Re-fetch the visible entity list once the background sync finishes; the
  // completion signal only arrives via the status poll above. This covers both
  // "Sync all" and single-syncer dropdown triggers, since both share one status.
  useRefreshEntitiesOnSyncComplete(syncStatus?.is_running);
  const triggerSync = useTriggerSync();
  const { enqueueSnackbar } = useSnackbar();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  if (syncersLoading || syncers.length === 0) {
    return null;
  }

  const isRunning = syncStatus?.is_running ?? false;
  const isDisabled = isRunning || triggerSync.isPending;
  const showDropdown = syncers.length > 1;

  function handleTrigger(syncerName?: string) {
    setAnchorEl(null);
    triggerSync.mutate(syncerName, {
      onError: (err) => {
        if (err instanceof ApiError && err.status === 400) {
          enqueueSnackbar(err.message, { variant: 'error' });
        } else {
          enqueueSnackbar('Failed to start sync. Please try again.', { variant: 'error' });
        }
      },
    });
  }

  return (
    <>
      <ButtonGroup variant="outlined" size="small" disabled={isDisabled}>
        <Button
          aria-label="Sync all configured syncers"
          startIcon={
            isDisabled ? <CircularProgress size={14} color="inherit" /> : <AutorenewIcon />
          }
          onClick={() => handleTrigger()}
        >
          Sync all
        </Button>
        {showDropdown && (
          <Button
            aria-label="Select a syncer"
            aria-haspopup="true"
            aria-expanded={Boolean(anchorEl)}
            onClick={(e) => setAnchorEl(e.currentTarget)}
            sx={{ px: 1, minWidth: 0 }}
          >
            <ExpandMoreIcon fontSize="small" />
          </Button>
        )}
      </ButtonGroup>
      {showDropdown && (
        <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
          {syncers.map((syncer) => (
            <MenuItem
              key={syncer.name}
              disabled={isDisabled}
              onClick={() => handleTrigger(syncer.name)}
            >
              <AutorenewIcon fontSize="small" sx={{ mr: 1 }} />
              Sync {syncer.display_name}
            </MenuItem>
          ))}
        </Menu>
      )}
    </>
  );
}
