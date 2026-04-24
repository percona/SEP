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
  postRefresh,
  postLogout,
  fetchCurrentUser,
  setTokenProvider,
  setOnUnauthorized,
  type User,
} from '@sep/api';

// ── Context shape ───────────────────────────────────────────────────────
interface AuthState {
  user: User | null;
  token: string | null;
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
// Access token lives only in React state. The refresh token lives in an
// `HttpOnly` cookie set by the backend — JS never sees it and never
// persists anything to localStorage/sessionStorage.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  // Mirror the latest token so the token-provider callback doesn't close
  // over a stale value.
  const tokenRef = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const isAuthenticated = !!token;
  const isAdmin = user?.isAdmin ?? false;

  // ── Helpers ───────────────────────────────────────────────────────────
  const persistToken = useCallback((accessToken: string) => {
    setToken(accessToken);
    tokenRef.current = accessToken;
  }, []);

  const clearAuth = useCallback(() => {
    setToken(null);
    tokenRef.current = null;
    setUser(null);
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = undefined;
    }
  }, []);

  // ── Token refresh ─────────────────────────────────────────────────────
  const scheduleRefresh = useCallback(
    (expiresIn: number) => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }

      // Refresh 60 seconds before expiry (minimum 10s)
      const ms = Math.max((expiresIn - 60) * 1000, 10_000);

      refreshTimerRef.current = setTimeout(async () => {
        try {
          const tokens = await postRefresh();
          persistToken(tokens.access_token);
          scheduleRefresh(tokens.expires_in);
        } catch {
          // Refresh failed — force re-login
          clearAuth();
        }
      }, ms);
    },
    [persistToken, clearAuth],
  );

  // ── Login ─────────────────────────────────────────────────────────────
  const login = useCallback(
    async (username: string, password: string) => {
      setLoading(true);
      try {
        const tokens = await postLogin(username, password);
        persistToken(tokens.access_token);
        scheduleRefresh(tokens.expires_in);

        // Fetch full user profile
        const profile = await fetchCurrentUser();
        setUser(profile);
      } finally {
        setLoading(false);
      }
    },
    [persistToken, scheduleRefresh],
  );

  // ── Logout ────────────────────────────────────────────────────────────
  // `POST /oauth/logout` requires the Bearer token to identify the session
  // to invalidate, so we must call it *before* clearing local state — if
  // we cleared first, the request interceptor would read a null token and
  // the backend would reject with 401, leaving the `HttpOnly` refresh
  // cookie intact (and a subsequent page reload would bootstrap a fresh
  // session). Run the logout request, then clear local state regardless
  // of the outcome so a backend failure can't trap the user.
  const logout = useCallback(async () => {
    try {
      await postLogout();
    } catch {
      /* clear local state anyway — cookie will expire on its own */
    }
    clearAuth();
  }, [clearAuth]);

  // ── Inject token provider & unauthorized handler into API client ────
  // The API layer never owns the token — it calls back here to get it.
  useEffect(() => {
    setTokenProvider(() => tokenRef.current);
    setOnUnauthorized(() => {
      clearAuth();
      // Redirect to login unless already there (avoid loops)
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
      }
    });
    return () => {
      setTokenProvider(() => null);
      setOnUnauthorized(() => {});
    };
  }, [clearAuth]);

  // ── Session bootstrap (runs once on mount) ────────────────────────────
  // Access token is memory-only so it's lost on reload. Restore the session
  // by attempting a silent refresh — the browser automatically sends the
  // `HttpOnly` refresh cookie if one is set. No persisted state to read.
  useEffect(() => {
    setLoading(true);
    postRefresh()
      .then((tokens) => {
        persistToken(tokens.access_token);
        scheduleRefresh(tokens.expires_in);
        return fetchCurrentUser();
      })
      .then((profile) => {
        setUser(profile);
      })
      .catch(() => {
        // No valid refresh cookie — user must log in
        clearAuth();
      })
      .finally(() => {
        setLoading(false);
        setReady(true);
      });

    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Context value ─────────────────────────────────────────────────────
  const value = useMemo<AuthState>(
    () => ({
      user,
      token,
      isAuthenticated,
      isAdmin,
      loading,
      ready,
      login,
      logout,
    }),
    [user, token, isAuthenticated, isAdmin, loading, ready, login, logout],
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
