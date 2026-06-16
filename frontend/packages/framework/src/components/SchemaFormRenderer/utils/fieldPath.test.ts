/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { describe, expect, it } from 'vitest';

import { getAtPath, setAtPath } from './fieldPath';

describe('fieldPath', () => {
  it('reads and writes nested dotted paths', () => {
    const values: Record<string, unknown> = {};
    setAtPath(values, 'source.mode', 'schema');
    setAtPath(values, 'source.source_db_id', 'inventory');

    expect(getAtPath(values, 'source.mode')).toBe('schema');
    expect(getAtPath(values, 'source.source_db_id')).toBe('inventory');
    expect(values).toEqual({
      source: { mode: 'schema', source_db_id: 'inventory' },
    });
  });

  it('reads nested values from caller default payloads', () => {
    const values = {
      source: { mode: 'query', source_query: 'SELECT 1' },
    };
    expect(getAtPath(values, 'source.source_query')).toBe('SELECT 1');
  });
});
