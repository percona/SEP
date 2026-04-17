# SEP-963 — Phase 2 follow-up (codegen + middleware removal)

Phase 1 of SEP-963 landed the axios client, `createQueryClient()`,
error normalization, dev logging, and MSW-based tests.

Phase 2 is **blocked on SEP-957** (OpenAPI spec tuning & multi-spec
strategy). Once SEP-957 merges, execute the checklist below.

## Context at time of writing (2026-04-19)

- Backend exposes four FastAPI apps, each with its own OpenAPI spec:
  - `/api/` — main
  - `/api/inventory/`
  - `/api/tasks/`
  - `/` — SEP UI
- The wire format is snake_case.
- Frontend currently runs `axios-case-converter` to auto-convert
  camelCase ↔ snake_case at the axios boundary. Plugin schemas, table
  column keys, mock data (`mockChecksumTasks`), and the auth context
  all assume camelCase at the application layer.
- SEP-957 has not yet decided whether to publish one merged spec or
  keep per-service specs. The codegen script below must support both.

## Policy decisions already made

- **Drop `axios-case-converter` in Phase 2** (not Phase 1). Dropping
  it earlier would cascade through every plugin without a live backend
  to verify snake_case wire shapes, and generated types will provide
  the canonical field names anyway.
- **Typed request layer**: use `openapi-fetch` on top of
  `openapi-typescript`-generated `paths`. Keep the existing `apiClient`
  axios instance for places that still need interceptor features
  (logging, token injection, error normalization); expose a typed
  wrapper that shares those interceptors.
- **Committed generated types**: `src/generated/*.ts` is committed so
  builds don't require a running backend. Mark the files as
  `linguist-generated` in `.gitattributes` to keep diffs clean on GitHub.

## Checklist

### 1. Remove `axios-case-converter`

1. Remove the `axios-case-converter` dependency from
   `frontend/packages/api/package.json`.
2. In `src/client.ts`, drop `applyCaseMiddleware(...)` and use
   `axios.create(...)` directly.
3. Update hand-written types in `src/types/api.ts` to snake_case
   (or delete them in favor of generated equivalents, step 3 below).
4. Update consumers that currently read camelCase fields from the API:
   - `frontend/packages/shell/src/contexts/auth.tsx` — `accessToken`,
     `refreshToken`, `expiresIn`, `isAdmin`, `fullName`.
   - `frontend/packages/shell/src/layouts/TheHeader.tsx` — `fullName`.
   - `frontend/packages/checksums/src/mock-data.ts` and
     `frontend/packages/checksums/src/schema.ts` — `lastRun`,
     `chunkSize`, `replicateCheck` (and any other snake_cased fields
     the backend actually exposes).
   - Any new plugins added between Phase 1 and Phase 2.
5. Re-run the MSW test suite. Add cases that verify a request body
   containing `{ chunk_size: 1 }` reaches the server as-is (no
   transform).

### 2. Add codegen dependencies and script

1. Add devDependencies:
   ```
   openapi-typescript   ^7.x
   ```
   And runtime dependency:
   ```
   openapi-fetch        ^0.x
   ```
2. Create `frontend/packages/api/scripts/codegen.ts`:

   ```ts
   // Accepts a configurable spec source list so it handles either a
   // merged spec or per-service specs — SEP-957's decision does not
   // change this file.
   type SpecSource = { name: string; source: string };

   const SPECS: SpecSource[] = [
     { name: 'main', source: 'http://localhost:8000/api/openapi.json' },
     { name: 'inventory', source: 'http://localhost:8000/api/inventory/openapi.json' },
     { name: 'tasks', source: 'http://localhost:8000/api/tasks/openapi.json' },
     { name: 'sep', source: 'http://localhost:8000/openapi.json' },
   ];
   ```

   The script iterates over `SPECS`, calls `openapiTS(source)` for
   each, and writes `src/generated/{name}.ts`. If SEP-957 chooses the
   merged-spec route, collapse `SPECS` to a single entry.

3. Register the script in `package.json`:
   ```json
   "scripts": {
     "codegen": "tsx scripts/codegen.ts"
   }
   ```
4. Run `pnpm --filter @sep/api codegen` and commit the output.
5. Add `src/generated/** linguist-generated=true` to
   `frontend/.gitattributes` (create the file if absent).

### 3. Migrate hand-written types to generated

1. Delete the hand-written types in `src/types/api.ts` (`User`,
   `OAuthTokenResponse`, `PaginatedResponse`, `ApiErrorResponse`).
2. Re-export the equivalents from `src/generated/main.ts` through
   `src/index.ts`.
3. Update consumers to import from `@sep/api` (no source change
   expected — barrel names should stay stable).

### 4. Add the typed request wrapper

1. In `src/typed-client.ts`, wire `openapi-fetch` on top of the
   existing axios instance (or a fetch adapter) so interceptors still
   apply. Reference:
   ```ts
   import createClient from 'openapi-fetch';
   import type { paths } from './generated/main';
   export const api = createClient<paths>({ baseUrl: '/api' });
   ```
2. Decide whether the typed wrapper replaces `apiClient` or sits next
   to it. Recommendation: keep `apiClient` for the auth functions and
   anything that needs axios-specific features; use `api` for all new
   hooks.
3. Export `api` from the barrel.

### 5. Sample typed hook

1. Add `src/hooks/useHealthCheck.ts` (or whichever endpoint SEP-957
   settles on) demonstrating:
   - import `paths` from `./generated/…`
   - typed call via the wrapper
   - `useQuery` with typed return
   - `ApiError` handling

### 6. Documentation

1. Update the README's "What's missing" section to reflect Phase 2
   being done.
2. Add a "How to add a new hook" walkthrough to the README.
3. Delete this follow-up file.

## Risks and notes

- **Spec drift**: committing generated files means the backend and
  frontend can fall out of sync silently. Add a CI check that runs
  `pnpm --filter @sep/api codegen` and fails if the working tree
  changes.
- **File size**: monitor `src/generated/*.ts` size. If it becomes
  unwieldy, split per-tag (OpenAPI tags → separate modules).
- **Auth module overlap**: `postLogin` / `postRefresh` /
  `fetchCurrentUser` in `src/auth.ts` are hand-written. Once codegen
  lands, consider replacing them with typed calls and deleting the
  hand-written module. Confirm with the SEP-961 owner that doing so
  doesn't break the `AuthProvider` contract.
- **`axios-case-converter` removal is a breaking change** for every
  consumer. Land it in a single PR with all plugin updates so the
  frontend never sits in an inconsistent state.
