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
import {
  hasValidCronFieldCharacters,
  hasInvalidZeroStep,
  isCronExpressionValid,
} from './cronValidation';

describe('hasValidCronFieldCharacters', () => {
  it('accepts a valid 5-field expression', () => {
    expect(hasValidCronFieldCharacters('*/5 * * * *')).toBe(true);
    expect(hasValidCronFieldCharacters('0 6 * * 1-5')).toBe(true);
    expect(hasValidCronFieldCharacters('0 0 1,15 * *')).toBe(true);
  });

  it('rejects fewer than 5 fields', () => {
    expect(hasValidCronFieldCharacters('* * * *')).toBe(false);
  });

  it('rejects more than 5 fields', () => {
    expect(hasValidCronFieldCharacters('* * * * * *')).toBe(false);
  });

  it('accepts day-of-month LW characters', () => {
    expect(hasValidCronFieldCharacters('0 0 L * *')).toBe(true);
    expect(hasValidCronFieldCharacters('0 0 15W * *')).toBe(true);
  });

  it('accepts month names (case-insensitive)', () => {
    expect(hasValidCronFieldCharacters('0 0 * JAN *')).toBe(true);
    expect(hasValidCronFieldCharacters('0 0 * jan *')).toBe(true);
  });

  it('accepts day-of-week hash and question-mark', () => {
    expect(hasValidCronFieldCharacters('0 0 * * 2#3')).toBe(true);
    expect(hasValidCronFieldCharacters('0 0 ? * ?')).toBe(true);
  });

  it('rejects invalid characters in minute field', () => {
    expect(hasValidCronFieldCharacters('abc * * * *')).toBe(false);
  });

  it('rejects invalid characters in hour field', () => {
    expect(hasValidCronFieldCharacters('0 abc * * *')).toBe(false);
  });
});

describe('hasInvalidZeroStep', () => {
  it('returns false for expressions without steps', () => {
    expect(hasInvalidZeroStep('* * * * *')).toBe(false);
    expect(hasInvalidZeroStep('0 6 1 1 1')).toBe(false);
  });

  it('returns false for valid step values', () => {
    expect(hasInvalidZeroStep('*/5 * * * *')).toBe(false);
    expect(hasInvalidZeroStep('0-59/2 * * * *')).toBe(false);
  });

  it('returns true for step /0', () => {
    expect(hasInvalidZeroStep('*/0 * * * *')).toBe(true);
    expect(hasInvalidZeroStep('0 */0 * * *')).toBe(true);
  });

  it('does not flag non-numeric step tokens', () => {
    // non-numeric step like /A should not be treated as zero
    expect(hasInvalidZeroStep('*/A * * * *')).toBe(false);
  });
});

describe('isCronExpressionValid', () => {
  it('returns false for empty string', () => {
    expect(isCronExpressionValid('')).toBe(false);
  });

  it('returns true for a valid expression', () => {
    expect(isCronExpressionValid('*/5 * * * *')).toBe(true);
    expect(isCronExpressionValid('0 6 * * 1-5')).toBe(true);
  });

  it('returns false for wrong field count', () => {
    expect(isCronExpressionValid('* * *')).toBe(false);
    expect(isCronExpressionValid('* * * * * *')).toBe(false);
  });

  it('returns false for zero step', () => {
    expect(isCronExpressionValid('*/0 * * * *')).toBe(false);
  });

  it('returns false for invalid characters', () => {
    expect(isCronExpressionValid('not-a-cron')).toBe(false);
  });

  it('trims surrounding whitespace before checking', () => {
    expect(isCronExpressionValid('  */5 * * * *  ')).toBe(true);
  });
});
