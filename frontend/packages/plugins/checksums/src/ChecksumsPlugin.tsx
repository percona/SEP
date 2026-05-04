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
import { checksumsSchema } from './schema';
import { mockChecksumTasks } from './mock-data';

/**
 * Checksums plugin — zero custom UI code.
 *
 * The SchemaDrivenPlugin reads the schema and auto-generates:
 * - List page with sortable/filterable table
 * - Create page with auto-generated form
 * - Detail page showing task data
 *
 * Once the backend serves the schema at /api/plugins/checksums/schema,
 * remove mockSchema and mockTasks — the framework fetches everything.
 */
export function ChecksumsPlugin() {
  return (
    <SchemaDrivenPlugin
      pluginName="checksums"
      mockSchema={checksumsSchema}
      mockTasks={[...mockChecksumTasks]}
    />
  );
}
