---
applyTo: "app/**/*.py"
---

# Security — Manual-Judgment Checks

Bandit (ruff `S` rules) catches generic findings automatically — flag those only if the PR introduces them in code the linter doesn't cover. The checks below need human judgment.

## Must flag (Critical)

- **Hardcoded secrets** — API keys, OAuth client secrets, DB credentials, JWT signing keys, passwords. Secrets must come from environment variables (optionally via a local `.env`) and must never be committed to `settings.yaml`, source code, fixtures, or config. `.env` is gitignored.
- **Raw SQL with user-controlled input** — `session.execute(text(...))` or f-string SQL where any part comes from a request parameter, form field, URL path, header, or JSON body. All DB access goes through CRUD managers, which parameterise.
- **`| safe` filter in Jinja2 templates** with user-controlled data defeats auto-escaping. `Markup()` carries the same risk.
- **Missing CSRF validation** on a new state-changing endpoint (POST / PUT / DELETE / PATCH). Need `validate_csrf` in the dependency chain — decorator-level `dependencies=[IsCsrfValidated]`, router-level, or shared parent router. Trace the full chain.
- **Disabled SSL verification** — `verify=False` on `requests.*` / `httpx.*` / `aiohttp.*`.
- **Unsafe deserialization of untrusted data** — any `loads()` from a library that allows arbitrary code execution during deserialization, on inputs sourced outside this service. Prefer JSON.
- **Unvalidated file paths** — `open(user_input)`, `Path(user_input).read_text()`, `shutil.copy(user_input, ...)` without normalisation against an allowed root. Also flag bespoke path/reference resolvers (custom `file://`-style schemes, bare `resolve_relative_path()` calls, hand-joins to `BASE_DIR`) that skip a `resolved.is_relative_to(BASE_DIR)` containment check — `resolve_relative_path()` does NOT itself contain, so any caller adding user input must add the check. The obvious `open()` pattern is not the only vector.

## Should flag (Important)

- **Missing authentication on a new endpoint** — every new route needs either `dependencies=[IsAuthenticated]` / `dependencies=[IsApiAuthenticated]`, a `CurrentUser` / `ApiAdminUser` parameter, OR a router-level dependency that enforces it.
- **Auth declared only via parameter side-effect** — a route with `user: CurrentUser` / `user: ApiAdminUser` in its signature but no `dependencies=[...]` declaration in the decorator relies on the parameter as a security gate. The next refactor that touches the parameter silently removes auth. When sibling routes on the same router declare `dependencies=[...]` explicitly, the new route must too.
- **Overly broad exception handling** — `except Exception: pass` or `except: ...` that swallows security-relevant failures. Catch specific types, or re-raise after logging.
- **Logging sensitive data** — passwords, tokens, JWTs, OAuth secrets, full request bodies on auth endpoints, PII. Flag `logger.info(f"... {token} ...")` / `logger.debug(request.json())` on auth or user-facing endpoints.
- **Missing input validation on new form fields** — every new form field needs a Pydantic model with appropriate constraints (`NonEmptyStr`, `StringConstraints(max_length=...)`, a custom field type like `StrHttpUrl`). Raw `str` with no constraint on user-controllable input is a flag.
- **Debug/development code left in** — `breakpoint()`, `pdb.set_trace()`, hardcoded `DEBUG = True`. Ruff `T20` catches `print`.
- **Fail-open default on an access/reachability gate** — a missing state row (`Manager.first(...) is None`, `dict.get(key, <truthy>)`) resolving to *enabled / granted* rather than *denied / disabled*. The absent case must fail closed; also confirm any UI/sidebar projection of the same state shares the gate's restrictive default. Cosmetic / non-security toggles are exempt.
- **Localized security guard without a sibling sweep** — when a PR *adds* a guard (`validate_csrf`, `IsApiAuthenticated`, a SQL-parameterization fix) to one instance of a repeatable pattern (per-app `app/sep/apps/*/api_routes.py`, per-handler validators, per-query builders), the local fix usually signals a systemic gap. Grep siblings for the same guard's absence and surface it. Carve-outs: middleware additions (single integration point), per-field model validators.
- **No rate-limiting consideration on new endpoints** — flag its absence on auth, password-reset, API-key, or other abuse-prone endpoints.
- **Auth-client error taxonomy** — a login/token client that maps *all* non-2xx upstream responses to "invalid credentials". Only `401` means bad credentials; `5xx` / `429` / timeouts are upstream failures and must surface as such, not collapse into an auth error (which masks outages and throttling as bad passwords).

## Context-dependent

- **`subprocess`** — input sanitized, `shell=True` not used, args passed as a list.
- **External API calls** — responses validated by a Pydantic model before downstream use.
- **File uploads** — content-type / extension / size validated before persistence.
- **Redirect URLs** — enforce same-origin containment: reject protocol-relative `//host` and backslashed `/\host`, and require an empty `urlsplit(value).netloc`. A path-shape check or `URIPath` alone is insufficient — both admit `//host`, which browsers follow off-origin.

## Input validation primitives to prefer

`app/core/utils/fields.py` defines validation-at-construction-time field types. Prefer them over raw `str` + `field_validator`:

- URLs: `StrHttpUrl`, `StrAnyUrl`, `StrDatabaseUrl`, `StrAsyncDatabaseUrl`.
- File/dir paths: `RelativeFilePathField`, `RelativeDirectoryPathField`, `URIPath`.
- Non-empty: `NonEmptyStr`.

## CSP and security headers

`SecurityHeadersMiddleware` adds CSP with per-request nonce, HSTS, X-Frame-Options. New inline `<script>` must use `nonce="{{ request.state.csp_nonce }}"`. Flag new inline scripts without the nonce.
