import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  postLogin,
  postLogout,
  fetchCurrentUser,
  refreshAccessToken,
  setOnRefreshed,
  setOnUnauthorized,
  setTokenProvider,
  type OAuthTokenResponse,
  type User,
} from '@sep/api';
import { useSilentRefresh } from '../hooks/useSilentRefresh';

// ── Context shape ───────────────────────────────────────────────────────
interface AuthState {
  user: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /** true during initial session bootstrap & during login */
  loading: boolean;
  /** true after the initial session check finishes (success or failure) */
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

// ── Provider ────────────────────────────────────────────────────────────
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Access token lives only in React state. A ref mirrors the latest value
  // so the token provider callback (injected into the API client) always
  // reads the current token without stale closures.
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [expiresIn, setExpiresIn] = useState<number | null>(null);
  const tokenRef = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);

  const isAuthenticated = !!accessToken;
  const isAdmin = user?.isAdmin ?? false;

  const applyTokens = useCallback((tokens: OAuthTokenResponse) => {
    tokenRef.current = tokens.accessToken;
    setAccessToken(tokens.accessToken);
    setExpiresIn(tokens.expiresIn);
  }, []);

  const clearAuth = useCallback(() => {
    tokenRef.current = null;
    setAccessToken(null);
    setExpiresIn(null);
    setUser(null);
  }, []);

  // ── Login ─────────────────────────────────────────────────────────────
  const login = useCallback(
    async (username: string, password: string) => {
      setLoading(true);
      try {
        const tokens = await postLogin(username, password);
        applyTokens(tokens);
        const profile = await fetchCurrentUser();
        setUser(profile);
      } finally {
        setLoading(false);
      }
    },
    [applyTokens],
  );

  // ── Logout ────────────────────────────────────────────────────────────
  // Always clear local state, even if the backend call fails (network
  // error, expired token). The refresh cookie is best-effort cleared
  // server-side; a stuck cookie would be re-validated on next use.
  const logout = useCallback(async () => {
    try {
      await postLogout();
    } catch {
      // swallow — we clear local state unconditionally below
    } finally {
      clearAuth();
    }
  }, [clearAuth]);

  // ── Silent refresh timer ──────────────────────────────────────────────
  // Success updates state via the ``setOnRefreshed`` callback below — the
  // hook only triggers the shared single-flight refresh so the timer and
  // the 401 retry interceptor cannot double-rotate the refresh cookie.
  useSilentRefresh({
    accessToken,
    expiresIn,
    onFailure: clearAuth,
  });

  // ── Inject callbacks into API client ──────────────────────────────────
  useEffect(() => {
    setTokenProvider(() => tokenRef.current);
    setOnRefreshed((token, ttl) => {
      tokenRef.current = token;
      setAccessToken(token);
      setExpiresIn(ttl);
    });
    setOnUnauthorized(() => {
      clearAuth();
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
      }
    });
    return () => {
      setTokenProvider(() => null);
      setOnRefreshed(() => {});
      setOnUnauthorized(() => {});
    };
  }, [clearAuth]);

  // ── Session bootstrap (runs once on mount) ────────────────────────────
  // Access token is memory-only so it's lost on reload. Attempt a silent
  // refresh through the shared coordinator (same path as the 401 retry
  // interceptor) so a page-load concurrent with an in-flight refresh does
  // not rotate the cookie twice. If the cookie is absent or invalid the
  // call resolves to null and the user lands on /login.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    refreshAccessToken()
      .then(async (token) => {
        if (cancelled) {
          return;
        }
        if (!token) {
          clearAuth();
          return;
        }
        // ``setOnRefreshed`` has already synced tokenRef + accessToken
        // state, so the profile fetch will carry the new Bearer token.
        const profile = await fetchCurrentUser();
        if (cancelled) {
          return;
        }
        setUser(profile);
      })
      .catch(() => {
        if (!cancelled) {
          clearAuth();
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          setReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Context value ─────────────────────────────────────────────────────
  const value = useMemo<AuthState>(
    () => ({
      user,
      accessToken,
      isAuthenticated,
      isAdmin,
      loading,
      ready,
      login,
      logout,
    }),
    [user, accessToken, isAuthenticated, isAdmin, loading, ready, login, logout],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}

// ── Hook ────────────────────────────────────────────────────────────────
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}

export type { User };
