/**
 * Extract a numeric id from a value that may be:
 *   - a finite number (returned as-is),
 *   - a numeric string (parsed),
 *   - an option object with an `id` field (recursively extracted),
 *   - or anything else (returns `null`).
 *
 * Used by the cascading selectors to handle parent values that may come from
 * either an upstream selector (object form) or a persisted form default
 * (scalar form, possibly stringified).
 */
export function extractId(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  if (value && typeof value === 'object' && 'id' in value) {
    return extractId((value as { id: unknown }).id);
  }
  return null;
}
