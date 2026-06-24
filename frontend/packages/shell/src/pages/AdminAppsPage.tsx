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
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import LockIcon from '@mui/icons-material/Lock';
import { useMutationState } from '@tanstack/react-query';
import { LoadableChildren } from '@percona/percona-ui';
import {
  ADMIN_APP_MUTATION_KEY,
  appStateErrorMessage,
  isTransitional,
  useAdminApps,
  useForceDisableApp,
  useSetAppState,
  type AdminApp,
  type AppLifecycleState,
} from '@sep/api';

import { useAuth } from '../contexts/auth';
import { useNotification } from '../contexts/notification';

/** Chip colour per lifecycle state. Transitional states read as "in progress". */
const STATE_CHIP: Record<
  AppLifecycleState,
  { label: string; color: 'success' | 'default' | 'warning' | 'info' }
> = {
  ENABLED: { label: 'Enabled', color: 'success' },
  DISABLED: { label: 'Disabled', color: 'default' },
  ENABLING: { label: 'Enabling…', color: 'info' },
  DISABLING: { label: 'Disabling…', color: 'warning' },
};

function AppRow({
  app,
  onToggle,
  onForceDisable,
  busy,
}: {
  app: AdminApp;
  onToggle: (app: AdminApp) => void;
  onForceDisable: (app: AdminApp) => void;
  busy: boolean;
}) {
  const transitional = isTransitional(app.lifecycle_state);
  // The switch reflects the live (possibly transitional) state: ENABLING reads
  // as on, DISABLING as off, so the user sees the direction of travel.
  const checked = app.lifecycle_state === 'ENABLED' || app.lifecycle_state === 'ENABLING';
  // Toggle only from a terminal state on a toggleable app, and never while a
  // mutation for this row is in flight.
  const locked = !app.toggleable || transitional || busy;
  const chip = STATE_CHIP[app.lifecycle_state];

  return (
    <Box
      data-testid={`app-row-${app.app_key}`}
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 2,
        py: 1.5,
        px: 1,
        borderBottom: 1,
        borderColor: 'divider',
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 500 }}>
          {app.name}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {app.app_key}
        </Typography>
      </Box>

      <Stack direction="row" spacing={1.5} alignItems="center">
        <Chip
          size="small"
          label={chip.label}
          color={chip.color}
          data-testid={`app-state-${app.app_key}`}
        />

        {app.lifecycle_state === 'DISABLING' && (
          <Button
            size="small"
            color="warning"
            variant="outlined"
            disabled={busy}
            onClick={() => onForceDisable(app)}
            data-testid={`app-force-disable-${app.app_key}`}
          >
            Force disable
          </Button>
        )}

        {transitional && <CircularProgress size={18} aria-label="transition in progress" />}

        {!app.toggleable ? (
          <Tooltip title="This app is protected and cannot be disabled.">
            <LockIcon
              fontSize="small"
              color="disabled"
              titleAccess="Protected app, cannot be disabled"
              data-testid={`app-protected-${app.app_key}`}
            />
          </Tooltip>
        ) : (
          <Switch
            checked={checked}
            disabled={locked}
            onChange={() => onToggle(app)}
            inputProps={{ 'aria-label': `${app.name} enabled` }}
          />
        )}
      </Stack>
    </Box>
  );
}

export default function AdminAppsPage() {
  const { isAdmin } = useAuth();
  // Skip fetching for non-admins — the API would 403 and we render a guard state.
  const appsQuery = useAdminApps({ enabled: isAdmin });
  const setAppState = useSetAppState();
  const forceDisable = useForceDisableApp();
  const { showError } = useNotification();
  // Every app key with a transition mutation currently in flight. Tracking all
  // pending mutations (not just the latest) keeps each row locked while its own
  // request runs, even when several apps are toggled concurrently. Called
  // unconditionally — before the admin guard — to keep the hook order stable.
  const pendingKeys = useMutationState({
    filters: { mutationKey: ADMIN_APP_MUTATION_KEY, status: 'pending' },
    select: (mutation) => (mutation.state.variables as { appKey?: string } | undefined)?.appKey,
  });

  if (!isAdmin) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          py: 10,
          textAlign: 'center',
        }}
        data-testid="admin-apps-admins-only"
      >
        <LockIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
        <Typography variant="h5" gutterBottom>
          Admins only
        </Typography>
        <Typography variant="body2" color="text.secondary">
          You need administrator access to manage apps.
        </Typography>
      </Box>
    );
  }

  const handleToggle = (app: AdminApp) => {
    // Derive direction from lifecycle_state (the single source of truth the row
    // also renders from); `enabled` is a derived/deprecated mirror.
    const lifecycleState = app.lifecycle_state === 'ENABLED' ? 'DISABLING' : 'ENABLING';
    setAppState.mutate(
      { appKey: app.app_key, lifecycleState },
      {
        onError: (error) => {
          showError(appStateErrorMessage(error) ?? 'Failed to change app state.');
        },
      },
    );
  };

  const handleForceDisable = (app: AdminApp) => {
    forceDisable.mutate(
      { appKey: app.app_key },
      {
        onError: (error) => {
          showError(appStateErrorMessage(error) ?? 'Failed to force-disable app.');
        },
      },
    );
  };

  const apps = appsQuery.data ?? [];

  return (
    <>
      <Box sx={{ mb: 3 }}>
        <Typography
          variant="h5"
          sx={{ fontFamily: '"Poppins", sans-serif', fontWeight: 500, mb: 0.5 }}
        >
          Apps
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Enable or disable apps at runtime. Disabling drains in-flight work before an app goes
          offline.
        </Typography>
      </Box>

      {appsQuery.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load apps: {appStateErrorMessage(appsQuery.error)}
        </Alert>
      )}

      <LoadableChildren loading={appsQuery.isLoading}>
        {apps.length === 0 ? (
          <Typography variant="body2" color="text.secondary" data-testid="admin-apps-empty">
            No apps are configured.
          </Typography>
        ) : (
          <Box>
            {apps.map((app) => (
              <AppRow
                key={app.app_key}
                app={app}
                onToggle={handleToggle}
                onForceDisable={handleForceDisable}
                busy={pendingKeys.includes(app.app_key)}
              />
            ))}
          </Box>
        )}
      </LoadableChildren>
    </>
  );
}
