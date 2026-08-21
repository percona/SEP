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

import { Box, Button, CircularProgress, Tooltip } from '@mui/material';
import NetworkCheckIcon from '@mui/icons-material/NetworkCheck';
import { ApiError, useAuth } from '@sep/api';
import { useSnackbar } from 'notistack';
import { useCheckServiceConnectivity } from './hooks';

/**
 * Service types the server knows how to probe, mirroring the connectable set
 * the check endpoint enforces. This copy only decides whether the button is
 * offered; the server rejects anything else regardless.
 */
const CONNECTABLE_SERVICE_TYPES = new Set(['mysql', 'postgresql', 'mongodb']);

/**
 * Run an on-demand database connectivity probe for one inventory service.
 *
 * Unlike `SyncControl`, this reports the passing case too: a check whose whole
 * purpose is to tell you whether the database is reachable is useless if only
 * failures are visible.
 */
export function ConnectivityControl({
  serviceId,
  serviceType,
}: {
  serviceId: string | number;
  serviceType?: unknown;
}) {
  const { canMutate } = useAuth();
  const checkConnectivity = useCheckServiceConnectivity(serviceId);
  const { enqueueSnackbar } = useSnackbar();

  const isConnectable =
    typeof serviceType === 'string' && CONNECTABLE_SERVICE_TYPES.has(serviceType);
  const isPending = checkConnectivity.isPending;

  function handleCheck() {
    checkConnectivity.mutate(undefined, {
      onSuccess: (result) => {
        if (result.success) {
          enqueueSnackbar('Connectivity check passed', { variant: 'success' });
        } else {
          enqueueSnackbar(`Connectivity check failed: ${result.error ?? 'Unknown error'}`, {
            variant: 'error',
          });
        }
      },
      onError: (err) => {
        const message =
          err instanceof ApiError
            ? err.message
            : 'Connectivity check could not be started. Please try again.';
        enqueueSnackbar(message, { variant: 'error' });
      },
    });
  }

  // The probe is a POST, so a read-only session is offered no button at all.
  if (!canMutate) {
    return null;
  }

  return (
    <Box sx={{ mt: 3 }}>
      {/* A disabled MUI button swallows hover, so the tooltip anchors to a wrapper. */}
      <Tooltip
        title={isConnectable ? '' : 'Connectivity checks are not supported for this service type'}
      >
        <Box component="span" sx={{ display: 'inline-block' }}>
          <Button
            variant="outlined"
            size="small"
            disabled={!isConnectable || isPending}
            startIcon={
              isPending ? <CircularProgress size={14} color="inherit" /> : <NetworkCheckIcon />
            }
            onClick={handleCheck}
          >
            Check connectivity
          </Button>
        </Box>
      </Tooltip>
    </Box>
  );
}
