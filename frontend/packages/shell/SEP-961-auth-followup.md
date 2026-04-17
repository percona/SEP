# SEP-945 — Auth Implementation Follow-up

**Status:** Blocked on SEP-952 (backend Casdoor redirect flow + HttpOnly refresh cookie + logout endpoint).

Current frontend implements an interim username/password (OAuth2 password grant) flow. Once SEP-952 lands, swap wholesale to the Casdoor authorization-code flow described below.

## Files to change

- `frontend/packages/shell/src/contexts/auth.tsx`
- `frontend/packages/shell/src/pages/LoginPage.tsx`
- `frontend/packages/shell/src/components/AuthGuard.tsx` (minor)
- `frontend/packages/api/src/client.ts`
- `frontend/packages/api/src/auth.ts`
- `frontend/packages/shell/src/router.tsx` (add callback route)
- **New:** `frontend/packages/shell/src/pages/OAuthCallbackPage.tsx`
- **New (optional, per ticket):** `frontend/packages/shell/src/hooks/useSilentRefresh.ts`

## Required changes

### 1. Remove refresh token from localStorage

Violates AC: _"No tokens are persisted in localStorage, sessionStorage, or non-HttpOnly cookies"_.

In `auth.tsx`:

- Delete `REFRESH_KEY` constant and all `localStorage.getItem/setItem/removeItem` calls (lines 23, 60, 67, 84, 148).
- `persistTokens` becomes `setAccessToken(accessToken)` — no refresh token argument; backend owns it via HttpOnly cookie.
- Session bootstrap (`useEffect` at line 147) no longer reads localStorage. Instead, unconditionally attempt `POST /api/oauth/refresh` with `withCredentials: true`. If cookie exists and is valid → restore session; if not → 401 → clear state, mark `ready`.

### 2. Replace password login with Casdoor redirect

`LoginPage.tsx` currently renders a username/password form. Replace with:

- On "Sign In" click (or auto on mount if page is just a redirect), construct Casdoor authorize URL:
  ```
  {CASDOOR_ENDPOINT}/login/oauth/authorize
    ?client_id={CLIENT_ID}
    &response_type=code
    &redirect_uri={FRONTEND_ORIGIN}/oauth/callback
    &scope=read
    &state={random-csrf-token}
  ```
- Store `state` + optional post-login `redirect` path in `sessionStorage` under a short-lived key (acceptable — not a token) before redirecting.
- `window.location.href = authorizeUrl` (full navigation, not SPA nav).
- Casdoor config (endpoint, client_id, redirect_uri) must come from backend — add `GET /api/oauth/config` or embed in initial page HTML. Coordinate with SEP-960.

Keep the current Percona-branded card UI as a placeholder with a "Sign in with Casdoor" button if auto-redirect is undesirable.

### 3. Add OAuth callback page

New `OAuthCallbackPage.tsx` mounted at `/oauth/callback`:

- Parse `code` and `state` from `useSearchParams()`.
- Validate `state` against the value stored pre-redirect; abort on mismatch (CSRF guard).
- `POST /api/oauth/callback { code }` (or whichever endpoint SEP-952 exposes for code exchange). Backend calls `CasdoorSDK.get_access_token(code=...)`, sets HttpOnly refresh cookie, returns `{ access_token, expires_in, ... }`.
- Call a new `auth.completeLogin(accessToken, expiresIn)` method on the context → store access token in state, schedule refresh, fetch user via `/users/me`.
- Navigate to the stored `redirect` path (or `/`).
- On any error: clear state, redirect to `/login?error=...`.

Add route in `router.tsx`:

```tsx
{ path: '/oauth/callback', element: <OAuthCallbackPage /> }
```

Keep it outside `AuthGuard`.

### 4. Update `AuthContext` API surface

Change the `login` signature per the ticket:

```ts
interface AuthState {
  user: User | null;
  accessToken: string | null; // rename from `token` for ticket alignment (optional)
  isAuthenticated: boolean;
  isAdmin: boolean;
  loading: boolean;
  ready: boolean;
  login: () => void; // redirects to Casdoor — no args
  logout: () => Promise<void>; // now async, calls backend
  // Internal, used only by OAuthCallbackPage:
  completeLogin: (accessToken: string, expiresIn: number) => Promise<void>;
}
```

`login()`:

- Build Casdoor authorize URL (same logic extracted from LoginPage) and `window.location.href = ...`.

`completeLogin(accessToken, expiresIn)`:

- `setAccessToken(accessToken)`; update ref.
- `scheduleRefresh(expiresIn)`.
- `fetchCurrentUser()` → `setUser`.

### 5. Logout calls backend

`logout()` in `auth.tsx:122`:

```ts
const logout = useCallback(async () => {
  try {
    await apiClient.post('/oauth/logout', null, { withCredentials: true });
  } catch {
    // Even if backend logout fails, clear local state.
  } finally {
    clearTokens();
    window.location.href = '/login';
  }
}, [clearTokens]);
```

Backend logout must clear the HttpOnly refresh cookie and invalidate the token in Casdoor (SEP-952 scope).

### 6. Refresh flow: cookie-based, no body

In `api/src/auth.ts`:

```ts
export async function postRefresh(): Promise<OAuthTokenResponse> {
  const { data } = await apiClient.post<OAuthTokenResponse>('/oauth/refresh', null, {
    withCredentials: true,
  });
  return data;
}
```

Remove the `refreshToken` parameter everywhere. The HttpOnly cookie is sent automatically.

