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

import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { Route, Routes, useLocation } from 'react-router-dom';
import { SchemaDrivenApp } from '@sep/framework';
import { useEnabledApps, type EnabledApp } from '@sep/api';
import { toRoutePattern } from '../appNavConfig';
import { isCustomApp } from '../appRegistry';
import { wrapAppRoute } from '../appRouteGuard';
import NotFoundPage from '../pages/NotFoundPage';

interface ResolvedApp {
  appKey: string;
  reactRoute: string;
}

/** Strip trailing slashes while preserving the leading ``/`` (``/apps/x/`` → ``/apps/x``). */
function stripTrailingSlash(path: string): string {
  const stripped = path.replace(/\/+$/, '');
  return stripped.length > 0 ? stripped : '/';
}

/**
 * Resolve which schema-driven app owns ``pathname`` from the ``/api/apps`` list.
 *
 * The candidate set is **enabled-agnostic** — a disabled app still resolves, so
 * it reaches ``AppDisabledGuard``'s splash instead of a 404. Custom-UI apps
 * (their bespoke static routes already outrank this resolver's ``*``) and nested
 * sub-app keys are excluded; among the rest, the app whose ``react_route`` is the
 * longest full-segment prefix of ``pathname`` wins. Both sides are compared with
 * trailing slashes stripped, since ``URIPath`` permits a configured route like
 * ``/apps/x/`` that would otherwise fail to match a slashless deep link.
 */
export function resolveSchemaApp(pathname: string, apps: EnabledApp[]): ResolvedApp | null {
  const normalizedPath = stripTrailingSlash(pathname);
  let best: ResolvedApp | null = null;
  for (const app of apps) {
    if (isCustomApp(app.app_key) || app.app_key.includes('/')) {
      continue;
    }
    const reactRoute = stripTrailingSlash(app.react_route);
    const matches = normalizedPath === reactRoute || normalizedPath.startsWith(`${reactRoute}/`);
    if (matches && (best === null || reactRoute.length > best.reactRoute.length)) {
      best = { appKey: app.app_key, reactRoute };
    }
  }
  return best;
}

/**
 * Extract ``{appKey, reactRoute}`` for a default ``/apps/<id>`` path, else null.
 *
 * The error-only fallback used when the listing is unavailable: the default
 * convention encodes the app key in the URL, so a default deep link stays
 * routable without the listing. A deviating route cannot be mapped this way.
 */
export function matchDefaultAppsPath(pathname: string): ResolvedApp | null {
  const match = /^\/apps\/([^/]+)/.exec(pathname);
  if (match === null) {
    return null;
  }
  const appKey = match[1];
  return { appKey, reactRoute: `/apps/${appKey}` };
}

function renderResolved({ appKey, reactRoute }: ResolvedApp) {
  return (
    <Routes>
      <Route
        path={toRoutePattern(reactRoute)}
        element={wrapAppRoute(
          appKey,
          <SchemaDrivenApp pluginName={appKey} routeBase={reactRoute} />,
        )}
      />
    </Routes>
  );
}

/**
 * Terminal ``*`` route that mounts the schema-driven app owning the current path.
 *
 * A single static route (matches immediately, so a cold deep link is never a
 * 404) that defers only *which* app owns the path to render time, when
 * ``useEnabledApps`` has the listing. On a cold uncached load it holds a brief
 * spinner rather than optimistically mounting — matching ``AppDisabledGuard``'s
 * documented anti-race policy. The resolved app is wrapped in that same guard,
 * so a disabled app renders its splash (not NotFound). If the listing errors it
 * fails open for the default ``/apps/<id>`` convention; an unmappable deviating
 * path and any unmatched path render ``NotFoundPage``.
 */
export function SchemaDrivenAppResolver() {
  const { pathname } = useLocation();
  const { data: apps, isLoading } = useEnabledApps();

  if (!apps) {
    if (isLoading) {
      return (
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', py: 10 }}>
          <CircularProgress />
        </Box>
      );
    }
    const structural = matchDefaultAppsPath(pathname);
    return structural ? renderResolved(structural) : <NotFoundPage />;
  }

  const resolved = resolveSchemaApp(pathname, apps);
  return resolved ? renderResolved(resolved) : <NotFoundPage />;
}
