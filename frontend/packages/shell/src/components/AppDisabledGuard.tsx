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

import type { ReactNode } from 'react';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { useEnabledApps } from '@sep/api';
import AppDisabledPage from '../pages/AppDisabledPage';

interface AppDisabledGuardProps {
  /** Backend app key (the last dotted segment of the app's MODULE_NAME). */
  appKey: string;
  children: ReactNode;
}

/**
 * Gate an app-owned route on its runtime enabled state.
 *
 * Consults the same `GET /api/apps/` query that drives sidebar filtering. When
 * the matching app is explicitly disabled, the `AppDisabledPage` splash renders
 * *instead of* `children` — so the wrapped app never mounts and no 503-prone
 * API calls fire.
 *
 * On a cold load (bookmark / email link / hard reload) the query has no cached
 * data, so we hold a brief spinner until it resolves rather than optimistically
 * mounting the app. Optimistic render would race `/api/apps/` against the
 * lazy app chunk + its first API call, making the very 503 cascade this
 * guard exists to prevent nondeterministic. Gating on `isLoading` keeps the
 * disabled-URL outcome deterministic; the spinner only appears on the first
 * uncached fetch (a warm cache decides instantly).
 *
 * Fail-open on error is intentional and distinct from loading: if the query
 * errors, `children` render. A backend hiccup on `/api/apps/` must not turn
 * every app into a splash; the existing 503-toast behaviour is strictly less
 * broken than that. An app key absent from a successful response also fails
 * open.
 */
export default function AppDisabledGuard({ appKey, children }: AppDisabledGuardProps) {
  const { data: apps, isLoading, isError } = useEnabledApps();

  // Fail open on error even when React Query is still holding stale data from a
  // prior successful fetch — a failed refetch must never strand the user on the
  // splash (matches the JSDoc contract above). Checked before `isLoading` so an
  // errored query never blocks on the spinner.
  if (isError) {
    return <>{children}</>;
  }

  // Cold load with no cached data yet: hold a spinner so the disabled-URL
  // outcome is deterministic instead of racing the app mount.
  if (isLoading) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          py: 10,
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  const app = apps?.find((a) => a.app_key === appKey);
  if (app && !app.enabled) {
    // Drop an unmappable key so a raw app key never reaches the UI; if none map
    // (e.g. self-disabled, so no blockers) the splash stays generic.
    const nameByKey = new Map((apps ?? []).map((a) => [a.app_key, a.display_name]));
    const blockingDependencyNames = (app.blocking_dependencies ?? [])
      .map((key) => nameByKey.get(key))
      .filter((name): name is string => name !== undefined);
    return (
      <AppDisabledPage
        appDisplayName={app.display_name}
        blockingDependencyNames={blockingDependencyNames}
      />
    );
  }

  return <>{children}</>;
}
