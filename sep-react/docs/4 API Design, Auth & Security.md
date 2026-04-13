# 4. API Design, Auth & Security

## Guiding Principles

1. **Security is the top priority.** When a decision trades security for convenience, security wins.
2. **API is the product.** The UI is one consumer. External scripts, CLI tools, and future integrations should use the same API.
3. **SEP is the gateway.** Inventory and Tasks sub-apps are internal services. The browser never talks to them directly.
4. **Follow existing patterns where they exist.** The Inventory API at `/api/inventory/` is a mature reference for response models, auth, and pagination.
5. **Don't build what we don't need yet.** No API versioning, no response wrapper, no Bearer tokens for places that still work with cookies.

## URL Structure

### Conventions

- Backend-facing (Jinja2 legacy): stays under `/legacy/*` during transition, removed in Wave 4
- Frontend-facing API: everything under `/api/*`
- Plugin-specific API: `/api/plugins/{plugin_name}/*`
- Core API: `/api/auth/*`, `/api/me/*`, `/api/schema/*` (OpenAPI schema endpoint), etc.
- SSE and streaming endpoints: under `/api/stream-logs/*` and `/api/execution-events/*` (existing pattern)

**Why `/api/plugins/{name}/` and not `/api/{name}/`:**

1. Prevents collision with core routes (e.g., `/api/auth/` could conflict with a hypothetical `auth` plugin)
2. Enables plugin-level middleware — rate limiting, logging, metrics can be applied at the `/api/plugins/*` level without affecting core routes
3. Self-documenting — a developer looking at `/api/plugins/checksums/` immediately knows it's a plugin endpoint
4. Makes the schema discovery endpoint predictable: `/api/plugins/{name}/schema`

### No versioning (for now)

**Decision**: No `/api/v1/` prefix. The API is unversioned.

**Rationale**:

