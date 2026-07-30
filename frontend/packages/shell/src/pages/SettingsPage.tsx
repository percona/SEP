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

import { useMemo, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import DownloadIcon from '@mui/icons-material/Download';
import LockIcon from '@mui/icons-material/Lock';
import { LoadableChildren } from '@percona/percona-ui';
import { useConfigExport, useSettingsList } from '@sep/api';

import { useAuth } from '../contexts/auth';
import SettingsGroup from '../components/settings/SettingsGroup';
import TestConnectionButton from '../components/settings/TestConnectionButton';
import SettingsSearchBar from '../components/settings/SettingsSearchBar';
import {
  DEFAULT_SETTINGS_FILTERS,
  appLabelFor,
  filterSettingsGroups,
  partitionSettingsGroups,
} from '../components/settings/filters';

export default function SettingsPage() {
  const { isAdmin } = useAuth();
  // Skip fetching for non-admins — the API would 403 and we render a guard state.
  const settingsQuery = useSettingsList({ enabled: isAdmin });
  const configExport = useConfigExport();
  const [filters, setFilters] = useState(DEFAULT_SETTINGS_FILTERS);

  const allGroups = useMemo(() => settingsQuery.data ?? [], [settingsQuery.data]);
  // Only offer classes the page can actually render: disabled app-owned groups
  // are hidden, so their classes must not surface in the Class filter either
  // (selecting one would otherwise dead-end in the empty state).
  const settingClasses = useMemo(() => {
    const { core, appOwned } = partitionSettingsGroups(allGroups);
    return [...core, ...appOwned].map((group) => group.setting_class);
  }, [allGroups]);
  const visibleGroups = useMemo(
    () => filterSettingsGroups(allGroups, filters),
    [allGroups, filters],
  );
  const { core: coreGroups, appOwned: appGroups } = useMemo(
    () => partitionSettingsGroups(visibleGroups),
    [visibleGroups],
  );
  const searchActive = filters.search.trim() !== '';

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
        data-testid="settings-admins-only"
      >
        <LockIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
        <Typography variant="h5" gutterBottom>
          Admins only
        </Typography>
        <Typography variant="body2" color="text.secondary">
          You need administrator access to view and edit application settings.
        </Typography>
      </Box>
    );
  }

  return (
    <>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 2,
          mb: 3,
        }}
      >
        <Box>
          <Typography
            variant="h5"
            sx={{ fontFamily: '"Poppins", sans-serif', fontWeight: 500, mb: 0.5 }}
          >
            Settings
          </Typography>
          <Typography variant="body2" color="text.secondary">
            View and edit application configuration at runtime.
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
          <TestConnectionButton />
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={() => configExport.mutate()}
            disabled={configExport.isPending}
          >
            {configExport.isPending ? 'Downloading…' : 'Download YAML'}
          </Button>
        </Box>
      </Box>

      {configExport.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to export configuration: {configExport.error?.message}
        </Alert>
      )}

      {settingsQuery.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load settings: {settingsQuery.error?.message}
        </Alert>
      )}

      <SettingsSearchBar filters={filters} onChange={setFilters} settingClasses={settingClasses} />

      <LoadableChildren loading={settingsQuery.isLoading}>
        {coreGroups.length === 0 && appGroups.length === 0 ? (
          <Typography variant="body2" color="text.secondary" data-testid="settings-empty">
            No settings match the current filters.
          </Typography>
        ) : (
          <>
            {coreGroups.map((group) => (
              <SettingsGroup
                key={group.setting_class}
                settingClass={group.setting_class}
                settings={group.settings}
                searchActive={searchActive}
              />
            ))}

            {appGroups.length > 0 && (
              <Box data-testid="app-settings-region" sx={{ mt: coreGroups.length > 0 ? 4 : 0 }}>
                <Typography
                  variant="subtitle1"
                  sx={{ fontFamily: '"Poppins", sans-serif', fontWeight: 500, mb: 1.5 }}
                >
                  App settings
                </Typography>
                {appGroups.map((group) => (
                  <SettingsGroup
                    key={group.setting_class}
                    settingClass={group.setting_class}
                    settings={group.settings}
                    searchActive={searchActive}
                    appLabel={appLabelFor(group)}
                  />
                ))}
              </Box>
            )}
          </>
        )}
      </LoadableChildren>
    </>
  );
}
