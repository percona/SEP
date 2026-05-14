---
applyTo: "app/sep/api/**/*.py,app/sep/plugins/framework/**/*.py,app/sep/plugins/**/api_routes.py,app/sep/plugins/**/schema.py,frontend/packages/framework/**,frontend/packages/api/**,frontend/packages/plugins/**,frontend/packages/shell/**"
---

# API-First + React Migration

Mid-migration from server-rendered Jinja2 to a schema-driven React SPA backed by a SEP API gateway. PRs on these paths must follow the rules below.

## Rule 1 — Gateway pattern (most-violated)

**The frontend NEVER calls the Inventory or Tasks sub-apps directly.** All FE traffic goes through SEP routes — plugin (`/api/plugins/{name}/`) or SEP-level core (`/api/sep/...`) — which proxy to sub-apps via injected deps (`tasks_api: TaskAPI`, `inventory_api: InventoryAPI`).

Flag any new FE→`/api/tasks/*` or FE→`/api/inventory/*` traffic, and any two parallel FE fetches merging data from both sub-apps client-side (should be one SEP route merging server-side).

Use `/api/sep/<resource>/` when data is shared across plugins (executor hosts, current-user, global flags). Otherwise `/api/plugins/{name}/<resource>/`.

## Rule 2 — Schema-driven by default

Default: define a `PluginSchema` in `app/sep/plugins/{name}/schema.py`, register a plugin router, ship a React package that's a pass-through to `<SchemaDrivenPlugin pluginName="…" />`.

**Custom React (escape hatch)** requires (a) no `PluginSchema` shape covers the plugin AND (b) the missing extension wouldn't benefit any other planned plugin. Only **alerts** and **report** qualify today.

## Rule 3 — Reuse the framework layer

The framework layer exists so plugin migrations don't reinvent chaining, log streaming, history, selectors, scheduling, alert-on-fail. **Custom React plugins still consume framework components** — only the form is custom. Existing primitives in `@sep/framework`: `<TaskHistoryTable>`, `<StatusBadge>`, `<ChainDisplay>`, `<ChainBuilder>`, `<TaskLogViewer>` + `useTaskLogs()`, `useExecutionEvents()`, `<ServiceSelector>`/`<SchemaSelector>`/`<TableSelector>` (cascading), `<HostSelector>` (mock data — see below), `<AlertOnFailField>`, `<ScheduledTasksPanel>`, `<SchemaFormRenderer>`, `<SchemaDrivenPlugin>`, `<PluginListPage>`, `<AuthProvider>`/`useAuth()`, `<NotificationProvider>`/`useNotification()`, the API client (axios + auth interceptor + `openapi-typescript` codegen + React Query).

Source of truth: `frontend/packages/framework/src/index.ts`. A diff that adds a parallel implementation needs a sentence-level justification per primitive.

## Rule 4 — URL & response conventions

- `/api/plugins/{name}/` plugin routes (default); `/api/sep/<resource>/` SEP-level core; `/api/auth/*`, `/api/me/*`, `/api/schema/*` core.
- `/api/inventory/*`, `/api/tasks/*` are internal-only after Wave 3; FE never calls them.
- **No versioning** — no `/api/v1/`.
- **Bare Pydantic responses** — `response_model=ChecksumTaskResponse` (or `list[...]`), not `ApiResponse[...]` envelope wrappers.
- **Model naming**: `{Resource}Base` → `{Resource}Write` (input) → `{Resource}Response` (output) → `{Resource}` (DB table). Reject `*Request` / `*Input` / `*Output` / `*Payload` suffixes.

## Rule 5 — Dual auth

Cookie auth (Jinja2) and Bearer auth (React SPA) coexist in `app/sep/deps.py::get_current_user()`. **Both** work for every `/api/*` route. Don't introduce a new flow.

**CSRF skips Bearer-authenticated requests** — the middleware checks for a Bearer header and skips when present. New API routes don't need `@csrf_exempt`. **Never store access tokens in localStorage** — in-memory + HttpOnly refresh cookie + silent refresh (XSS is the threat).

## Mock data propagation

`<HostSelector>` uses `MOCK_HOSTS` until SEP-1088. When a diff surfaces it to real users — or touches `MOCK_*`/`FAKE_*`/`EXAMPLE_*` data the app would render — either fold the real-data wiring into the PR or open a follow-up.
