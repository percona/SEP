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

import { describe, expect, it } from 'vitest';
import { ICON_BY_KEY } from './appNavConfig';

/**
 * The `NavIcon` vocabulary, hand-mirrored from the backend
 * `app.sep.apps.nav_icons` StrEnum. Both this list and `ICON_BY_KEY` are
 * hand-maintained frontend copies; the assertions below only check that the two
 * agree with each other, not that either matches the backend enum. A backend key
 * added to neither still passes, so keeping both in sync with the backend
 * remains a manual step.
 */
const NAV_ICON_KEYS = [
  'assignment',
  'code',
  'support-agent',
  'description',
  'troubleshoot',
  'table-chart',
  'check-circle',
  'mysql',
  'mongo',
  'postgresql',
  'archive',
  'science',
  'bar-chart',
  'account-tree',
] as const;

describe('ICON_BY_KEY', () => {
  it('resolves every NavIcon vocabulary key with no fallback', () => {
    for (const key of NAV_ICON_KEYS) {
      expect(ICON_BY_KEY[key]).toBeDefined();
    }
  });

  it('defines no key outside the NavIcon vocabulary', () => {
    expect(new Set(Object.keys(ICON_BY_KEY))).toEqual(new Set(NAV_ICON_KEYS));
  });
});
