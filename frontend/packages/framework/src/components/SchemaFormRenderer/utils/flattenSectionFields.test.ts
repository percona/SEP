/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { describe, expect, it } from 'vitest';

import type { FormSection } from '@sep/api';

import {
  flattenSectionFields,
  flattenSectionItem,
  isOneOfGroup,
  buildFieldLabelMap,
} from './flattenSectionFields';

const ONE_OF_SECTION: FormSection[] = [
  {
    title: 'Source',
    fields: [
      {
        type: 'one_of',
        name: 'source',
        label: 'Source',
        discriminator: 'source.mode',
        default: 'schema',
        branches: [
          {
            value: 'schema',
            label: 'Schema',
            fields: [{ type: 'string', name: 'source.source_db_id', label: 'Schema' }],
          },
          {
            value: 'query',
            label: 'Query',
            fields: [{ type: 'string', name: 'source.source_query', label: 'Query' }],
          },
        ],
      },
    ],
  },
];

describe('isOneOfGroup', () => {
  it('detects one_of containers', () => {
    const field = ONE_OF_SECTION[0].fields[0];
    expect(isOneOfGroup(field)).toBe(true);
  });

  it('returns false for leaf fields', () => {
    expect(isOneOfGroup({ type: 'string', name: 'x', label: 'X' })).toBe(false);
  });
});

describe('flattenSectionFields', () => {
  it('expands one-of branches into leaf fields', () => {
    const names = flattenSectionFields(ONE_OF_SECTION).map((field) => field.name);
    expect(names).toEqual(['source.source_db_id', 'source.source_query']);
  });

  it('passes through plain leaf sections unchanged', () => {
    const sections: FormSection[] = [
      {
        title: 'T',
        fields: [{ type: 'string', name: 'title', label: 'Title' }],
      },
    ];
    expect(flattenSectionItem(sections[0].fields[0])).toEqual([
      { type: 'string', name: 'title', label: 'Title' },
    ]);
  });
});

describe('buildFieldLabelMap', () => {
  it('maps each flattened field path to its label, falling back to the name', () => {
    const sections: FormSection[] = [
      {
        title: 'T',
        fields: [
          { type: 'string', name: 'task_name', label: 'Task Name' },
          { type: 'integer', name: 'limit', label: '' },
        ],
      },
    ];
    const labels = buildFieldLabelMap(sections);
    expect(labels.get('task_name')).toBe('Task Name');
    expect(labels.get('limit')).toBe('limit');
  });

  it('includes one-of branch leaf paths', () => {
    const labels = buildFieldLabelMap(ONE_OF_SECTION);
    expect(labels.get('source.source_db_id')).toBe('Schema');
    expect(labels.get('source.source_query')).toBe('Query');
  });
});
