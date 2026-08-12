---
applyTo: "app/**/*.py"
---

# Architecture & Patterns

## Sub-application ownership

New code lives in the sub-application of the **primary settings/config object it reads**, not where it's scheduled from.

| Sub-app | Owns | Settings |
|---|---|---|
| `app/inventory/` | Nodes, services, schemas, tables, inventory sync | `inventory_settings` |
| `app/tasks/` | Task execution, Nomad/local executors, executor-config-driven side effects, executor periodic tasks | `tasks_settings` |
| `app/sep/` | Web UI, apps, OAuth, alerts, cross-cutting concerns not owned by a single domain | `sep_settings` |

Red flags:

- A new function under `app/sep/` reads `tasks_settings.*` or `inventory_settings.*`, or imports `NomadExecutor` / `LocalExecutor` / `BaseExecutor`.
- A new entry in `app/sep/db/seed.py::get_system_periodic_tasks()` whose task operates on tasks/inventory state. `app/sep/` seeds via the `get_system_periodic_tasks()` builder; sub-apps (`app/tasks/`, `app/inventory/`) each have their own `celery.py` and `db/seed.py::SYSTEM_PERIODIC_TASKS` — use the matching pair.
- A test for a tasks-flavored periodic task landing under `tests/app/sep/` instead of `tests/app/tasks/`.
- A module in `app/tasks/` or `app/inventory/` hard-codes a specific app's parser, schema, magic strings, or enrichment for one app — even wrapped as "generic infra". The tell: a helper returning app-specific content for one app and `None` for the rest. App knowledge stays in the app's package; the generic service holds only the registration/hook mechanism. (The inverted *import* — `app/tasks` or `app/inventory` importing `app.sep.apps` — is caught mechanically; app knowledge **copied** into the generic service imports nothing and stays a reviewer call.)
- **A new per-app block in a shared core registry.** A file every app edits to register its own contribution is the same accretion smell wherever it appears — currently `app/sep/celery.py`, `tests/app/factories.py`, and `app/sep/db/seed.py`. Adding a *new* per-app block to any of them must be **justified** ("why not an app-package seam?") even when a precedent block already lives there: precedent, not licence. Flag-and-justify, not a hard block — no retro-move demanded.

## App config never lives in a core module

App operational settings belong to the app, not to a core module. `app/sep/config.py` / `SEPSettings` and `app/core/**` are core surfaces mounted by the whole application, so a field, type, default, or import carrying app-specific knowledge there makes **core depend on an app package** — the wrong-direction dependency. Read the section straight off YAML/env in an app-owned `app/sep/apps/<app>/config.py`, imported by consumers at call time.

**The check is "does this make a core module know about / import an app?" — not "does it cycle?"** A lighter app package or a string-annotated field would place app config in core *without* cycling and compile clean. Reject on the layering ground alone.

- **Flag:** `SEPSettings.ATW: AtwSettings = AtwSettings()` where `AtwSettings` is defined in `app/sep/apps/atw/` — whether or not it cycles.
- **Not a violation:** a genuinely cross-app / core setting (`settings.PMM`, a shared timeout) as a `SEPSettings` field; and an app importing *from* `app.sep.config` — app→core is the allowed direction.

Separately, **any `SEPSettings` field typed with a class from an app *package* does cycle**: importing `app.sep.apps.<app>.config` first executes `app/sep/apps/<app>/__init__.py`, which imports the app object for registry discovery → `api_routes` → … → `app/sep/deps.py` → `sep_settings`, only partially initialized at settings-construction time. Every app package has this `__init__.py` shape, so no import discipline inside the leaf `config.py` avoids it. Reason about an import edge into a settings-construction-time module from **what importing the target actually executes**, not from the leaf module's own import list — and a precedent claim must share the structural property, not just the `app/sep/apps/…` path prefix (`app/sep/apps/nav_icons.py` is a leaf module whose `__init__.py` has zero imports).

## Database models

