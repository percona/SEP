import axios from 'axios';
import applyCaseMiddleware from 'axios-case-converter';

// ── In-memory token store ──────────────────────────────────────────────
// Access token lives only in memory — never persisted to localStorage.
// This limits XSS blast radius: a script can't just read storage to
// steal the token. The refresh token is still in localStorage until the
// backend provides an HttpOnly-cookie-based refresh endpoint.
let _accessToken: string | null = null;

/** Set the in-memory access token. Called by AuthProvider on login/refresh. */
export function setAccessToken(token: string | null) {
  _accessToken = token;
}

/** Read the current in-memory access token. */
export function getAccessToken(): string | null {
  return _accessToken;
}

/**
 * Primary API client with automatic camelCase <-> snake_case conversion.
 * All SEP API requests go through this client.
 */
export const apiClient = applyCaseMiddleware(
  axios.create({
    baseURL: '/api',
    headers: {
      'Content-Type': 'application/json',
    },
    // Backend returns 303 for expired sessions — don't auto-follow redirects
    maxRedirects: 0,
    validateStatus: (status) => status >= 200 && status < 300,
  }),
);

// Attach Bearer token from in-memory store on every request
apiClient.interceptors.request.use((config) => {
  if (_accessToken) {
    config.headers.Authorization = `Bearer ${_accessToken}`;
  }
  return config;
});

// Handle 401 and 303 globally — clear token and redirect to login
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      // 401 = invalid token, 303 = session expired (backend redirect to login)
      if (status === 401 || status === 303) {
        _accessToken = null;
        // TODO: once refresh token moves to HttpOnly cookie, remove this line
        localStorage.removeItem('sep_refresh_token');
        // Only redirect if not already on login page (avoid loops)
        if (!window.location.pathname.startsWith('/login')) {
          window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
        }
      }
    }
    return Promise.reject(error);
  },
);
