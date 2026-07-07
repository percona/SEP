---
applyTo: "app/sep/api/**/*.py,app/sep/apps/framework/**/*.py,app/sep/apps/**/api_routes.py,app/sep/apps/**/schema.py,frontend/packages/framework/**,frontend/packages/api/**,frontend/packages/apps/**,frontend/packages/shell/**"
---

# API-First + React Migration

Mid-migration from server-rendered Jinja2 to a schema-driven React SPA backed by a SEP API gateway. PRs on these paths must follow the rules below.

## Rule 1 — Gateway pattern (most-violated)

**The frontend NEVER calls the Inventory or Tasks sub-apps directly.** All FE traffic goes through SEP routes — app (`/api/plugins/{name}/`) or SEP-level core (`/api/sep/...`) — which proxy to sub-apps via injected deps (`tasks_api: TaskAPI`, `inventory_api: InventoryAPI`).

Flag any new FE→`/api/tasks/*` or FE→`/api/inventory/*` traffic, and any two parallel FE fetches merging data from both sub-apps client-side (should be one SEP route merging server-side).

Use `/api/sep/<resource>/` when data is shared across apps (executor hosts, current-user, global flags). Otherwise `/api/plugins/{name}/<resource>/`.

**Passthrough vs transforming proxy.** A passthrough route (single upstream call, no merge/transform/projection) returns `dict[str, Any]` / `list[dict[str, Any]]` — NOT a SEP-owned model mirroring the upstream 1:1. Flag any new `{Resource}Response` alongside a bare `tasks_api.get(...)` / `inventory_api.get(...)` where no field is added, dropped, renamed, or projected. A transforming proxy (merges upstreams, projects fields, adds SEP-only data) keeps its SEP-owned model.

## Rule 2 — Schema-driven by default

Default: define an `AppSchema` in `app/sep/apps/{name}/schema.py`, register an app router, ship a React package that's a pass-through to `<SchemaDrivenApp pluginName="…" />`.

**Custom React (escape hatch)** requires (a) no `AppSchema` shape covers the app AND (b) the missing extension wouldn't benefit any other planned app. Only **alerts** and **report** qualify today. **alters** and **archives** are schema-driven via the DSL primitives (conditional rules + side-actions + derived tasks) — reject any proposal to revert either to custom React.

After an app adopts `derive_crud_routes` (deleting its hand-written `api_routes.py`), the old `<App>CreateResponse = derive_create_response_model(...)` line in `models.py` and its now-unused import become dead code that lint won't flag (the assignment still references the import). Flag the leftover — a stray model sharing the auto-derived OpenAPI component name is a latent collision.

## Rule 3 — Reuse the framework layer

The framework layer exists so app migrations don't reinvent chaining, log streaming, history, selectors, scheduling, alert-on-fail. **Custom React apps still consume framework components** — only the form is custom. `@sep/framework` already ships primitives for each of these: history tables and status badges, chain display/builder, the log viewer + `useTaskLogs()`/`useExecutionEvents()`, cascading service/schema/table/host selectors, `<AlertOnFailField>`, schedule panels, the `<SchemaFormRenderer>`/`<SchemaListView>`/`<SchemaDrivenApp>` schema stack, the `useHosts`/`useServices`/`useSchemas`/`useTables` data hooks, and the API client (axios + auth interceptor + `openapi-typescript` codegen + React Query). Auth/notification context (`<AuthProvider>`/`useAuth()`, `<NotificationProvider>`/`useNotification()`) lives in `@sep/shell`, not `@sep/framework`.

Source of truth: `frontend/packages/framework/src/index.ts` — check it for the exact export names before adding a parallel implementation, which needs a sentence-level justification per primitive.

## Rule 4 — URL & response conventions

- `/api/plugins/{name}/` app routes (default); `/api/sep/<resource>/` SEP-level core; `/api/auth/*`, `/api/me/*`, `/api/schema/*` core.
- `/api/inventory/*`, `/api/tasks/*` are internal-only after Wave 3; FE never calls them.
- **No versioning** — no `/api/v1/`.
- **Bare Pydantic responses** — `response_model=ChecksumTaskResponse` (or `list[...]`), not `ApiResponse[...]` envelope wrappers.
- **Model naming**: `{Resource}Base` → `{Resource}Write` (input) → `{Resource}Response` (output) → `{Resource}` (DB table). Reject `*Request` / `*Input` / `*Output` / `*Payload` suffixes.
- **Exceptions & status codes**: use SEP project exceptions (`HTTPNotFoundException`, `HTTPConflictException`, `HTTPBadRequestException`, `HTTPUnauthorizedException`), never `fastapi.HTTPException` directly; status codes via `status.HTTP_*` constants, never bare integers.

## Rule 5 — Dual auth

Cookie auth (Jinja2) and Bearer auth (React SPA) coexist in `app/sep/deps.py::get_current_user()`. **Both** work for every `/api/*` route. Don't introduce a new flow.

**CSRF skips Bearer-authenticated requests** — the middleware checks for a Bearer header and skips when present. New API routes don't need `@csrf_exempt`. **Never store access tokens in localStorage** — in-memory + HttpOnly refresh cookie + silent refresh (XSS is the threat).

## Mock / placeholder data propagation

When a diff surfaces `MOCK_*`/`FAKE_*`/`EXAMPLE_*`/`STUB_*` data the running app would render to real users — or wires a component off placeholder data onto a real source — either fold the real-data wiring into the PR or open a tracked follow-up. Don't let placeholder constants reach a user-facing render path silently.