- Existing sub-app APIs (`/api/inventory/`, `/api/tasks/`) are unversioned. Adding a version prefix to new endpoints creates inconsistency.
- SEP has one frontend client (the React SPA we're building) and no external API consumers yet.
- Versioning is ceremony that adds no value until there are external consumers with backward-compatibility requirements.
- When that day comes, we add versioning via a namespace migration, not by pre-baking it now.

**When to revisit**: If and when SEP exposes its API to external consumers (customer scripts, partner integrations, CLI tools maintained outside the SEP team). At that point, introduce `/api/v1/` for the public API surface and leave internal routes unversioned.

## Shared API Router Pattern

A **shared API router** provides consistent middleware (auth, error handling, logging). Each plugin registers its own sub-router.

### Router composition

```python
# app/sep/api/router.py
from fastapi import APIRouter, Depends
from app.sep.deps import IsAuthenticatedDep

api_router = APIRouter(prefix="/api", dependencies=[IsAuthenticatedDep])

# Core routes
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(me_router, prefix="/me", tags=["me"])

# Plugin routes — each under /api/plugins/{name}/
plugins_router = APIRouter(prefix="/plugins")

from app.sep.plugins.checksums.api_routes import router as checksums_router
from app.sep.plugins.backup.api_routes import router as backup_router
# ... etc for all plugins

plugins_router.include_router(checksums_router, prefix="/checksums", tags=["checksums"])
plugins_router.include_router(backup_router, prefix="/backup", tags=["backup"])

api_router.include_router(plugins_router)
```

### Per-plugin API routes

```python
# app/sep/plugins/checksums/api_routes.py
from typing import Annotated
from fastapi import APIRouter, Depends, status
from app.sep.plugins.checksums.models import ChecksumTaskResponse, ChecksumTaskWrite
from app.sep.plugins.checksums.deps import (
    get_checksum_tasks,
    get_checksum_task_by_name,
    build_checksum_task,
)
from app.sep.deps import TaskAPI, InventoryAPI
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.checksums.schema import plugin_schema

router = APIRouter()

# Schema discovery — automatic via shared helper
schema_endpoint(router, plugin_schema)

@router.get("/", response_model=list[ChecksumTaskResponse])
async def list_checksum_tasks(
    tasks_api: TaskAPI,
) -> list[ChecksumTaskResponse]:
    return await get_checksum_tasks(tasks_api)

@router.get("/{task_name}", response_model=ChecksumTaskResponse)
async def get_checksum_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> ChecksumTaskResponse:
    task = await get_checksum_task_by_name(task_name, tasks_api)
    if task is None:
        raise HTTPNotFoundException(f"Checksum task {task_name!r} not found")
    return task

@router.post("/", response_model=ChecksumTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_checksum_task(
    body: ChecksumTaskWrite,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> ChecksumTaskResponse:
    task = await build_checksum_task(body, inventory_api)
    return await tasks_api.post("/", json=task.model_dump())
```

### What the shared router provides

- **Auth**: `IsAuthenticatedDep` applied at the router level. Individual routes inherit it. Admin-only routes can still add `AdminUserDep` on top.
- **Error handling**: Project exceptions (`HTTPNotFoundException`, `HTTPConflictException`, `HTTPBadRequestException`) are converted to appropriate JSON responses by FastAPI's exception handlers.
- **Logging**: Middleware logs request/response with correlation IDs for debugging.
- **Rate limiting** (future): Applied at the `/api/plugins/*` level for shared protection.
- **Schema discovery**: Each plugin's `schema_endpoint(router, plugin_schema)` helper registers a `GET /schema` route that serves the plugin schema as JSON.
- **OpenAPI generation**: Each router carries `tags=["plugin_name"]` so the generated OpenAPI spec groups endpoints by plugin.

## Gateway Pattern

The frontend **never calls the Inventory or Tasks sub-apps directly**. All requests go through SEP plugin routes, which internally proxy to sub-apps via injected dependencies.

### Why

1. **Security**: Controls exactly which sub-app endpoints are exposed. If a sub-app adds an admin endpoint, it doesn't automatically become accessible from the browser.
2. **Consistency**: The frontend has one API base URL. Plugin routes can add plugin-specific filtering, authorization, and validation.
3. **Stability**: If a sub-app's internal contract changes, the plugin route absorbs the change. The frontend sees a stable plugin-specific API.
4. **Audit and logging**: All user-facing API traffic goes through SEP's middleware stack.

### Pattern

```python
# app/sep/plugins/checksums/deps.py
from typing import Annotated
from fastapi import Depends
from app.sep.deps import TaskAPI

async def get_checksum_tasks(
    tasks_api: TaskAPI,
) -> list[dict]:
    """Fetch checksum tasks from Tasks sub-app.

    Filters tasks to only those owned by pt-table-checksum.
    """
    return await tasks_api.get("/", params={"owner": "pt-table-checksum"})
```

The plugin calls `tasks_api.get(...)` — which uses SEP's `RemoteAPI` helper to make a Bearer-authenticated HTTP call to the Tasks sub-app. The user's auth token is automatically forwarded. The frontend only sees `GET /api/plugins/checksums/`.

### What stays direct

**Inventory API is NOT exposed** at `/api/inventory/` to the frontend. It becomes an internal-only service. Existing code that calls `/api/inventory/*` from Jinja2 templates or JavaScript is migrated to call `/api/plugins/*` equivalents.

**Tasks API is NOT exposed** either. Same rationale.

This is a **migration task**: find all references to `/api/inventory/*` and `/api/tasks/*` in templates and JS, and replace them with plugin-level equivalents. Part of Wave 0.

## Response Conventions

### Format

**Bare Pydantic models**, not wrapped responses. Follows the existing Inventory API pattern:

```python
# GOOD — bare resource
@router.get("/", response_model=list[ChecksumTaskResponse])
async def list_tasks(...) -> list[ChecksumTaskResponse]:
    ...

# BAD — avoid
@router.get("/", response_model=ApiResponse[list[ChecksumTaskResponse]])
async def list_tasks(...) -> ApiResponse:
    return ApiResponse(data=tasks, meta={"total": len(tasks)})
```

**Rationale:**

- Consistent with existing sub-app APIs
- FastAPI already provides structured error responses
- Pagination metadata can be returned in response headers or, if needed as JSON, via a `Page[T]` generic model (future)
- Wrapper envelopes add boilerplate to every endpoint and every consumer

### Model naming

Following SEP conventions (already in Inventory API):

- `{Resource}Base` — shared fields used by Write and Response
- `{Resource}Write` — input model for POST/PUT (accepts form data)
- `{Resource}Response` — output model for GET responses (includes computed fields, IDs)
- `{Resource}` — DB table model (with `table=True`)

```python
class ChecksumTaskBase(SQLModel):
    service_id: int
    schema_name: str | None = None
    chunk_size: int = 1000
    replicate_check: bool = True

class ChecksumTaskWrite(ChecksumTaskBase):
    """Input for POST /api/plugins/checksums/"""

class ChecksumTaskResponse(ChecksumTaskBase):
    """Output for GET /api/plugins/checksums/{name}"""
    name: str
    created_at: datetime
    last_run: datetime | None
    status: TaskHistoryStatusEnum | None
```

### Errors

Use SEP project exceptions, not FastAPI's `HTTPException`:

```python
from app.core.exceptions import (
    HTTPNotFoundException,
    HTTPConflictException,
    HTTPBadRequestException,
)

if task is None:
    raise HTTPNotFoundException(f"Task {task_name!r} not found")
```

These are already mapped to structured JSON error responses by SEP's exception handlers.

### Status codes

Always use `status.HTTP_*` constants, never magic numbers:

```python
@router.post(
    "/",
    response_model=ChecksumTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(...):
    ...
```

## Pagination

The backlog includes pagination infrastructure work (SEP-923 core manager, SEP-924 inventory list, SEP-925 tasks list). Wave 0's list endpoints must be paginated from day one, using the pattern those tickets establish.

**Recommended pattern** (to be finalized during Wave 0 implementation):

- Query params: `?page=1&per_page=50&sort=-created_at`
- Response: Either bare `list[T]` with pagination metadata in response headers (`X-Total-Count`, `X-Page`, `X-Per-Page`), or a `Page[T]` generic response model wrapping `items: list[T]`, `total: int`, `page: int`, `per_page: int`
- The React `<TaskHistoryTable>` and schema-driven list view must support both initial load and pagination controls

**Decision deferred to Wave 0** (not critical before). Default preference: `Page[T]` generic model in the response body, because HTTP headers are not type-safe and harder to consume from generated TS types.

## Authentication

### Current state

- **Cookie auth**: SEP app uses `get_access_token_from_cookie()` in `app/sep/deps.py`. Casdoor OAuth returns a JWT, stored in a signed `authToken` cookie (HttpOnly, SameSite=lax, configurable Secure flag).
- **Bearer auth**: Inventory and Tasks sub-apps already support Bearer tokens via `OAuth2PasswordBearer` in `app/api/deps.py`. The SEP app does not.

### Target state — dual support in SEP app

Unify both mechanisms in SEP's `get_current_user()`:

```python
# app/sep/deps.py
async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> User:
    """Return the authenticated user from Bearer token or cookie."""
    # Try Bearer token first (React SPA)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        try:
            return await User.from_jwt(token)
        except (BadSignature, ValidationError) as exc:
            raise HTTPUnauthorizedException from exc

    # Fall back to cookie (legacy Jinja2)
    return await _get_user_from_cookie(request)
```

**What changes**:

- Existing cookie-authenticated Jinja2 routes continue to work unchanged
- New API routes work with either Bearer or cookie — consumer's choice
- The React SPA uses Bearer tokens (obtained via Casdoor OAuth flow, stored in memory)

**What does NOT change**:

- Casdoor remains the identity provider
- JWT format and validation unchanged
- `User.from_jwt()` and `is_active` checks unchanged

### Token lifecycle (recommendation for nachodd)

**Decision**: Token lifecycle is a frontend implementation detail. The backend's responsibility is to accept both Bearer and cookie; how the frontend gets, stores, and refreshes the token is a frontend concern.

**Recommended approach** for the frontend (nachodd decides final):

1. **Login flow**: User is redirected to Casdoor. On return, SEP issues a short-lived access token (e.g., 1 hour) AND a refresh token (e.g., 8 hours).
2. **Storage**: Access token in memory (JS variable inside React Context). Refresh token in an **HttpOnly cookie** that only the refresh endpoint can read.
3. **Silent refresh**: A background timer refreshes the access token before it expires, using the HttpOnly refresh cookie. No user interaction required.
4. **Expiry handling**: If the refresh fails (expired refresh token, revoked session), redirect to login.
5. **Logout**: Call `POST /api/auth/logout` which clears the refresh cookie and blacklists the current access token.

**Why not localStorage for the access token**: XSS-accessible. Memory is safer. Trade-off: full page refresh loses the token and requires a silent refresh dance, which is solvable.

**Why HttpOnly cookie for the refresh token**: Cannot be read by JavaScript, so XSS can't exfiltrate it. Must be same-origin (which we are) and must be accompanied by CSRF protection on the refresh endpoint (use double-submit cookie or Origin header check).

**This is a recommendation**, not a mandate. If nachodd has a better approach, he documents it and we adopt it.

### Casdoor replacement

SEP plans to replace Casdoor with an in-house auth system eventually. Out of scope for this migration. **What matters for this migration**: don't write code that makes replacing Casdoor harder. Keep auth abstractions clean — `User.from_jwt()`, `get_current_user()` — so the backing provider can change without touching plugin routes or React components.

## CSRF

### Current state

- SEP uses the **OWASP Signed Double-Submit Cookie** pattern
- Middleware: `app/sep/middleware/csrf.py`
- CSRF token generated on GET requests, stored in `_csrf` cookie, embedded in Jinja2 forms as a hidden field `csrf-token`
- POST/PUT/DELETE requests validate the token from the form field against the cookie
- SEP-662 made the cookie refresh SPA-compatible (GET refreshes the token, POST doesn't clear it)

### Target state

**Bearer-authenticated requests don't need CSRF.** Bearer tokens aren't sent automatically by the browser — cross-site requests cannot forge them. So:

- **React SPA API calls** (Bearer-authenticated): CSRF middleware does not apply
- **Legacy Jinja2 forms** (cookie-authenticated): CSRF middleware continues to apply, unchanged
- **Wave 4 cleanup**: When the last Jinja2 route is removed, the CSRF middleware is removed entirely

### How the middleware knows which is which

The existing CSRF middleware already skips endpoints decorated with `@csrf_exempt` (used for AJAX proxy routes). The cleaner approach for new API routes:

**Option 1 (preferred)**: CSRF middleware applies only to requests that arrive with the `authToken` cookie and no `Authorization` header. Bearer-authenticated requests bypass it entirely. Implemented in the middleware's `dispatch()` method.

**Option 2 (fallback)**: Every new API route is decorated with `@csrf_exempt`. Works but adds boilerplate.

**Decision**: Option 1. Update the CSRF middleware to check for a Bearer header and skip validation if present. This is a small change to `csrf.py` in Wave 0.

## Security Priorities

<aside>
🔒

Security is the top priority. Design decisions explicitly rank security above convenience.

</aside>

### 1. API surface control

The gateway pattern (SEP proxies Inventory/Tasks) exists specifically to limit the exposed API surface. Every endpoint the frontend can reach is explicitly designed for external consumption. Internal endpoints stay internal.

### 2. Auth on every endpoint by default

`IsAuthenticatedDep` is applied at the `/api/*` router level, not per-route. It's harder to forget. Admin-only routes layer `AdminUserDep` on top. Unauthenticated endpoints (e.g., login, health check) are explicit exceptions that must be documented.

### 3. CSRF protection for cookie-authenticated requests

Don't accidentally turn off CSRF for Jinja2 routes during the transition. The middleware must continue to apply to cookie-authenticated routes.

### 4. Bearer token storage

Frontend stores the access token in memory (not localStorage). Refresh token in HttpOnly cookie. No tokens in URL query params.

### 5. Input validation at the API boundary

Every API endpoint takes a Pydantic input model. No raw dicts, no `Request.json()`, no manual parsing. Pydantic enforces types, required fields, and constraints.

### 6. Output validation

Every API endpoint uses `response_model=`. FastAPI enforces the response structure. Prevents accidental leakage of internal fields.

### 7. Error responses don't leak internals

SEP project exceptions map to structured JSON errors. Stack traces never appear in responses. Debug info only in server logs.

### 8. CORS

**Same-origin deployment means CORS is not configured** — there are no cross-origin requests from the React SPA to the SEP API. If CORS middleware exists in SEP today, it is scoped narrowly (specific origins, specific methods). It is NOT set to `allow_origins=["*"]`.

### 9. Rate limiting (future)

The shared API router is the right place to apply rate limiting middleware later. Not Wave 0 scope, but the architecture supports it trivially.

### 10. Audit logging

The shared API router logs every request with user ID, endpoint, status, and duration. For state-changing requests (POST/PUT/DELETE), also log the request body (with sensitive fields masked). Supports future audit requirements without retrofitting.

### 11. AGPL license on `@percona/percona-ui`

As noted in the Context page, the shared component library is AGPL-3.0. The license was reviewed and cleared for SEP to adopt as a hard dependency. Ongoing obligations (fixes contributed upstream, non-compatible code isolated) are documented in the Context page.

### 12. Secrets in cookies and tokens

The existing `itsdangerous` signing of the access token stays. Cookies use `HttpOnly`, `SameSite=lax`, and `Secure` (in production). JWT signatures validated on every request.

## Future API Concerns to Design Around

The backlog signals upcoming API work that the design must accommodate:

- **Pagination** (SEP-923/924/925): The `list_*` endpoints must be paginated from day one.
- **Connectivity checks** (SEP-927): Pre-execution and on-demand connectivity checks. Plugin API routes may expose a `POST /api/plugins/{name}/pre-check` endpoint that runs checks without creating a task. The schema system supports "pre-check" form sections.
- **Data masking** (SEP-511): Log streaming endpoints need to support masked/unmasked modes. The `useTaskLogs()` hook and SSE payload need a "decrypted" flag.
- **Class-based viewsets** (SEP-187): Plugins may eventually declare their CRUD operations in a class-based style similar to DRF viewsets. The shared router pattern accommodates this — a plugin provides its router, however it's built.

None of these are Wave 0 scope, but the API design does not foreclose them.
