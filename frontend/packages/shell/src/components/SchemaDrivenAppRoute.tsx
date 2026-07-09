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

import { SchemaDrivenApp } from '@sep/framework';
import { getAppRouteMeta } from '../appNavConfig';

interface SchemaDrivenAppRouteProps {
  /** Backend app module key (``GET /api/apps/`` ``app_key``). */
  appKey: string;
}

/**
 * Generic shell route for schema-driven apps without a bespoke React package.
 *
 * ``routeBase`` comes from ``appNavConfig`` when the app is not mounted
 * under the default ``/apps/{appKey}`` prefix. The derived schema now drives
 * every form (including archives' one-of groups and free-solo references), so
 * no per-app create/edit form override is injected here.
 */
export function SchemaDrivenAppRoute({ appKey }: SchemaDrivenAppRouteProps) {
  const meta = getAppRouteMeta(appKey);

  return <SchemaDrivenApp pluginName={appKey} routeBase={meta?.routeBase} />;
}
