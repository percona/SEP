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

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { MongoIcon, MySqlIcon, PostgreSqlIcon } from '@percona/percona-ui';
import { ICON_BY_KEY } from './appNavIcons';

const SPEC_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../api/specs/sep.json',
);
const NAV_ICON_KEYS: string[] = JSON.parse(readFileSync(SPEC_PATH, 'utf8')).components.schemas
  .nav_icons__NavIcon.enum;

describe('generated ICON_BY_KEY', () => {
  it('covers exactly the NavIcon vocabulary from the spec', () => {
    expect(new Set(Object.keys(ICON_BY_KEY))).toEqual(new Set(NAV_ICON_KEYS));
  });

  it('resolves every vocabulary key to a defined component', () => {
    for (const key of NAV_ICON_KEYS) {
      expect(ICON_BY_KEY[key as keyof typeof ICON_BY_KEY]).toBeDefined();
    }
  });

  it('maps the brand keys to their @percona/percona-ui components', () => {
    expect(ICON_BY_KEY.mysql).toBe(MySqlIcon);
    expect(ICON_BY_KEY.mongo).toBe(MongoIcon);
    expect(ICON_BY_KEY.postgresql).toBe(PostgreSqlIcon);
  });
});
