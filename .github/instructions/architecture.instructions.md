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
| `app/sep/` | Web UI, plugins, OAuth, alerts, cross-cutting concerns not owned by a single domain | `sep_settings` |

Red flags:

- A new function under `app/sep/` reads `tasks_settings.*` or `inventory_settings.*`, or imports `NomadExecutor` / `LocalExecutor` / `BaseExecutor`.
- A new entry in `app/sep/db/seed.py::SYSTEM_PERIODIC_TASKS` whose task operates on tasks/inventory state. Each sub-app has its own `celery.py` and its own `db/seed.py::SYSTEM_PERIODIC_TASKS` — use the matching pair.
- A test for a tasks-flavored periodic task landing under `tests/app/sep/` instead of `tests/app/tasks/`.

## Database models

- All table models inherit from `BaseSQLModel` (auto-increment int PK + `created_at`/`updated_at` UTC) or `BaseUUIDSQLModel` (UUID4 PK). NEVER inherit plain `SQLModel` for table models.
- All table models set `table=True`. `created_at` defaults to `utc_now()` (microseconds zeroed). `updated_at` uses `func.now()` for auto-update.

## CRUD managers — never raw queries

All DB operations go through `BaseSQLModelManager` subclasses. Flag:

- Raw `session.execute(select(...))` / `await session.scalar(...)` in route handlers, Celery tasks, or services where a manager exists.
- Route logic that does pagination, filtering, or 404 handling inline instead of calling the manager methods that centralize those.

## Dependency injection

- `Annotated[..., Depends(...)]` aliases MUST live in `deps.py`, never in `routes.py` or `models.py`.
- When a dep helper exists in `deps.py` (e.g. `get_pmm_api`, `get_or_create_alert_folder`), routes and tasks MUST use it — not construct clients or do lookups inline.
- When the same lookup pattern appears in 2+ routes, extract as a named function in `deps.py`. Single-route extraction is also warranted when the inline block is non-trivial multistep prep (fetch + validate + decide).

## Explicit auth declaration — not parameter side-effect

A route that "enforces" auth only because an auth-bearing parameter (`user: ApiAdminUser`, `user: CurrentUser`) is resolved for its value — with no `dependencies=[IsApiAuthenticated]` in the decorator — relies on the parameter as a security gate. The next refactor that touches the parameter silently removes auth.

Flag new route handlers lacking explicit `dependencies=[...]` when sibling routes on the same router declare one. Carve-outs: router-level `dependencies=[...]`, full-router parameter conventions documented in the router file.

## CSRF on state-changing endpoints

POST / PUT / DELETE / PATCH endpoints must validate CSRF. When modeling a new plugin's stack on a sibling, don't mechanically copy decorators — trace where CSRF is enforced in the sibling's **full** dependency chain (parent router, middleware, earlier dependency). Before dropping `IsCsrfValidated` anywhere, grep the sibling for `validate_csrf` and `IsCsrfValidated` across `routes.py`, `deps.py`, and any parent router inclusion.

## Periodic-task schedules

Hard-coded periodic schedules in seed files are a red flag when the task's config object already has an `IntervalSchedule | None` field. The schedule belongs on that config object, not in seed.

## Plugin layout

`app/sep/plugins/<name>/` with `routes.py`, `deps.py`, optional `models.py`. Registration in `settings.yaml` under `SEP.PLUGINS`. Flag plugins that put dep aliases in `routes.py`/`models.py` or scatter helpers into ad-hoc module names.
