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
 * @sep/inventory — Inventory app entry point.
 *
 * Exports:
 * - InventoryApp: inventory-specific nested routes and drill-down UI.
 */

export { InventoryApp } from './InventoryApp';
export type { InventoryAppProps } from './InventoryApp';
export { InventoryBreadcrumbs, renderInventoryDetailChildren } from './InventoryAppNavigation';
export {
  inventoryMountPrefix,
  parseFlatInventoryRoute,
  parseNestedInventoryPath,
  parseInventoryRoute,
  pathThroughPairIndex,
  pathToNestedInventoryParent,
} from './inventoryNestedPaths';
