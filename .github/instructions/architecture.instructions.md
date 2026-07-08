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
- A module in `app/tasks/` or `app/inventory/` hard-codes a specific app's parser, schema, magic strings, or enrichment for one app — even wrapped as "generic infra". The tell: a helper returning app-specific content for one app and `None` for the rest. App knowledge stays in the app's package; the generic service holds only the registration/hook mechanism.

## Database models

- All table models inherit from `BaseSQLModel` (auto-increment int PK + `created_at`/`updated_at` UTC) or `BaseUUIDSQLModel` (UUID4 PK). NEVER inherit plain `SQLModel` for table models.
- All table models set `table=True`. `created_at` defaults to `utc_now()` (microseconds zeroed). `updated_at` uses `func.now()` for auto-update.
- **Enum columns** declare `EnumField(<Enum>, native_enum=False, create_constraint=True)` — a native PG ENUM is an expensive ALTER, and `native_enum=False` alone silently drops the CHECK constraint. The Alembic migration must mirror both kwargs on its `sa.Enum(...)`.
- **Status-enum subsets** (active, finished, terminal) are named classmethods/frozensets on the enum (`TaskHistoryStatusEnum.active_statuses()`, `is_active()`), not open-coded `status.in_([PENDING, RUNNING])` at each call site.
- A new `@dataclass(frozen=True)` must include `slots=True`. Opt out with `# slots-exempt: <reason>` only when a non-slottable base or runtime attribute injection requires it.

## CRUD managers — never raw queries

All DB operations go through `BaseSQLModelManager` subclasses. Flag:

- Raw `session.execute(select(...))` / `await session.scalar(...)` in route handlers, Celery tasks, or services where a manager exists.
- Route logic that does pagination, filtering, or 404 handling inline instead of calling the manager methods that centralize those.
- A caller-level `await session.commit()` after a manager mutating method (`save`, `create`, `update`, `delete`, `update_where`, `delete_where`) — those commit internally, so the follow-up commit is dead code that misleads readers. The only valid caller-level commit is a hand-rolled `session.add(...)` batch staged outside any manager.

## Dependency injection

- `Annotated[..., Depends(...)]` aliases MUST live in `deps.py`, never in `routes.py`, `models.py`, or `loader.py`.
- When a dep helper exists in `deps.py` (e.g. `get_pmm_api`, `get_or_create_alert_folder`), routes and tasks MUST use it — not construct clients or do lookups inline.
- When the same lookup pattern appears in 2+ routes, extract as a named function in `deps.py`. Single-route extraction is also warranted when the inline block is non-trivial multistep prep (fetch + validate + decide).

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

## State-machine liveness

A new or modified state machine must name, for each non-terminal state, the server-side actor that advances it (a reconciler, a `task_postrun` receiver, a `save()` hook) or a contract-permitted client action. "The edge is declared valid" is not "something drives it." Mirror-image pairs (ENABLING/DISABLING) are the canonical bug — one side gets a driver, its mirror doesn't.

## App layout

`app/sep/apps/<name>/` with `routes.py`, `deps.py`, optional `models.py`. Registration in `settings.yaml` under `SEP.APPS`. Flag apps that put dep aliases in `routes.py`/`models.py` or scatter helpers into ad-hoc module names.

The standard module roles under each app package are:

- **`models.py`** — DB table models (`BaseSQLModel` / `BaseUUIDSQLModel` subclasses with `table=True`), domain Pydantic models, and API-DTO request/response models. This is the single Pydantic/SQLModel home for the app.
- **`schema.py`** (singular) — `AppSchema` / form-DSL definitions consumed by the framework to render and validate the app's configuration form. Only present in apps that use the `TaskExecutionApp` form-DSL scaffold.
- **`spec.py`** — task-envelope builders (`build_*_spec` functions) that assemble the execution payload for a task. Only present in spec-driven apps.

No `schemas.py` (plural) files exist under `app/sep/apps/`. Pydantic request/response models belong in `models.py`.

- **Form-DSL markers** (`Forbidden`, `Required`, `pattern`) are display-only — they drive `GET /schema` rendering and client UI but do NOT validate JSON API request bodies. A constraint that must reject invalid API input needs a real Pydantic validator (`@model_validator(mode="after")` / `AfterValidator`) in addition.
- **Create wires; it doesn't run.** A create / cascade-create handler must not fire task execution (`.delay()`, a chained `POST /execute/...`). Creating a task is configuration; running it is a separate sanctioned trigger (`POST /execute/{name}` or a registered schedule).
- **Route registration order**: register literal path segments before parametrized ones — FastAPI matches in registration order, so a `/{param}` registered first swallows every literal sibling path.
