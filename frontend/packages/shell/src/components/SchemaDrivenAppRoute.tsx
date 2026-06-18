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

import { SchemaDrivenPlugin } from '@sep/framework';
import { getAppRouteMeta } from '../appNavConfig';
import { ArchiveForm } from './ArchiveForm';

interface SchemaDrivenAppRouteProps {
  /** Backend plugin module key (``GET /api/apps/`` ``app_key``). */
  appKey: string;
}

/**
 * Generic shell route for schema-driven apps without a bespoke React package.
 *
 * ``routeBase`` comes from ``appNavConfig`` when the plugin is not mounted
 * under the default ``/plugins/{appKey}`` prefix. Archives keeps its custom
 * create/edit form slots here instead of a separate ``@sep/plugin-archives``
 * package.
 */
export function SchemaDrivenAppRoute({ appKey }: SchemaDrivenAppRouteProps) {
  const meta = getAppRouteMeta(appKey);
  const archiveFormSlots =
    appKey === 'archives'
      ? {
          renderCreateForm: (props) => <ArchiveForm {...props} submitLabel="Create Archives" />,
          renderEditForm: (props) => <ArchiveForm {...props} submitLabel="Save Archives" />,
        }
      : {};

  return (
    <SchemaDrivenPlugin pluginName={appKey} routeBase={meta?.routeBase} {...archiveFormSlots} />
  );
}
