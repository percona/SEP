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
// Deep import keeps this to the dependency-free coercion util. Locks the wire
// contract the destination combos rely on: dest_db_id / dest_service_id are
// `schema` / `service` types whose `{ id, name }` option unwraps to a scalar id,
// while dest_table_id is an `integer` that does NOT unwrap — which is exactly why
// the Destination Table combo emits a scalar id rather than an option object.
import { coerceFormValues } from '@sep/framework/src/components/SchemaFormRenderer/utils/validationMapper';
import type { PluginField } from '@sep/api';

const DEST_FIELDS = [
  { name: 'dest_table_id', label: 'Destination Table ID', type: 'integer' },
  { name: 'dest_table_name', label: 'Destination Table Name', type: 'string' },
  { name: 'dest_file', label: 'Destination File', type: 'string' },
  { name: 'dest_service_id', label: 'Destination Service', type: 'service' },
  { name: 'dest_host', label: 'Destination Host', type: 'string' },
  { name: 'dest_port', label: 'Destination Port', type: 'integer' },
  { name: 'dest_db_id', label: 'Destination Schema', type: 'schema' },
  { name: 'dest_db_name', label: 'Destination Schema Name', type: 'string' },
] as unknown as PluginField[];

describe('archives destination payload coercion', () => {
  it('keeps the scalar Destination Table id and unwraps schema/service options', () => {
    const out = coerceFormValues(
      {
        dest_table_id: 9,
        dest_table_name: '',
        dest_file: '',
        dest_service_id: { id: 4, name: 'destsvc' },
        dest_host: '',
        dest_port: '',
        dest_db_id: { id: 5, name: 'orders' },
        dest_db_name: '',
      },
      DEST_FIELDS,
    );

    // Integer field: the combo already emitted the scalar id, so it survives.
    expect(out.dest_table_id).toBe(9);
    // schema / service fields unwrap their option object to the scalar id.
    expect(out.dest_db_id).toBe(5);
    expect(out.dest_service_id).toBe(4);
    expect(out.dest_port).toBeUndefined();
  });

  it('keeps typed names and drops empty ids in the manual path', () => {
    const out = coerceFormValues(
      {
        dest_table_id: '',
        dest_table_name: 'archived_rows',
        dest_file: '',
        dest_service_id: '',
        dest_host: 'db2.example.com',
        dest_port: '3307',
        dest_db_id: '',
        dest_db_name: 'archive_db',
      },
      DEST_FIELDS,
    );

    expect(out.dest_table_id).toBeUndefined();
    expect(out.dest_db_id).toBeUndefined();
    expect(out.dest_service_id).toBeUndefined();
    expect(out.dest_table_name).toBe('archived_rows');
    expect(out.dest_db_name).toBe('archive_db');
    expect(out.dest_host).toBe('db2.example.com');
    expect(out.dest_port).toBe(3307);
  });

  it('passes a destination file through and drops the table fields', () => {
    const out = coerceFormValues(
      {
        dest_table_id: '',
        dest_table_name: '',
        dest_file: '/tmp/archive.csv',
        dest_service_id: '',
        dest_host: '',
        dest_port: '',
        dest_db_id: '',
        dest_db_name: '',
      },
      DEST_FIELDS,
    );

    expect(out.dest_file).toBe('/tmp/archive.csv');
    expect(out.dest_table_id).toBeUndefined();
    expect(out.dest_db_id).toBeUndefined();
    expect(out.dest_service_id).toBeUndefined();
  });
});
