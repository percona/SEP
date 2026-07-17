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
import { BRAND_ICONS, pascalCase, resolveNavIcon } from './appNavIcons.codegen';

const SPEC_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../api/specs/sep.json',
);
const NAV_ICON_KEYS: string[] = JSON.parse(readFileSync(SPEC_PATH, 'utf8')).components.schemas
  .nav_icons__NavIcon.enum;

describe('pascalCase', () => {
  it('joins kebab segments into a single PascalCase token', () => {
    expect(pascalCase('support-agent')).toBe('SupportAgent');
    expect(pascalCase('bar-chart')).toBe('BarChart');
    expect(pascalCase('code')).toBe('Code');
  });
});

describe('resolveNavIcon', () => {
  it('brands exactly the three non-MUI keys', () => {
    expect(Object.keys(BRAND_ICONS).sort()).toEqual(['mongo', 'mysql', 'postgresql']);
  });

  it('routes brand keys to the @percona/percona-ui barrel', () => {
    expect(resolveNavIcon('mysql')).toEqual({
      module: '@percona/percona-ui',
      importName: 'MySqlIcon',
    });
    expect(resolveNavIcon('mongo')).toEqual({
      module: '@percona/percona-ui',
      importName: 'MongoIcon',
    });
    expect(resolveNavIcon('postgresql')).toEqual({
      module: '@percona/percona-ui',
      importName: 'PostgreSqlIcon',
    });
  });

  it('routes non-brand keys to the MUI subpath with an Icon binding', () => {
    expect(resolveNavIcon('support-agent')).toEqual({
      module: '@mui/icons-material/SupportAgent',
      importName: 'SupportAgentIcon',
    });
    expect(resolveNavIcon('code')).toEqual({
      module: '@mui/icons-material/Code',
      importName: 'CodeIcon',
    });
  });

  it('does not treat inherited Object.prototype keys as brand keys', () => {
    const resolved = resolveNavIcon('toString');
    expect(resolved.module).not.toBe('@percona/percona-ui');
    expect(typeof resolved.importName).toBe('string');
  });

  it('resolves every NavIcon vocabulary key to an import source', () => {
    for (const key of NAV_ICON_KEYS) {
      const resolved = resolveNavIcon(key);
      expect(resolved.module).toBeTruthy();
      expect(resolved.importName).toBeTruthy();
    }
  });
});
