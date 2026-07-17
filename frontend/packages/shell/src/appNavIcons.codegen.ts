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
 * Pure resolver mapping a backend ``NavIcon`` key to its icon import.
 *
 * The side-effect-free half of the ``ICON_BY_KEY`` codegen: the thin I/O wrapper
 * ``scripts/gen-icon-map.ts`` reads the ``NavIcon`` vocabulary from the OpenAPI
 * spec and calls ``resolveNavIcon`` per key to emit
 * ``src/generated/appNavIcons.ts``. Kept in ``src/`` so it is type-checked and
 * unit-tested; the wrapper stays outside the typed surface.
 */

/** Non-MUI brand icons, keyed by ``NavIcon`` value; consulted before the MUI transform. */
export const BRAND_ICONS: Record<string, string> = {
  mysql: 'MySqlIcon',
  mongo: 'MongoIcon',
  postgresql: 'PostgreSqlIcon',
};

/** Join a kebab-case ``NavIcon`` key into a single PascalCase token. */
export const pascalCase = (key: string): string =>
  key
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');

/**
 * Resolve a ``NavIcon`` key to its import module and default-binding name.
 *
 * Brand keys route to the ``@percona/percona-ui`` barrel; every other key maps
 * to an ``@mui/icons-material`` subpath (``<Pascal>``) with the conventional
 * ``<Pascal>Icon`` binding.
 */
export function resolveNavIcon(key: string): { module: string; importName: string } {
  if (Object.prototype.hasOwnProperty.call(BRAND_ICONS, key)) {
    return { module: '@percona/percona-ui', importName: BRAND_ICONS[key] };
  }
  const pascal = pascalCase(key);
  return { module: `@mui/icons-material/${pascal}`, importName: `${pascal}Icon` };
}
