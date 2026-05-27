# Bug Report: SPA Login Returns "Invalid username or password" After Merge

## Summary

After merging `origin/main` into `MUM`, the React SPA login returns **"Invalid username or password"** for valid credentials. The backend receives the `POST /api/oauth/login` request but responds with **HTTP 303 See Other** (a redirect to `/login`) instead of a JSON token.

## Environment

- Branch: `MUM`
- Affected commit: merge `653c3f76` (`Merge origin/main into MUM`)
- Regression introduced by: `git checkout --theirs app/sep/main.py` during the merge
- Commit that originally fixed this: `2f376b3` (`Fix SPA login: mount core API routes and return JSON errors for API paths`)

## Steps to Reproduce

1. Run the stack with the merged `app/sep/main.py` (as produced by `git checkout --theirs`).
2. Open the React frontend at `https://localhost:8444`.
3. Enter valid credentials and click **Login**.
4. Observe "Invalid username or password" toast despite correct credentials.

## Expected Behaviour

`POST /api/oauth/login` returns HTTP 200 with a JSON body containing `access_token`.

## Actual Behaviour

`POST /api/oauth/login` returns HTTP 303 redirecting to `/login`. The SPA `axios` interceptor treats any non-2xx response as an auth failure and surfaces the generic error message.

## Root Cause

`sep_app` (started by `python -m app.sep.main`) runs as a standalone FastAPI application. The core OAuth/users/config routes live in `app.api.main.api_router` (`core_api_router`) and must be explicitly included in `sep_app`. The original fix in `2f376b3` did this; however, the merge conflict resolution chose `origin/main`'s `app/sep/main.py` verbatim, silently dropping:

1. `from app.api.main import api_router as core_api_router` — the import
2. `sep_app.include_router(core_api_router)` — the router registration
3. The expanded `JSON_API_PATH_PREFIXES` (`/api/oauth/`, `/api/users/`, `/api/config/`)
4. The `try/except` guard around `get_current_user` in `internal_error_handler`
5. The JSON response path in `auth_provider_exception_handler`

Without item 1+2, `POST /api/oauth/login` matches no route and FastAPI falls through to the 404 handler, which redirects unauthenticated requests to `/login` (HTTP 303). Without item 3, the 404 handler cannot distinguish API paths from HTML paths and always redirects.

## Fix

Re-apply all five changes from `2f376b3` to `app/sep/main.py`:

```diff
+from app.api.main import api_router as core_api_router
 from app.sep.api.router import api_router

-JSON_API_PATH_PREFIXES: tuple[str, ...] = ("/api/plugins/", "/api/sep/")
+JSON_API_PATH_PREFIXES: tuple[str, ...] = ("/api/plugins/", "/api/sep/", "/api/oauth/", "/api/users/", "/api/config/")

+sep_app.include_router(core_api_router)
 sep_app.include_router(api_router)

-    user = await get_current_user(request)
+    try:
+        user = await get_current_user(request)
+    except Exception:
+        user = None

-) -> RedirectResponse:
+) -> Response:
     """Handle exceptions raised by auth providers."""
     logger.exception("Error connecting to auth provider:", exc_info=exc)
+    if request.url.path.startswith(JSON_API_PATH_PREFIXES) or is_bearer_authenticated(request):
+        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
```

## Prevention

When merging `origin/main` into feature branches that contain `app/sep/main.py` modifications, **do not blindly `git checkout --theirs`** this file. The MUM branch carries permanent additions to `sep_app` (`core_api_router`, `JSON_API_PATH_PREFIXES`, `_TASK_INFRA_PLUGINS`) that must survive every merge.

Consider adding a merge driver or a CI check that asserts `core_api_router` is present in `app/sep/main.py`.
