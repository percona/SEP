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

/** Inject a callback invoked when the API receives an unauthorized response. */
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

// Handle unauthorized responses globally — delegate to the injected handler.
// In the browser, 303 redirects are followed automatically (maxRedirects is
// Node-only), so the client may receive a 200 HTML login page instead of a
// 303 status. We detect this by checking the response content-type.
apiClient.interceptors.response.use(
  (response) => {
    const ct = response.headers['content-type'] ?? '';
    if (ct.includes('text/html')) {
      // API endpoints should never return HTML — this means the browser
      // followed a 303 redirect to the login page.
      _onUnauthorized();
      return Promise.reject(new Error('Session expired (redirected to login page)'));
    }
    return response;
  },
  (error) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      if (status === 401 || status === 303) {
        _onUnauthorized();
      }
    }
    return Promise.reject(error);
  },
);
