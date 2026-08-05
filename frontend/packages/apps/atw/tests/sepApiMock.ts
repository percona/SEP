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
 * The non-client `@sep/api` exports `src/hooks.ts` binds at import time.
 *
 * Any test that mocks `@sep/api` must supply these too, or importing the hooks
 * module fails on the missing named exports before a single test runs. Spread
 * into the mock factory alongside the file's own `apiClient` stub.
 */
export const sepApiListStubs = {
  DEFAULT_APP_LIST_LIMIT: 50,
  /**
   * The real helper's two live branches: a bare array (no pagination) and a
   * full `{ items, total, offset, limit }` envelope. Its legacy `{ items }`-only
   * branch is left out on purpose — no ATW route returns that shape, and a test
   * fixture that did would be describing an endpoint contract that does not hold.
   */
  normalizeAppListResponse: <T>(
    data: T[] | { items: T[]; total: number; offset: number; limit: number },
  ) => {
    if (Array.isArray(data)) {
      return { items: data, pagination: null };
    }
    return {
      items: data.items,
      pagination: { total: data.total, offset: data.offset, limit: data.limit },
    };
  },
};
