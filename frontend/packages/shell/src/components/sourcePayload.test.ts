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
// Deep import keeps this to the (dependency-free) coercion util rather than the
// whole framework barrel. This locks the contract that ArchiveSchemaCombo relies
// on: an inventory pick stored as a `{ id, name }` option unwraps to the scalar
// wire id on submit, so the backend keeps receiving source_db_id / source_table_id
// as ints and validators 5a/5b stay authoritative.
import { coerceFormValues } from '@sep/framework/src/components/SchemaFormRenderer/utils/validationMapper';
import type { PluginField } from '@sep/api';

const SOURCE_FIELDS = [
  { name: 'source_db_id', label: 'Source Schema', type: 'schema', depends_on: 'service_id' },
  { name: 'source_db_name', label: 'Source Schema Name', type: 'string' },
  { name: 'source_table_id', label: 'Source Table', type: 'table', depends_on: 'source_db_id' },
  { name: 'source_table_name', label: 'Source Table Name', type: 'string' },
  { name: 'source_query', label: 'Source Query', type: 'string' },
] as unknown as PluginField[];

describe('archives source payload coercion', () => {
  it('unwraps picked inventory options to scalar ids', () => {
    const out = coerceFormValues(
      {
        source_db_id: { id: 5, name: 'orders' },
        source_db_name: '',
        source_table_id: { id: 9, name: 'line_items' },
        source_table_name: '',
        source_query: '',
      },
      SOURCE_FIELDS,
    );

    expect(out.source_db_id).toBe(5);
    expect(out.source_table_id).toBe(9);
    expect(out.source_db_name).toBe('');
    expect(out.source_table_name).toBe('');
  });

  it('keeps typed names and drops empty ids', () => {
    const out = coerceFormValues(
      {
        source_db_id: '',
        source_db_name: 'orders',
        source_table_id: '',
        source_table_name: 'line_items',
        source_query: '',
      },
      SOURCE_FIELDS,
    );

    expect(out.source_db_id).toBeUndefined();
    expect(out.source_table_id).toBeUndefined();
    expect(out.source_db_name).toBe('orders');
    expect(out.source_table_name).toBe('line_items');
  });

  it('passes the query through untouched in query mode', () => {
    const out = coerceFormValues(
      {
        source_db_id: '',
        source_db_name: '',
        source_table_id: '',
        source_table_name: '',
        source_query: 'SELECT * FROM orders WHERE id < 100',
      },
      SOURCE_FIELDS,
    );

    expect(out.source_query).toBe('SELECT * FROM orders WHERE id < 100');
    expect(out.source_db_id).toBeUndefined();
    expect(out.source_table_id).toBeUndefined();
  });
});