- All table models inherit from `BaseSQLModel` (auto-increment int PK + `created_at`/`updated_at` UTC) or `BaseUUIDSQLModel` (UUID4 PK). NEVER inherit plain `SQLModel` for table models.
- All table models set `table=True`. `created_at` defaults to `utc_now()` (microseconds zeroed). `updated_at` uses `func.now()` for auto-update.
- **First decide whether the column should be an enum at all.** A column whose value set is a fixed, known set **is** an enum column — declare it with the enum type, not as a bare `str`. The tell is a column whose docstring, validator, or downstream coercion names the permitted values while the annotation says `str`. This omission is invisible to the enum rules below, which a `str` column silently matches none of. When the enum lives in a module the table deliberately does not import, that import boundary is the finding — not a reason to widen the column.
- **Enum columns** declare `EnumField(<Enum>, native_enum=False, create_constraint=True)` — a native PG ENUM is an expensive ALTER, and `native_enum=False` alone silently drops the CHECK constraint. The Alembic migration must mirror both kwargs on its `sa.Enum(...)`.
- **Spell `StrEnum` / `Enum` values explicitly — `auto()` is retired.** An enum's `.value` is a contract: what the API serializes, what a persisted row or JSON payload keys on, what a client parses. `auto()` on a `StrEnum` leaves it implicit ("the lowercased member name"), so a later member rename silently changes the wire value. New enums spell every member (`PENDING = "pending"`). This is going-forward: existing `auto()` enums (`ServiceTypeEnum`, `ConnectivityServiceType`, `SourceEnum`, …) are transitional debt — don't copy `auto()` into new code, and don't grow an `auto()` enum without considering spelling the whole set. **A relocation is a re-authoring, not a move**: a `StrEnum` carried verbatim into a new module keeps today's wire values byte-for-byte *and* silently re-pins the serialized contract to member names.
- **Hand-declared datetime columns need `sa_type=DateTimeWithTimezone`.** `BaseSQLModel` / `BaseUUIDSQLModel` give every table model tz-aware `created_at` / `updated_at`; a datetime column you add yourself does **not** inherit that. A `SQLField` holding a `utc_now()` / `UTCDatetime` value maps to a **naive** `DateTime` column unless you pass it. The Python value stays tz-aware, so nothing fails loudly — the timezone is dropped silently at the DB boundary, only for the columns you declared, diverging from every other timestamp column. `started_at: UTCDatetime | None = SQLField(default=None, sa_type=DateTimeWithTimezone)`.
- **Status-enum subsets** (active, finished, terminal) are named classmethods/frozensets on the enum (`TaskHistoryStatusEnum.active_statuses()`, `is_active()`), not open-coded `status.in_([PENDING, RUNNING])` at each call site.
- A new `@dataclass(frozen=True)` must include `slots=True`. Opt out with `# slots-exempt: <reason>` only when a non-slottable base or runtime attribute injection requires it.

## CRUD managers — never raw queries

All DB operations go through `BaseSQLModelManager` subclasses. Flag:

- Raw `session.execute(select(...))` / `await session.scalar(...)` in route handlers, Celery tasks, or services where a manager exists.
- Route logic that does pagination, filtering, or 404 handling inline instead of calling the manager methods that centralize those.
- A caller-level `await session.commit()` after a manager mutating method (`save`, `create`, `update`, `delete`, `update_where`, `delete_where`) — those commit internally, so the follow-up commit is dead code that misleads readers. The only valid caller-level commit is a hand-rolled `session.add(...)` batch staged outside any manager.
- **A manager method typed `-> list[T]` that a route wraps** — the pagination contract binds at the manager, not only at the route. A reviewer reading `crud.py` in isolation sees no route and so has nothing to trigger on, which is exactly how an unbounded per-service history query ships behind a route that looks fine. Decide paginated-vs-fixed-cardinality where the query is written: `list_paginated(...)` returning `PaginatedResponse[T]`, with the route taking a `PaginationDep` and passing it through. For genuinely fixed cardinality add `# pagination-ok: <reason>` in the signature window. **Carve-out:** a manager method whose result is consumed *internally* (a background job legitimately iterating every row, never a route) is not covered — batch it deliberately rather than paginating it.
- **A mapper event does not cover a bulk path.** `event.listen(Model, "after_update", …)` fires only on ORM unit-of-work flushes of tracked instances; `update_where()` / `delete_where()` funnel through `_mutate_where`, which emits a Core-level bulk `UPDATE`/`DELETE` and bypasses the identity map entirely. So a field carrying a side effect **should not be mutated through a bulk path** — route that write through `save()` and coverage is automatic. When a bulk path genuinely must carry it, fire it explicitly in the manager's `update_where` override, using `returning=` to learn which rows were affected. Don't reach for a mapper event to cover a bulk path; that's precisely the case it misses.

## Dependency injection

- `Annotated[..., Depends(...)]` aliases MUST live in `deps.py`, never in `routes.py`, `models.py`, or `loader.py` — **and so does the machinery that *produces* them**: dependency factories (`make_*_dep`), their `Depends()` callables, and any builder whose only consumer is a `Depends()`. The alias and its factory are one construct; splitting them so the alias sits in `deps.py` while the factory sits beside the value objects it builds is the same misplacement.
- **The canonical home may not exist yet.** A construct whose *kind* has a canonical home by convention — `deps.py` for dependency machinery, `responses.py` for response builders, `exceptions.py` for typed errors — belongs there even when the package has no such module: a missing canonical home is work to do, not evidence the convention doesn't apply. Scanning the package enumerates only the status quo; look to the nearest sibling *package* that has one (`app/core/pagination/deps.py` when placing into `app/core/db/`). Two exceptions, each needing a recorded reason rather than silence: creating the module would introduce a circular import, or the construct is a private single-use helper of no canonical kind.
- When a dep helper exists in `deps.py` (e.g. `get_pmm_api`, `get_or_create_alert_folder`), routes and tasks MUST use it — not construct clients or do lookups inline.
- When the same lookup pattern appears in 2+ routes, extract as a named function in `deps.py`. Single-route extraction is also warranted when the inline block is non-trivial multistep prep (fetch + validate + decide).
- **When a cycle blocks aliasing a helper, first ask whether the helper is *misplaced*.** A settings-derived helper with nothing app-specific about it belongs in `app/core/`, where no cycle exists — relocate it and alias it directly. Only when the helper genuinely belongs inside the cycle should you wrap it in a thin `provide_*()` with a function-local import.

