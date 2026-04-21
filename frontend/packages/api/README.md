# @sep/api

Centralized HTTP client, React Query configuration, and (in Phase 2) OpenAPI
type codegen for the SEP frontend.

This package is consumed by `@sep/shell`, `@sep/framework`, and plugin
packages. Anything that talks to the backend should go through here.

## What's in the package today (Phase 1)

- **`apiClient`** — preconfigured axios instance with interceptors for Bearer
  token injection, unauthorized handling, dev logging, and structured error
  normalization into `ApiError`.
- **`createQueryClient()`** — factory that returns a `QueryClient` with the
  dashboard-tuned defaults: 30s stale time, exponential back-off retry that
  skips 4xx responses, `refetchOnWindowFocus: true`.
- **`ApiError`** — structured error class surfaced by the client. Every
  rejection from `apiClient` is an `ApiError`. Distinguishes `http`,
  `network`, `timeout`, `canceled`, and `unknown` kinds.
- **Token accessor pattern** — `setTokenProvider()` and `setOnUnauthorized()`
  let the auth layer plug in without the API package depending on auth state.
- **Hooks** — `usePluginSchema`, `usePluginTasks`, `usePluginTask`,
  `useCreatePluginTask`. These predate codegen and use generics; they'll be
  complemented by typed hooks once Phase 2 lands.
- **Auth functions** — `postLogin`, `postRefresh`, `fetchCurrentUser`.
  Thin request wrappers consumed by the `AuthProvider` in `@sep/shell`.

## Usage

### Wire up the query client in the app root

```tsx
import { QueryClientProvider } from '@tanstack/react-query';
import { createQueryClient } from '@sep/api';

const queryClient = createQueryClient();

<QueryClientProvider client={queryClient}>
  <App />
</QueryClientProvider>;
```

### Wire up auth (from `@sep/shell`'s `AuthProvider`)

```ts
import { setTokenProvider, setOnUnauthorized } from '@sep/api';

setTokenProvider(() => currentAccessToken);
setOnUnauthorized(() => redirectToLogin());
```

### Call the API

```ts
import { apiClient, ApiError } from '@sep/api';

try {
  const { data } = await apiClient.get('/plugins/checksums/');
} catch (err) {
  if (err instanceof ApiError && err.status === 404) {
    // handle not found
  }
}
```

### Handling errors in React Query

```ts
const { data, error } = useQuery({ queryKey: ['x'], queryFn: () => apiClient.get('/x') });

if (error instanceof ApiError) {
  // error.kind, error.status, error.message are all reliable
}
```

## Conventions

### camelCase ↔ snake_case (policy: drop middleware in Phase 2)

The backend is FastAPI and exposes snake_case field names on the wire.
Today `apiClient` wraps axios with `axios-case-converter`, which transforms
request payloads to snake_case and response payloads to camelCase before
either hits application code. This was pragmatic before codegen existed.

**Decision:** once Phase 2 runs `openapi-typescript`, the generated types
will mirror the wire format (snake_case). Keeping the middleware would
create a hidden mismatch between TypeScript's view of the data and the
runtime object, so the middleware will be removed in Phase 2.

**Implications for new code:** be aware that Phase 2 will rename fields
across plugin schemas, table columns, mock data, and the auth context.
Don't entrench new camelCase assumptions that a codegen pass can't see.

See `SEP-963-codegen-followup.md` for the full Phase 2 checklist.

## Testing

Tests run under vitest with MSW:

```bash
pnpm --filter @sep/api test
```

Covered:

- Bearer token attachment (present and absent)
- `ApiError` normalization for 4xx / 5xx / network errors
- Unauthorized handler invocation on 401 (skipped for refresh endpoint)
- Retry predicate: skip 4xx, retry 5xx and network, cap at 3 attempts
- `retryDelay` exponential back-off and ceiling

## What's missing (Phase 2)

Blocked on SEP-957 (OpenAPI spec tuning). See `SEP-963-codegen-followup.md`.

- `openapi-typescript` codegen script + generated types under `src/generated/`
- `openapi-fetch`-based typed request wrapper
- Sample typed health-check hook
- Migration of hand-written types in `src/types/api.ts` to generated
- Removal of `axios-case-converter`
