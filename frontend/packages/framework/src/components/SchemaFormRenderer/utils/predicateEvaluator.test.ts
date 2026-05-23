/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { describe, expect, it } from 'vitest';

import { evaluatePredicate, getGateFieldNames } from './predicateEvaluator';

describe('evaluatePredicate – contains', () => {
  it('returns true when the value is in the array', () => {
    expect(evaluatePredicate({ contains: { upload: 's3' } }, { upload: ['s3', 'rsync'] })).toBe(
      true,
    );
  });

  it('returns false when the value is not in the array', () => {
    expect(evaluatePredicate({ contains: { upload: 's3' } }, { upload: ['rsync'] })).toBe(false);
  });

  it('returns false when the container is undefined / null', () => {
    expect(evaluatePredicate({ contains: { upload: 's3' } }, {})).toBe(false);
    expect(evaluatePredicate({ contains: { upload: 's3' } }, { upload: null })).toBe(false);
  });

  it('returns false when the container is empty', () => {
    expect(evaluatePredicate({ contains: { upload: 's3' } }, { upload: [] })).toBe(false);
  });

  it('returns false when the container is not an array', () => {
    expect(evaluatePredicate({ contains: { upload: 's3' } }, { upload: 's3' })).toBe(false);
    expect(evaluatePredicate({ contains: { upload: 1 } }, { upload: 42 })).toBe(false);
  });

  it('supports a $field reference on the right-hand side', () => {
    expect(
      evaluatePredicate(
        { contains: { upload: { $field: 'wanted' } } },
        { upload: ['s3', 'rsync'], wanted: 'rsync' },
      ),
    ).toBe(true);
    expect(
      evaluatePredicate(
        { contains: { upload: { $field: 'wanted' } } },
        { upload: ['s3'], wanted: 'rsync' },
      ),
    ).toBe(false);
  });

  it('contributes its field name to getGateFieldNames', () => {
    expect(getGateFieldNames([{ when: { contains: { upload: 's3' } } }])).toEqual(['upload']);
  });
});
