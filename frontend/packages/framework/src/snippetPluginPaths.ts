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

/**
 * Snippets plugin JSON API path prefix (axios `apiClient` uses base `/api`).
 *
 * Encoding the filename in the path still carries SEP-1128 routing caveats
 * (e.g. `%2F` in segment-oriented stacks); a query-param or opaque id contract
 * would replace these builders when that lands server-side.
 */
export const SNIPPETS_PLUGINS_API_BASE = '/plugins/snippets';

/** Path for `GET` per-snippet plugin schema (filename is the snippet path key). */
export function snippetPluginSchemaPath(filename: string): string {
  return `${SNIPPETS_PLUGINS_API_BASE}/${encodeURIComponent(filename)}/schema`;
}

/** Path for `POST` snippet execution. */
export function snippetPluginExecutePath(filename: string): string {
  return `${SNIPPETS_PLUGINS_API_BASE}/${encodeURIComponent(filename)}/execute`;
}
