/// <reference path="./vite-env.d.ts" />
/**
 * Typed request clients built on `openapi-fetch` + generated `paths` types.
 *
 * One client per OpenAPI spec (see `scripts/codegen.ts`):
 *   - `mainApi`      — core API (oauth, users)
 *   - `inventoryApi` — `/api/inventory/*`
 *   - `tasksApi`     — `/api/tasks/*`
 *   - `sepApi`       — SEP app
 *
 * The generated `paths` keys include the mount prefix (e.g. `/api/users/me`),
 * so every client uses `baseUrl: ''` and relies on the browser's same-origin
 * resolution — identical behaviour to the axios `apiClient`.
 *
 * We share auth state with `apiClient` via `getToken()`/`emitUnauthorized()`
 * from `./client` — both the axios and fetch transports observe the same
 * `setTokenProvider()`/`setOnUnauthorized()` registration. Errors are
 * normalised to `ApiError` (via `throwOnApiError`) so callers see the same
 * shape regardless of which client they use.
 */
import createClient, { type Client, type Middleware } from 'openapi-fetch';
import { emitUnauthorized, getToken } from './client';
import { ApiError } from './errors';
import type { paths as InventoryPaths } from './generated/inventory';
import type { paths as MainPaths } from './generated/main';
import type { paths as SepPaths } from './generated/sep';
import type { paths as TasksPaths } from './generated/tasks';

const IS_DEV = import.meta.env.DEV;

const isRefreshRequest = (url: string) => url.includes('/oauth/refresh');

/**
 * A 200 HTML response (e.g. a follow of a login redirect) means the session
 * is gone. The browser can't observe the 303, so content-type is the only
 * signal. Synthesise a 401 so the normal error path runs.
 */
function isHtmlLoginResponse(response: Response): boolean {
  const ct = response.headers.get('content-type') ?? '';
  return response.ok && ct.includes('text/html');
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) {
      request.headers.set('Authorization', `Bearer ${token}`);
    }
    if (IS_DEV) {
      // eslint-disable-next-line no-console
      console.debug(`[api] → ${request.method} ${new URL(request.url).pathname}`);
    }
    return request;
  },
  async onResponse({ request, response }) {
    if (IS_DEV) {
      // eslint-disable-next-line no-console
      console.debug(
        `[api] ← ${response.status} ${request.method} ${new URL(request.url).pathname}`,
      );
    }

    if (isHtmlLoginResponse(response) && !isRefreshRequest(request.url)) {
      emitUnauthorized();
      return new Response(null, {
        status: 401,
        statusText: 'Session expired (redirected to login page)',
      });
    }

    if ((response.status === 401 || response.status === 303) && !isRefreshRequest(request.url)) {
      emitUnauthorized();
    }

    return response;
  },
};

// openapi-fetch builds absolute URLs as `new URL(baseUrl + path)`. In the
// browser `baseUrl: ''` lets fetch resolve against the document origin, but
// under Node (tests, SSR) there is no implicit origin — fall back to
// `location.origin` if it exists, otherwise a sentinel localhost origin.
const CLIENT_BASE_URL =
  typeof globalThis !== 'undefined' &&
  typeof (globalThis as { location?: Location }).location?.origin === 'string'
    ? (globalThis as { location: Location }).location.origin
    : 'http://localhost';

// Resolve `fetch` lazily rather than capturing `globalThis.fetch` at module
// load. Test harnesses (MSW, happy-dom) patch the global after this file is
// imported, and openapi-fetch would otherwise call the pre-patch reference.
const lazyFetch: typeof fetch = (...args) => globalThis.fetch(...args);

function makeClient<Paths extends object>(): Client<Paths> {
  const client = createClient<Paths>({ baseUrl: CLIENT_BASE_URL, fetch: lazyFetch });
  client.use(authMiddleware);
  return client;
}

export const mainApi = makeClient<MainPaths>();
export const inventoryApi = makeClient<InventoryPaths>();
export const tasksApi = makeClient<TasksPaths>();
export const sepApi = makeClient<SepPaths>();

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function detailFromBody(body: unknown): string | undefined {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      return detail;
    }
  }
  return undefined;
}

/**
 * Raise `ApiError` on any failure instead of returning openapi-fetch's
 * `{ data, error }` tuple. Covers three failure modes:
 *   1. Resolved tuple with `response.ok === false` (server error body).
 *   2. Resolved tuple with a synthesised 401 (HTML login redirect).
 *   3. Rejected promise (network failure, JSON parse error).
 *
 * Use inside React Query `queryFn`s so errors propagate to `error` on the
 * hook result and consumers can `instanceof ApiError` on them.
 */
export async function throwOnApiError<T>(promise: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await promise;
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof SyntaxError) {
      throw new ApiError({ kind: 'unknown', message: 'Malformed response body' }, err);
    }
    // `TypeError` is the standard `fetch` rejection for network failures.
    const message = err instanceof Error ? err.message : 'Network error';
    throw new ApiError({ kind: 'network', message }, err);
  }

  const { data, error, response } = result;
  if (response.ok && error === undefined) {
    return data as T;
  }

  const url = (() => {
    try {
      return new URL(response.url).pathname;
    } catch {
      return undefined;
    }
  })();

  const detail = detailFromBody(error) ?? response.statusText ?? `HTTP ${response.status}`;
  throw new ApiError({
    kind: 'http',
    status: response.status,
    message: detail,
    data: error,
    url,
  });
}