`apiClient` baseURL is same-origin (`/api`) so cookies flow without CORS config, but still set `withCredentials: true` explicitly on refresh/logout for clarity — or set it globally on the axios instance.

In `auth.tsx`:

- `scheduleRefresh`'s timer callback calls `postRefresh()` (no args). On success → `setAccessToken` + re-schedule. On failure → `clearTokens()` + redirect to `/login`.

### 7. Response interceptor: single refresh retry on 401

Per ticket AC: _"catches 401 and triggers a single refresh attempt before failing"_. Current `client.ts:63-71` just calls `_onUnauthorized`.

Replace with a retry-with-refresh pattern. Inject a refresh callback via a new setter:

```ts
type RefreshFn = () => Promise<string>; // returns new access token
let _refresh: RefreshFn | null = null;
let _refreshInFlight: Promise<string> | null = null;

export function setRefreshHandler(fn: RefreshFn) {
  _refresh = fn;
}
```

Response interceptor:

```ts
apiClient.interceptors.response.use(
  (r) => r,
  async (error) => {
    if (!axios.isAxiosError(error)) return Promise.reject(error);
    const original = error.config as AxiosRequestConfig & { _retried?: boolean };
    const status = error.response?.status;

    if (status !== 401 || original._retried || !_refresh) {
      if (status === 401) _onUnauthorized();
      return Promise.reject(error);
    }

    original._retried = true;
    try {
      // Queue concurrent 401s onto the same in-flight refresh.
      _refreshInFlight ??= _refresh().finally(() => {
        _refreshInFlight = null;
      });
      const newToken = await _refreshInFlight;
      original.headers = { ...original.headers, Authorization: `Bearer ${newToken}` };
      return apiClient.request(original);
    } catch {
      _onUnauthorized();
      return Promise.reject(error);
    }
  },
);
```

AuthProvider wires the handler:

```ts
setRefreshHandler(async () => {
  const tokens = await postRefresh();
  setAccessToken(tokens.accessToken);
  scheduleRefresh(tokens.expiresIn);
  return tokens.accessToken;
});
```

Also **remove** the HTML-content-type hack (`client.ts:52-60`). With Bearer flow and JSON-only API, 401 returns JSON; no browser redirect to login page happens.

### 8. Extract `useSilentRefresh` hook (optional)

Ticket lists `frontend/packages/shell/src/hooks/useSilentRefresh.ts` as an affected file. Current implementation inlines the timer in `AuthProvider` via `scheduleRefresh`. Functionally equivalent. Extract only if reviewer asks.

Signature if extracted:

```ts
useSilentRefresh({
  expiresIn: number | null,         // null = no timer
  onRefresh: () => Promise<number>, // returns new expiresIn
  onFailure: () => void,
  bufferSeconds?: number,           // default 60
});
```

### 9. AuthGuard — no changes needed

Already handles `ready`/`loading`/`isAuthenticated` correctly. After swap, the bootstrap refresh path still sets `ready=true` at the end, so the guard behavior is unchanged.

## Preserve from current implementation

- Memory-only access token (state + `tokenRef` to avoid stale closures in the token provider callback). ✓
- `setTokenProvider` / `setOnUnauthorized` injection pattern in `client.ts`. ✓
- Request interceptor that reads token via the provider. ✓
- 60-second refresh buffer (`scheduleRefresh` min 10s clamp). ✓
- `AuthGuard` redirect-to-login with `?redirect=<returnUrl>`. ✓

## Acceptance checklist (re-verify after swap)

- [ ] No `localStorage` / `sessionStorage` writes of `access_token` or `refresh_token` (sessionStorage for CSRF state + post-login redirect is OK).
- [ ] `login()` redirects to Casdoor authorize URL.
- [ ] `/oauth/callback` exchanges code → access token via backend.
- [ ] Request interceptor injects `Authorization: Bearer <token>`.
- [ ] Response interceptor: single refresh retry on 401, concurrent 401s share one refresh.
- [ ] Silent refresh timer fires before `expires_in`, updates token, reschedules.
- [ ] On refresh failure → local state cleared + redirect to `/login`.
- [ ] `logout()` calls backend `/oauth/logout` and clears state.
- [ ] `AuthGuard` redirects unauthenticated users to `/login` with return URL.
- [ ] Page reload restores session via cookie-based refresh (no localStorage).

## Coordination

- **SEP-952** — backend dual-auth (Bearer + HttpOnly cookie) must be merged first. Confirm endpoint shapes:
  - `POST /api/oauth/callback` (or equivalent code-exchange route) — request body, response body.
  - `POST /api/oauth/refresh` — accepts no body, reads cookie, returns `{ access_token, expires_in }`.
  - `POST /api/oauth/logout` — clears cookie, invalidates Casdoor token.
  - `GET /api/oauth/config` — returns Casdoor endpoint, client_id, redirect_uri (or embed in shell HTML per SEP-960).
- **SEP-960** — shell configuration / Casdoor config delivery.
- **SEP-963** — ensure axios interceptors live in this package and are not duplicated.

## Risks

- **Refresh race:** concurrent 401s must not trigger parallel refreshes. Handled via `_refreshInFlight` singleton promise above.
- **Infinite redirect loop:** if `/oauth/callback` itself 401s (unlikely — it's unauthenticated), the retry logic must not redirect back into callback. Exclude the callback request from the retry path via `original._retried` guard or explicit URL skip.
- **CSRF on callback:** validate `state` param; reject mismatches.
- **Logout failure:** always clear local state even if backend call fails.