## Explicit auth declaration — not parameter side-effect

A route that "enforces" auth only because an auth-bearing parameter (`user: ApiAdminUser`, `user: CurrentUser`) is resolved for its value — with no `dependencies=[IsApiAuthenticated]` in the decorator — relies on the parameter as a security gate. The next refactor that touches the parameter silently removes auth.

Flag new route handlers lacking explicit `dependencies=[...]` when sibling routes on the same router declare one. Carve-outs: router-level `dependencies=[...]`, full-router parameter conventions documented in the router file.

## CSRF on state-changing endpoints

POST / PUT / DELETE / PATCH endpoints must validate CSRF. When modeling a new app's stack on a sibling, don't mechanically copy decorators — trace where CSRF is enforced in the sibling's **full** dependency chain (parent router, middleware, earlier dependency). Before dropping `IsCsrfValidated` anywhere, grep the sibling for `validate_csrf` and `IsCsrfValidated` across `routes.py`, `deps.py`, and any parent router inclusion.

## Periodic-task schedules

Hard-coded periodic schedules in seed files are a red flag when the task's config object already has an `IntervalSchedule | None` field. The schedule belongs on that config object, not in seed.

## Settings & config fields

- **No `Strict()` on a runtime-overridable field** (`hot_field` / `OverridableSettingsProxy`) — the override path re-validates via `validate_python` where values arrive as strings/floats, so `Strict()` rejects coercible forms the lax siblings accept.
- **Positive lower bound on duration/threshold fields** — a field consumed as a strictly-positive duration, count, or threshold declares it at the type level (`Annotated[timedelta, Gt(timedelta(0))]`, `PositiveInt`, `Field(gt=0)`). A sensible default alone doesn't stop an operator override to 0 / negative from loading cleanly and corrupting the computation.
- **Config snapshots hold serialized data, not live resources** — a settings-override proxy or change-detection layer stores `model_dump(mode="json")` or a fingerprint, never a live connection/executor. Pydantic `__eq__` compares private state, so two identically-configured `NomadExecutor` instances compare unequal and trigger a rebind storm; the live object belongs in `app.state.*`.
- **A newly added settings field needs a `settings.yaml` entry.** An env/YAML-only field that ships with no key in `settings.yaml` — while its siblings are listed right above it — is invisible to operators. Mechanically gated on newly added fields only; the escape hatch is `# settings-yaml-exempt: <reason>` on the field, and it needs a real reason (internal machinery, a reader for removed keys). Pre-existing gaps are debt, not exemptions.

## State-machine liveness

A new or modified state machine must name, for each non-terminal state, the server-side actor that advances it (a reconciler, a `task_postrun` receiver, a `save()` hook) or a contract-permitted client action. "The edge is declared valid" is not "something drives it." Mirror-image pairs (ENABLING/DISABLING) are the canonical bug — one side gets a driver, its mirror doesn't.

## Cross-service resource contracts

When a design names a physical resource that crosses a service boundary — a filesystem path, a local port, a host socket, a shared temp dir — name the process that places it there and confirm every supported deployment topology permits it (split: separate containers, files moved over HTTP; consolidated: shared filesystem). Red flags: a `Path` / file parameter produced by one service and consumed by another; `localhost` / `127.0.0.1` in config read by a different container; satisfying a `Path` parameter by spooling a stream to a temp file (the type is wrong, not the caller).

## Upstream errors & trust boundaries

