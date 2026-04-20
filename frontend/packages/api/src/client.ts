import axios, { type InternalAxiosRequestConfig } from 'axios';
import applyCaseMiddleware from 'axios-case-converter';
import { ApiError, normalizeAxiosError } from './errors';

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

// ── Dev logging flag ───────────────────────────────────────────────────
// Vite statically replaces `import.meta.env.DEV` at build time, so the
// logging branches are dead-code-eliminated in production bundles.
const IS_DEV = import.meta.env.DEV;

/**
 * Primary API client. See README.md for the camelCase ↔ snake_case policy —
 * axios-case-converter will be removed in Phase 2 once generated types land.
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

// ── Request: attach Bearer token, optionally log ───────────────────────
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = _getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  if (IS_DEV) {
    const method = config.method?.toUpperCase() ?? 'GET';
    // eslint-disable-next-line no-console
    console.debug(`[api] → ${method} ${config.url ?? ''}`);
  }
  return config;
});

// ── Response: unauthorized handling, dev logging, error normalization ──
// In the browser, 303 redirects are followed automatically (maxRedirects is
// Node-only), so the client may receive a 200 HTML login page instead of a
// 303 status. We detect this by checking the response content-type.
// Refresh endpoint is the recovery mechanism — its failures must not trigger
// the global unauthorized handler, or a genuine refresh rejection would hard-
// redirect instead of letting the AuthProvider bootstrap handle it cleanly.
const isRefreshRequest = (url: string | undefined) => !!url && url.includes('/oauth/refresh');

apiClient.interceptors.response.use(
  (response) => {
    const ct = response.headers['content-type'] ?? '';
    if (ct.includes('text/html') && !isRefreshRequest(response.config?.url)) {
      _onUnauthorized();
      return Promise.reject(
        new ApiError({
          kind: 'http',
          status: 401,
          message: 'Session expired (redirected to login page)',
          url: response.config?.url,
          method: response.config?.method?.toUpperCase(),
        }),
      );
    }
    if (IS_DEV) {
      const method = response.config?.method?.toUpperCase() ?? 'GET';
      // eslint-disable-next-line no-console
      console.debug(`[api] ← ${response.status} ${method} ${response.config?.url ?? ''}`);
    }
    return response;
  },
  (error) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      if ((status === 401 || status === 303) && !isRefreshRequest(error.config?.url)) {
        _onUnauthorized();
      }
    }
    const apiError = normalizeAxiosError(error);
    if (IS_DEV) {
      const loc = apiError.method && apiError.url ? `${apiError.method} ${apiError.url}` : '';
      // eslint-disable-next-line no-console
      console.debug(
        `[api] ✗ ${apiError.kind}${apiError.status ? ` ${apiError.status}` : ''} ${loc} — ${apiError.message}`,
      );
    }
    return Promise.reject(apiError);
  },
);
