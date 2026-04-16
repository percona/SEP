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
  fetchCurrentUser,
  setTokenProvider,
  setOnUnauthorized,
  type User,
} from '@sep/api';

// ── Storage keys ────────────────────────────────────────────────────────
// Only the refresh token is persisted (localStorage for now).
// TODO: move refresh token to HttpOnly cookie once backend supports it.
const REFRESH_KEY = 'sep_refresh_token';

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
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

// ── Provider ────────────────────────────────────────────────────────────
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Access token lives only in React state. A ref mirrors the latest value
  // so the token provider callback (injected into the API client) always
  // reads the current token without stale closures.
  const [token, setToken] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const isAuthenticated = !!token;
  const isAdmin = user?.isAdmin ?? false;

  // ── Helpers ───────────────────────────────────────────────────────────
  const persistTokens = useCallback((accessToken: string, refreshToken: string) => {
    setToken(accessToken);
    tokenRef.current = accessToken;
    localStorage.setItem(REFRESH_KEY, refreshToken);
  }, []);

  const clearTokens = useCallback(() => {
    setToken(null);
    tokenRef.current = null;
    setUser(null);
    localStorage.removeItem(REFRESH_KEY);
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
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
        const rt = localStorage.getItem(REFRESH_KEY);
        if (!rt) {
          return;
        }

        try {
          const tokens = await postRefresh(rt);
          persistTokens(tokens.accessToken, tokens.refreshToken);
          scheduleRefresh(tokens.expiresIn);
        } catch {
          // Refresh failed — force re-login
          clearTokens();
        }
      }, ms);
    },
    [persistTokens, clearTokens],
  );

  // ── Login ─────────────────────────────────────────────────────────────
  const login = useCallback(
    async (username: string, password: string) => {
      setLoading(true);
      try {
        const tokens = await postLogin(username, password);
        persistTokens(tokens.accessToken, tokens.refreshToken);
        scheduleRefresh(tokens.expiresIn);

        // Fetch full user profile
        const profile = await fetchCurrentUser();
        setUser(profile);
      } finally {
        setLoading(false);
      }
    },
    [persistTokens, scheduleRefresh],
  );

  // ── Logout ────────────────────────────────────────────────────────────
  const logout = useCallback(() => {
    clearTokens();
  }, [clearTokens]);

  // ── Inject token provider & unauthorized handler into API client ────
  // The API layer never owns the token — it calls back here to get it.
  useEffect(() => {
    setTokenProvider(() => tokenRef.current);
    setOnUnauthorized(() => {
      clearTokens();
      // Redirect to login unless already there (avoid loops)
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
      }
    });
    return () => {
      setTokenProvider(() => null);
      setOnUnauthorized(() => {});
    };
  }, [clearTokens]);

  // ── Session bootstrap (runs once on mount) ────────────────────────────
  // Access token is memory-only so it's lost on reload. Restore the
  // session by performing a silent refresh with the persisted refresh
  // token, then fetch the user profile with the new access token.
  useEffect(() => {
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    if (!refreshToken) {
      setReady(true);
      return;
    }

    setLoading(true);
    postRefresh(refreshToken)
      .then((tokens) => {
        persistTokens(tokens.accessToken, tokens.refreshToken);
        scheduleRefresh(tokens.expiresIn);
        return fetchCurrentUser();
      })
      .then((profile) => {
        setUser(profile);
      })
      .catch(() => {
        // Refresh token invalid/expired — clear and require re-login
        clearTokens();
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
