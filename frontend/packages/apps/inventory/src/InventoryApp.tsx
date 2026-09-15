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
 * Inventory app — no browser surface.
 *
 * PMM owns the embedded inventory UI and the SEP shell no longer links here.
 * The retained endpoints under ``/api/apps/inventory/`` are operator API
 * surfaces: scheduled sync is the normal refresh path, and ad-hoc sync and
 * connectivity probes are direct API calls. The package survives as a husk so
 * the shell's lazy import keeps resolving.
 */
export function InventoryApp() {
  return null;
}
