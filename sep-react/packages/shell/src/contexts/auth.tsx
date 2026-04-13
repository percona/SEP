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
  type User,
} from '@sep/api';

// ── Storage keys ────────────────────────────────────────────────────────
const TOKEN_KEY = 'sep_token';
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
  /** Dev-only: login without backend */
  mockLogin: (username: string) => void;
}

const AuthContext = createContext<AuthState | null>(null);

// ── Provider ────────────────────────────────────────────────────────────
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem(TOKEN_KEY),
  );
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const isAuthenticated = !!token;
  const isAdmin = user?.isAdmin ?? false;

  // ── Helpers ───────────────────────────────────────────────────────────
  const persistTokens = useCallback(
    (accessToken: string, refreshToken: string) => {
      setToken(accessToken);
      localStorage.setItem(TOKEN_KEY, accessToken);
      localStorage.setItem(REFRESH_KEY, refreshToken);
    },
    [],
  );

  const clearTokens = useCallback(() => {
    setToken(null);
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
  }, []);

  // ── Token refresh ─────────────────────────────────────────────────────
  const scheduleRefresh = useCallback(
    (expiresIn: number) => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);

      // Refresh 60 seconds before expiry (minimum 10s)
      const ms = Math.max((expiresIn - 60) * 1000, 10_000);

      refreshTimerRef.current = setTimeout(async () => {
        const rt = localStorage.getItem(REFRESH_KEY);
        if (!rt) return;

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

  // ── Mock login (dev without backend) ──────────────────────────────────
  const mockLogin = useCallback(
    (username: string) => {
      const mockUser: User = {
        id: '00000000-0000-0000-0000-000000000001',
        username,
        email: `${username}@percona.com`,
        firstName: username.charAt(0).toUpperCase() + username.slice(1),
        lastName: '',
        fullName: username,
        isAdmin: username === 'admin',
        isActive: true,
        isForbidden: false,
        isDeleted: false,
        owner: 'built-in',
        createdTime: new Date().toISOString(),
        updatedTime: new Date().toISOString(),
      };
      setToken('mock-jwt-token');
      setUser(mockUser);
      localStorage.setItem(TOKEN_KEY, 'mock-jwt-token');
    },
    [],
  );

  // ── Session bootstrap (runs once on mount) ────────────────────────────
  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY);
    if (!storedToken || storedToken === 'mock-jwt-token') {
      setReady(true);
      return;
    }

    setLoading(true);
    fetchCurrentUser()
      .then((profile) => {
        setUser(profile);
        // If we have a refresh token, start the refresh cycle
        // Assume ~30 min remaining since we don't know the exact expiry
        const rt = localStorage.getItem(REFRESH_KEY);
        if (rt) scheduleRefresh(1800);
      })
      .catch(() => {
        // Session invalid — clear everything silently
        clearTokens();
      })
      .finally(() => {
        setLoading(false);
        setReady(true);
      });

    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
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
      mockLogin,
    }),
    [user, token, isAuthenticated, isAdmin, loading, ready, login, logout, mockLogin],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}

// ── Hook ────────────────────────────────────────────────────────────────
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

export type { User };
