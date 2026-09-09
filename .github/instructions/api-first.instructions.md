---
applyTo: "app/sep/api/**/*.py,app/sep/apps/framework/**/*.py,app/sep/apps/**/api_routes.py,app/sep/apps/**/schema.py,app/sep/apps/**/views.py,app/sep/apps/**/spec.py,frontend/packages/framework/**,frontend/packages/api/**,frontend/packages/apps/**,frontend/packages/shell/**"
---

# API-First + React

The UI is a schema-driven React SPA backed by a SEP API gateway. The server-rendered Jinja2 layer it replaced has been removed, so there is no longer a legacy path to fall back to or keep at parity — every UI surface is React over the API. PRs on these paths must follow the rules below.

## Rule 1 — Gateway pattern (most-violated)

**The frontend NEVER calls the Inventory or Tasks sub-apps directly.** All FE traffic goes through SEP routes — app (`/api/apps/{name}/`) or SEP-level core (`/api/sep/...`) — which proxy to sub-apps via injected deps (`tasks_api: TaskAPI`, `inventory_api: InventoryAPI`).

Flag any new FE→`/api/tasks/*` or FE→`/api/inventory/*` traffic, and any two parallel FE fetches merging data from both sub-apps client-side (should be one SEP route merging server-side).

Use `/api/sep/<resource>/` when data is shared across apps (executor hosts, current-user, global flags). Otherwise `/api/apps/{name}/<resource>/`.

**Passthrough vs transforming proxy.** A passthrough route (single upstream call, no merge/transform/projection) returns `dict[str, Any]` / `list[dict[str, Any]]` — NOT a SEP-owned model mirroring the upstream 1:1. Flag any new `{Resource}Response` alongside a bare `tasks_api.get(...)` / `inventory_api.get(...)` where no field is added, dropped, renamed, or projected. A transforming proxy (merges upstreams, projects fields, adds SEP-only data) keeps its SEP-owned model. **Carve-out:** when the FE consumer is already typed by the upstream sub-app's OpenAPI/TS codegen, a SEP mirror only duplicates that typing — still add the proxy (Rule 1 stands) but return `dict[str, Any]`; the consumer's existing typed contract keeps applying.

## Rule 2 — Schema-driven by default

Default: declare the presentation model in `app/sep/apps/{name}/` and register an app router — **no React package**. `SchemaDrivenAppResolver` (the terminal `*` route in `frontend/packages/shell/src/router.tsx`) mounts a schema-driven app at render from the `GET /api/apps` payload; only bespoke apps take an entry in `CUSTOM_APP_REGISTRY` (`frontend/packages/shell/src/appRegistry.tsx`). Flag any new `frontend/packages/apps/<name>/` package whose component body is just `<SchemaDrivenApp pluginName="…" />` — that package is the resolver's job. The schema may be *derived* rather than hand-written: the `task` scaffold flavor emits `models.py` + `spec.py` + `views.py` and no `schema.py`, and archives, checksums, backup_pg and mysql_backups each carry their presentation bundle as a `Views(...)` in `views.py` feeding the derived `GET /schema`. Review the `Views` bundle wherever there is no `schema.py`; a hand-written `AppSchema` alongside a `Views` bundle is the drift to flag.

**Custom React (escape hatch)** requires (a) no `AppSchema` shape covers the app AND (b) the missing extension wouldn't benefit any other planned app. Only **alerts** and **report** qualify today. **alters** and **archives** are schema-driven via the DSL primitives (conditional rules + side-actions + derived tasks) — reject any proposal to revert either to custom React.

**snippets** is schema-driven for its forms and execution but keeps one custom-React screen, `SnippetsListPage`. Its list needs whole-dataset server-side search, a service-type facet, an approval filter, and server-side sort — none of which the `<SchemaListView>` / `ListView` schema stack exposes today (that stack drives only server-side pagination). This is a scoped, temporary exception: when the schema stack grows filter/facet/search/sort primitives, fold these into it and migrate the page onto `<SchemaListView>`. Reject any *new* bespoke list screen that a schema-stack primitive could serve.

