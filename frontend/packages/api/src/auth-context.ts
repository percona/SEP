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

import { createContext, useContext, useMemo } from 'react';
import type { User } from './types/api';

/**
 * Session state owned by the shell's ``AuthProvider``.
 *
 * The context lives here, at the root of the frontend dependency graph, so the
 * framework and every app package can read it — they all depend on ``@sep/api``
 * and none of them may depend on ``@sep/shell``. The provider itself, and all
 * token/session bookkeeping, stays in the shell.
 *
 * One context carries both the session and the capability derived from it, so a
 * silent-refresh token rotation re-renders every capability consumer too. That
 * is a handful of controls every few minutes; splitting the capability into its
 * own context is the fix if it ever costs more than it saves.
 */
export interface AuthSession {
  user: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  /**
   * Administrator identity. Read this only for genuinely admin-only surfaces
   * (the shell's Settings / Admin Apps pages and their query suppression). Per-app
   * write controls gate on {@link AuthState.canMutate} instead.
   */
  isAdmin: boolean;
  /** true during initial session bootstrap & during login */
  loading: boolean;
  /** true after the initial session check finishes (success or failure) */
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

/** {@link AuthSession} plus the capabilities derived from it. */
export interface AuthState extends AuthSession {
  /**
   * Whether this session may mutate: the gate every per-app create / execute /
   * stop / retry / delete control reads.
   *
   * Semantically distinct from {@link AuthSession.isAdmin} even though it is
   * exactly that today. The server already resolves a minimum role per route
   * rather than one administrator flag, and ``User`` carries that role, so
   * widening the UI to match is an edit to {@link deriveCanMutate} —
   * per-control minimum roles — and to no call site.
   */
  canMutate: boolean;
}

/**
 * Single derivation of "may this session mutate?" from session state.
 *
 * Deliberately the administrator flag and nothing finer: most unsafe routes
 * require ``admin``, so keying on a lesser role here would put back the
 * controls that answer 403. Widening this to a per-control minimum role is the
 * follow-up that {@link AuthState.canMutate} describes.
 */
export function deriveCanMutate(session: AuthSession): boolean {
  return session.isAdmin;
}

/**
 * Resolved state for a consumer rendered outside an ``AuthProvider``: signed
 * out, non-admin, and therefore unable to mutate. Tests and Storybook renders
 * mount framework/app components without the shell's provider, so a missing
 * provider must degrade to the least-privileged state rather than throw.
 */
export const UNAUTHENTICATED_SESSION: AuthSession = Object.freeze({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isAdmin: false,
  loading: false,
  ready: false,
  login: async () => {},
  logout: async () => {},
});

/**
 * Session state for a signed-in administrator: the mirror of
 * {@link UNAUTHENTICATED_SESSION}, and the fixture every "an admin still sees
 * this control" render needs.
 *
 * A test fixture living in shipped code, deliberately. It belongs beside the
 * constant it mirrors, and the alternative — a ``@sep/test-utils`` export —
 * would drag ``@sep/api`` into every package's vitest setup file, where the
 * eagerly-loaded real module defeats ``vi.mock('@sep/api')`` in suites that
 * have nothing to do with auth.
 *
 * Do not hand this to ``AuthContext`` in application code: the shell's
 * ``AuthProvider`` owns the real session, and a hardcoded admin one only
 * unlocks controls the API still refuses.
 */
export const ADMIN_SESSION: AuthSession = Object.freeze({
  ...UNAUTHENTICATED_SESSION,
  isAuthenticated: true,
  isAdmin: true,
  ready: true,
});

export const AuthContext = createContext<AuthSession | null>(null);

let warnedMissingProvider = false;

/**
 * Warn once per bundle when the provider is missing. Hiding controls is a
 * quieter failure than the throw this replaced, so a stray consumer mounted
 * outside the provider would otherwise silently look like a non-admin session.
 */
function warnMissingProvider(): void {
  if (warnedMissingProvider || !import.meta.env?.DEV) {
    return;
  }
  warnedMissingProvider = true;
  // eslint-disable-next-line no-console -- surface a silently degraded session in dev
  console.warn(
    'useAuth() was called outside an AuthProvider — falling back to a signed-out, ' +
      'non-admin session. Mutation controls will be hidden.',
  );
}

/**
 * Read the current session and its derived capabilities.
 *
 * Resolves to {@link UNAUTHENTICATED_SESSION} when no provider is mounted.
 */
export function useAuth(): AuthState {
  const session = useContext(AuthContext);
  if (!session) {
    warnMissingProvider();
  }
  const resolved = session ?? UNAUTHENTICATED_SESSION;
  return useMemo(() => ({ ...resolved, canMutate: deriveCanMutate(resolved) }), [resolved]);
}
