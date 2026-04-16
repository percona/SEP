import axios from 'axios';
import applyCaseMiddleware from 'axios-case-converter';

// ── Token provider ─────────────────────────────────────────────────────
// Instead of owning a copy of the access token, the API layer delegates
// token retrieval to a provider injected by the auth layer (AuthProvider).
// This ensures a single source of truth and prevents desync between
// AuthProvider state and the API client.
type TokenProvider = () => string | null;
type OnUnauthorized = () => void;

let _getToken: TokenProvider = () => null;
let _onUnauthorized: OnUnauthorized = () => {};

/** Inject a callback that returns the current access token. */
export function setTokenProvider(provider: TokenProvider) {
  _getToken = provider;
}

/** Inject a callback invoked when the API receives a 401/303 response. */
export function setOnUnauthorized(handler: OnUnauthorized) {
  _onUnauthorized = handler;
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

// Attach Bearer token via the injected provider on every request
apiClient.interceptors.request.use((config) => {
  const token = _getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 and 303 globally — delegate to the injected handler
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      // 401 = invalid token, 303 = session expired (backend redirect to login)
      if (status === 401 || status === 303) {
        _onUnauthorized();
      }
    }
    return Promise.reject(error);
  },
);