After an app adopts `derive_crud_routes` (deleting its hand-written `api_routes.py`), the old `<App>CreateResponse = derive_create_response_model(...)` line in `models.py` and its now-unused import become dead code that lint won't flag (the assignment still references the import). Flag the leftover — a stray model sharing the auto-derived OpenAPI component name is a latent collision.

## Rule 3 — Reuse the framework layer

The framework layer exists so app migrations don't reinvent chaining, log streaming, history, selectors, scheduling, alert-on-fail. **Custom React apps still consume framework components** — only the form is custom. `@sep/framework` already ships primitives for each of these: history tables and status badges, chain display/builder, the log viewer + `useTaskLogs()`/`useExecutionEvents()`, cascading service/schema/table/host selectors, `<AlertOnFailField>`, schedule panels, the `<SchemaFormRenderer>`/`<SchemaListView>`/`<SchemaDrivenApp>` schema stack, the `useHosts`/`useServices`/`useSchemas`/`useTables` data hooks, and the API client (axios + auth interceptor + `openapi-typescript` codegen + React Query). Auth/notification context (`<AuthProvider>`/`useAuth()`, `<NotificationProvider>`/`useNotification()`) lives in `@sep/shell`, not `@sep/framework`.

Source of truth: `frontend/packages/framework/src/index.ts` — check it for the exact export names before adding a parallel implementation, which needs a sentence-level justification per primitive.

## Rule 4 — URL & response conventions

- `/api/apps/{name}/` app routes (default); `/api/sep/<resource>/` SEP-level core; `/api/oauth/*`, `/api/users/*` (current user is `/api/users/me`), `/api/config/*` core (`app/api/main.py`).
- `/api/inventory/*`, `/api/tasks/*` are internal-only after Wave 3; FE never calls them.
- **No versioning** — no `/api/v1/`.
- **Bare Pydantic responses** — `response_model=ConnectivityCheckResponse` (or `list[...]`, e.g. `app/sep/apps/inventory/api_routes.py`), not `ApiResponse[...]` envelope wrappers.
- **Pagination has no house shape.** Neither an `X-Total-Count` header form nor a `Page[T]` generic was ever adopted — every live `api_routes.py` returns a bare `list[...]`. A PR introducing pagination picks one and says why in the description; flag a `Page[T]`-style wrapper landed silently as if it were the established convention.
- **Model naming**: `{Resource}Base` → `{Resource}Write` (input) → `{Resource}Response` (output) → `{Resource}` (DB table). Reject `*Request` / `*Input` / `*Output` / `*Payload` suffixes.
- **Exceptions & status codes**: use SEP project exceptions (`HTTPNotFoundException`, `HTTPConflictException`, `HTTPBadRequestException`, `HTTPUnauthorizedException`), never `fastapi.HTTPException` directly; status codes via `status.HTTP_*` constants, never bare integers.

## Rule 5 — Auth

**Bearer is the credential for `/api/*`.** The cookie-session path that coexisted with it belonged to the Jinja SSR layer and went with it. The one cookie that still matters is the **ambient provider session** (PMM / Grafana): when `AMBIENT_SESSION_SSO_ENABLED` is on and the active provider supports it, `resolve_ambient_session_token()` / `resolve_ambient_exchange_token()` (`app/sep/deps.py`) exchange that provider cookie for a SEP token pair or a short-lived bearer. It is an auto-login source, not a parallel session for route auth — an absent session, a rejected session, and a provider outage are deliberately indistinguishable and all deny. Don't introduce a new flow.

**Cross-site protection is the Bearer requirement itself**, not a CSRF token: `require_bearer_for_unsafe_methods` forces `Authorization: Bearer` on mutating methods, which browsers never attach cross-site. There is no `validate_csrf` / `@csrf_exempt` to add or skip. **Never store access tokens in localStorage** — in-memory + HttpOnly refresh cookie + silent refresh (XSS is the threat).

## Mock / placeholder data propagation

When a diff surfaces `MOCK_*`/`FAKE_*`/`EXAMPLE_*`/`STUB_*` data the running app would render to real users — or wires a component off placeholder data onto a real source — either fold the real-data wiring into the PR or open a tracked follow-up. Don't let placeholder constants reach a user-facing render path silently.
