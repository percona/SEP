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

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Link as MuiLink,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import LockOpenOutlinedIcon from '@mui/icons-material/LockOpenOutlined';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import { useNavigate, useParams } from 'react-router';
import { CollectPane } from './CollectPane';
import { ResultsPane } from './ResultsPane';
import { useAtwIncident, useCloseAtwIncident, useReopenAtwIncident } from './hooks';

/**
 * Incident workspace rendered at ``/atw/:incidentId``. Two side-by-side panes —
 * Collect (browse, select, and batch-execute snippets) and Results (each
 * execution's status, logs, and file listing) — stacked on narrow screens.
 */
export function IncidentWorkspacePage() {
  const { incidentId } = useParams<{ incidentId: string }>();
  const navigate = useNavigate();
  const { data: incident, isLoading, error } = useAtwIncident(incidentId);
  const closeMutation = useCloseAtwIncident();
  const reopenMutation = useReopenAtwIncident();
  const isClosed = incident?.closed_at !== null && incident?.closed_at !== undefined;
  const lifecycleError = closeMutation.isError
    ? (closeMutation.error?.message ?? 'Failed to close incident')
    : reopenMutation.isError
      ? (reopenMutation.error?.message ?? 'Failed to reopen incident')
      : null;

  if (!incidentId) {
    return null;
  }

  return (
    <Box>
      <MuiLink
        component="button"
        type="button"
        onClick={() => navigate('..')}
        sx={{ mb: 2, display: 'inline-block' }}
      >
        ← Back to incidents
      </MuiLink>

      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load incident: {error.message}
        </Alert>
      )}

      {lifecycleError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          onClose={() => {
            closeMutation.reset();
            reopenMutation.reset();
          }}
        >
          {lifecycleError}
        </Alert>
      )}

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        justifyContent="space-between"
        spacing={1}
        sx={{ mb: 0.5 }}
      >
        <Typography variant="h4">{incident?.name ?? 'Incident'}</Typography>
        {incident && (
          <Stack direction="row" spacing={1}>
            {isClosed ? (
              <Button
                variant="outlined"
                size="small"
                startIcon={<LockOpenOutlinedIcon />}
                disabled={reopenMutation.isPending}
                onClick={() => {
                  closeMutation.reset();
                  reopenMutation.reset();
                  reopenMutation.mutate(incident.id);
                }}
              >
                Reopen incident
              </Button>
            ) : (
              <Button
                variant="outlined"
                size="small"
                startIcon={<LockOutlinedIcon />}
                disabled={closeMutation.isPending}
                onClick={() => {
                  closeMutation.reset();
                  reopenMutation.reset();
                  closeMutation.mutate(incident.id);
                }}
              >
                Close incident
              </Button>
            )}
          </Stack>
        )}
      </Stack>
      {isClosed && (
        <Alert severity="info" sx={{ mb: 2 }}>
          This incident is closed. Reopen it to run more diagnostic snippets.
        </Alert>
      )}
      {incident?.case_ref && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Case reference: {incident.case_ref}
        </Typography>
      )}

      <Box
        sx={{
          mt: 1,
          display: 'grid',
          gap: 2,
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(2, minmax(0, 1fr))' },
          alignItems: 'start',
        }}
      >
        <Paper variant="outlined" sx={{ p: 2 }}>
          <CollectPane incidentId={incidentId} isClosed={isClosed} />
        </Paper>
        <Paper variant="outlined" sx={{ p: 2 }}>
          <ResultsPane incidentId={incidentId} />
        </Paper>
      </Box>
    </Box>
  );
}