- A JSON endpoint wrapping an upstream API call (Tasks / Inventory) must re-raise the upstream **status code**, not collapse it to 500 — and apply that mapping on every branch of a multi-branch route.
- At trust boundaries (upstream JSON, `RemoteAPI` responses, third-party payloads) surface contract violations as exceptions via `.model_validate()` or explicit type checks — never silently degrade to null / empty / default (parse, don't guard).
- **Parse the domain, not only the shape.** `.model_validate()` proves the payload has the right *fields*; it says nothing about whether the object is the *kind* the caller asked for. A resolver whose name or return type asserts a subtype must enforce that subtype before returning, and 404 otherwise — every downstream caller treats the resolver's promise as established fact. `resolve_mysql_service()` returning any `CreatedService` that parsed is the bad shape; `if service.type is not ServiceTypeEnum.MYSQL: raise HTTPNotFoundException(...)` is the fix. The failure doesn't stay local: a downstream filter keyed on a column with no uniqueness guarantee (`Service.name` carries no unique index) will happily return another resource's rows under the wrong id — an unguarded resolver fails **open**. Carve-out: a query filter that *cannot* return a non-matching row (scoped by owner or type in its own `where` clause) already satisfies this; the rule fires when the narrowing exists only in the name.

## App layout

`app/sep/apps/<name>/` with `routes.py`, `deps.py`, optional `models.py`. Registration in `settings.yaml` under `SEP.APPS`. Flag apps that put dep aliases in `routes.py`/`models.py` or scatter helpers into ad-hoc module names.

The standard module roles under each app package are:

- **`models.py`** — DB table models (`BaseSQLModel` / `BaseUUIDSQLModel` subclasses with `table=True`), domain Pydantic models, and API-DTO request/response models. This is the single Pydantic/SQLModel home for the app.
- **`schema.py`** (singular) — `AppSchema` / form-DSL definitions consumed by the framework to render and validate the app's configuration form. Only present in apps that use the `TaskExecutionApp` form-DSL scaffold.
- **`spec.py`** — task-envelope builders (`build_*_spec` functions) that assemble the execution payload for a task. Only present in spec-driven apps.

No `schemas.py` (plural) files exist under `app/sep/apps/`. Pydantic request/response models belong in `models.py`.

**Nomad payload files are under a hard size budget.** `app/sep/apps/mysql_backups/mydumper_payload` and `xtrabackup_payload` must stay under **16 KiB (16,384 B)** measured as minify + gzip — Nomad's dispatch-payload limit, enforced by a pre-commit hook. A change to either can be perfectly correct and still inadmissible, and reading the diff will never tell you which, because the limit depends on the file's *accumulated* size. State the current headroom before planning additions and treat "near the limit" as a scoping input (a reclaim step, or a split) rather than a surprise at the gate.

- **Form-DSL markers** (`Forbidden`, `Required`, `pattern`) are display-only — they drive `GET /schema` rendering and client UI but do NOT validate JSON API request bodies. A constraint that must reject invalid API input needs a real Pydantic validator (`@model_validator(mode="after")` / `AfterValidator`) in addition.
- **Create wires; it doesn't run.** A create / cascade-create handler must not fire task execution (`.delay()`, a chained `POST /execute/...`). Creating a task is configuration; running it is a separate sanctioned trigger (`POST /execute/{name}` or a registered schedule).
- **Route registration order**: register literal path segments before parametrized ones — FastAPI matches in registration order, so a `/{param}` registered first swallows every literal sibling path.
- **`extra_routes` cannot win a collision with a derived route.** That ordering rule is *within* one router; across routers, `build_router` in `app/sep/apps/framework/apps.py` includes the derived CRUD router **first** and `extra_routes` **last**, deliberately. With the default `capabilities.detail` the derived set includes the greedy `GET /{detail_path_param}`, so **a single-segment sibling path under the app prefix never matches** — declaring `extra_routes` at `/apps/<key>/choices` gets you the detail handler, not your route. Nest one level deeper: `/apps/<key>/<sub>/choices`. The failure is silent and reads as a registration bug — `GET /apps/<key>/qa-choices` returns a 404 byte-identical to requesting a non-existent record, because the detail handler ran and found nothing, so the usual "did I register it?" check comes back clean.

## FastAPI / Starlette request-body gotchas

- **A Pydantic model body alongside a sibling scalar `Body()`/`Form()` parameter flips the model into embed mode.** FastAPI then expects a single body key **named after the Python parameter** — a route with `task: Annotated[TaskModel, Form()]` plus `check_connectivity: Annotated[bool, Form()] = False` returns `422 {"loc": ["body", "task"], "type": "missing"}` on a real HTML form submission, because the flat form fields never reach the model. This is long-standing FastAPI behaviour, not a version regression.
- **Middleware body reads: `.form()` and `.stream()` consume; `.body()` and `.json()` don't.** On the pinned Starlette, `BaseHTTPMiddleware` wraps the request in a `_CachedRequest` whose `wrapped_receive()` replays a body already read by `await request.body()` / `await request.json()` — those are cached and safe downstream. `await request.form()` bypasses that cache (it consumes `.stream()` directly), so downstream parsers see an empty body and return the same 422. Only flag a new middleware under `app/sep/middleware/` for this when it calls `.form()` or `.stream()`; the blanket "any body read consumes the stream" warning stopped being true at Starlette 0.28.0.
