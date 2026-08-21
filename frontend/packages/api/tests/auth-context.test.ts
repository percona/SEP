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
import { UNAUTHENTICATED_SESSION, deriveCanMutate, type AuthSession } from '../src/auth-context';

function session(overrides: Partial<AuthSession> = {}): AuthSession {
  return { ...UNAUTHENTICATED_SESSION, ...overrides };
}

describe('deriveCanMutate', () => {
  it('grants mutation to an administrator', () => {
    expect(deriveCanMutate(session({ isAdmin: true, isAuthenticated: true }))).toBe(true);
  });

  it('withholds mutation from an authenticated non-administrator', () => {
    expect(deriveCanMutate(session({ isAdmin: false, isAuthenticated: true }))).toBe(false);
  });

  it('withholds mutation from a signed-out session', () => {
    expect(deriveCanMutate(UNAUTHENTICATED_SESSION)).toBe(false);
  });

  it('keys on the administrator flag alone, not on authentication', () => {
    // The server resolves a minimum role per route; the UI deliberately keys on
    // the one flag, so widening it stays a single-function change.
    expect(deriveCanMutate(session({ isAdmin: true, isAuthenticated: false }))).toBe(true);
  });
});

describe('UNAUTHENTICATED_SESSION', () => {
  it('is the least-privileged session a missing provider can resolve to', () => {
    expect(UNAUTHENTICATED_SESSION.isAdmin).toBe(false);
    expect(UNAUTHENTICATED_SESSION.isAuthenticated).toBe(false);
    expect(UNAUTHENTICATED_SESSION.user).toBeNull();
    expect(UNAUTHENTICATED_SESSION.accessToken).toBeNull();
  });

  it('is frozen, so a consumer cannot escalate the shared fallback', () => {
    expect(Object.isFrozen(UNAUTHENTICATED_SESSION)).toBe(true);
    expect(() => {
      (UNAUTHENTICATED_SESSION as { isAdmin: boolean }).isAdmin = true;
    }).toThrow();
    expect(UNAUTHENTICATED_SESSION.isAdmin).toBe(false);
  });

  it('resolves its no-op login and logout without throwing', async () => {
    await expect(UNAUTHENTICATED_SESSION.login('u', 'p')).resolves.toBeUndefined();
    await expect(UNAUTHENTICATED_SESSION.logout()).resolves.toBeUndefined();
  });
});
