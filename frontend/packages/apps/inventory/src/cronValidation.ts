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

// Mirrors the character-class + zero-step check from static/js/cron-validation.js.
// Final semantic validation (range checks) is server-side via croniter.

const CRON_FIELD_COUNT = 5;
const CRON_FIELD_PATTERNS = [
  /^[\d*/,-]+$/, // minute
  /^[\d*/,-]+$/, // hour
  /^[\d*/,\-?LW]+$/i, // day of month
  /^[\d*/,\-A-Z]+$/i, // month
  /^[\d*/,\-A-Z#?L]+$/i, // day of week
];

export function hasValidCronFieldCharacters(expr: string): boolean {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== CRON_FIELD_COUNT) {
    return false;
  }
  return parts.every((part, i) => CRON_FIELD_PATTERNS[i].test(part));
}

export function hasInvalidZeroStep(expr: string): boolean {
  return expr
    .trim()
    .split(/\s+/)
    .some((part) =>
      part.split(',').some((segment) => {
        if (!segment.includes('/')) {
          return false;
        }
        const step = segment.split('/')[1];
        return /^\d+$/.test(step) && Number(step) === 0;
      }),
    );
}

export function isCronExpressionValid(expr: string): boolean {
  if (!expr) {
    return false;
  }
  const trimmed = expr.trim();
  return hasValidCronFieldCharacters(trimmed) && !hasInvalidZeroStep(trimmed);
}
