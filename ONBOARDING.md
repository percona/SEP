# SEP Onboarding Guide

## Project Overview

**Percona Services Enablement Platform (SEP)** is a FastAPI application with three sub-apps for web UI, inventory management, and task execution.

| | |
|---|---|
| **Languages** | Python, JavaScript, Bash |
| **Frameworks** | FastAPI, SQLAlchemy, Pydantic, Celery, Alembic, Starlette, Uvicorn, aiohttp, pytest |
| **Auth** | Casdoor (OAuth2/OIDC) |
| **Task Execution** | HashiCorp Nomad + Celery |

---

## Architecture Layers

### 1. Shared Core (`app/core/`)

Cross-cutting infrastructure shared by all three sub-applications: auth (Casdoor/JWT), async DB session management, Celery worker base, HTTP request utilities, Pydantic field types, and reusable exceptions.

**Key files:**

- `app/core/config.py` — Layered settings: env vars > `.env` > `settings.yaml`
- `app/core/db/models.py` — `BaseSQLModel` (int PK) and `BaseUUIDSQLModel` (UUID4 PK)
- `app/core/db/crud.py` — Abstract CRUD manager hierarchy (`BaseSQLModelManager`)
- `app/core/auth/providers/casdoor.py` — Full Casdoor OAuth2/OIDC SDK client
- `app/core/auth/models.py` — `OAuthToken`, `BaseTokenPayload`, `BaseUser`
- `app/core/requests/remote_api.py` — Async HTTP client base class
- `app/core/utils/fields.py` — Custom Pydantic field types (`StrHttpUrl`, `StrAnyUrl`, etc.)
- `app/core/exceptions.py` — Project-specific HTTP exceptions

### 2. SEP Application (`app/sep/`)

The main web UI sub-application: FastAPI app bootstrap, Jinja2 templates, CRUD managers, data-sync framework (PMM/MySQL syncers), alert-snippet management, middleware (CSRF, flash messages), and shared route handlers.

**Key files:**

- `app/sep/main.py` — Lifespan init, plugin registration, Celery snippet-sync
- `app/sep/deps.py` — Central dependency injection hub (38 imports); `IsAuthenticated`, `CurrentUser`, `InventoryClient`
- `app/sep/clients/pmm.py` — PMM API client (20+ async methods)
- `app/sep/config.py` — SEP-specific settings hierarchy
- `app/sep/sync/` — Data synchronization framework (PMM syncer, MySQL syncer)
- `app/sep/snippets/` — Executable script snippet management

### 3. SEP Feature Plugins (`app/sep/plugins/`)

Modular FastAPI routers, each implementing one support-engineering feature. Each plugin has `routes.py`, `deps.py`, and optional `models.py`.

| Plugin | Purpose |
|--------|---------|
| `alerts` | Alert rule templates, PagerDuty config, alert push |
| `snippets` | List, approve, refresh, execute script snippets |
| `backup` / `backup_mongo` / `backup_pg` | Database backup management |
| `alters` | Schema alteration operations (pt-osc) |
| `archives` | Archive management |
| `checksums` | Data checksum verification |
| `dipper` | Diagnostic data collection |
| `inventory` | Inventory UI (delegates to Inventory Service API) |
| `tasks` | Task management UI |

### 4. Inventory Service (`app/inventory/`)

Standalone REST API managing a four-level hierarchy: **nodes → services → schemas → tables**. Routes split one-per-entity, all using the CRUD manager pattern.

**Key files:**

- `app/inventory/models.py` — Full entity hierarchy (29 fan-in, most-referenced in sub-app)
- `app/inventory/routes/` — `nodes.py`, `services.py`, `schemas.py`, `tables.py`

### 5. Tasks Service (`app/tasks/`)

Standalone FastAPI sub-app for task execution via Nomad, periodic scheduling, PII anonymization, and task lifecycle CRUD. Most internally connected part of the codebase.

**Key files:**

- `app/tasks/models.py` — **Highest fan-in in the entire graph** (57 imports); enums, Task/TaskHistory models, all Pydantic shapes
- `app/tasks/routes.py` — CRUD endpoints (24 outgoing imports)
- `app/tasks/execution/executors/nomad/models.py` — Nomad executor (1403 lines)
- `app/tasks/celery.py` — Periodic/async task scheduling
- `app/tasks/anonymizer/` — PII anonymization of task output

### 6. Infrastructure & Configuration

Deployment and runtime: container entrypoints, certificate generation, Alembic migrations for all three databases, top-level app composition.

**Key files:**

- `app/main.py` — Root composition: mounts inventory at `/api/inventory`, tasks at `/api/tasks`, SEP at `/`
- `entrypoint.sh` / `entrypoint_celery.sh` — Container entrypoints
- `app/{sep,inventory,tasks}/migrations/` — Alembic migration tracks

### 7. Frontend & Diagnostic Scripts

Browser-side JavaScript (Alpine.js/HTMX integrations) and shell scripts for diagnostic data collection.

**Key files:**

- `static/js/` — `app.js`, `alerts.js`, `logs.js`, `snippets.js`, `scheduled.js`
- `snippets/` — Bash diagnostic scripts (MySQL, PostgreSQL, system-level)

### 8. Tests (`tests/app/`)

Mirrors the full app structure. Factory-based test data via polyfactory.

**Key files:**

- `tests/app/factories.py` — Most-referenced test file (14 fan-in); factories for all major models
- Test directories mirror `app/` exactly (e.g., `tests/app/sep/plugins/alerts/`)

---

## Key Concepts & Patterns

1. **Dependency Injection** — All auth, DB sessions, and API clients are injected via `Annotated[..., Depends()]` type aliases in each service's `deps.py`
2. **CRUD Managers** — All DB operations go through class-based managers inheriting from `BaseSQLModelManager` — never raw session queries
3. **Model Hierarchy** — DB models inherit from `BaseSQLModel` or `BaseUUIDSQLModel`, never plain `SQLModel`
4. **Plugin Architecture** — Features are self-contained routers discovered at startup; add/remove via `settings.yaml`
5. **Three Separate Databases** — SEP, Inventory, and Tasks each have independent Alembic migration tracks
6. **Executor Pattern** — Task execution uses a plugin interface (`app/tasks/execution/executors/`) with Nomad as the primary implementation
7. **Project-Specific Exceptions** — Use `HTTPNotFoundException`, `HTTPConflictException`, etc. — never `HTTPException` directly

---

## Guided Tour (Recommended Reading Order)

| # | Topic | Start Here |
|---|-------|------------|
| 1 | **Application Entry Point** | `app/main.py` — see how the three sub-apps are composed |
| 2 | **Configuration Layer** | `app/core/config.py` — YAML + env + .env priority chain |
| 3 | **Database Foundations** | `app/core/db/models.py` + `app/core/db/crud.py` — base models and CRUD contract |
| 4 | **Authentication** | `app/core/auth/providers/casdoor.py` + `app/api/deps.py` — JWT flow |
| 5 | **SEP Web UI Core** | `app/sep/main.py` + `app/sep/deps.py` — plugin registration and DI hub |
| 6 | **Plugin System** | `app/sep/plugins/__init__.py` — how plugins are structured |
| 7 | **Alerts & Snippets** | `app/sep/plugins/alerts/routes.py` + `app/sep/plugins/snippets/routes.py` |
| 8 | **Inventory Service** | `app/inventory/models.py` — the nodes/services/schemas/tables hierarchy |
| 9 | **Tasks Domain** | `app/tasks/models.py` — the most-connected file in the codebase |
| 10 | **Nomad & Celery** | `app/tasks/execution/executors/nomad/models.py` + `app/tasks/celery.py` |
| 11 | **Testing** | `tests/app/factories.py` — polyfactory-based data generation |

---

## Complexity Hotspots

These files have the highest complexity — approach with care:

| File | Why it's complex |
|------|-----------------|
| `app/tasks/models.py` | 871 lines, 57 fan-in — the most-imported file in the entire codebase |
| `app/tasks/execution/executors/nomad/models.py` | 1403 lines — full Nomad job lifecycle |
| `app/core/auth/providers/casdoor.py` | 14 async methods covering full OAuth2/OIDC flow |
| `app/core/auth/models.py` | Abstract user model with 12 class methods |
| `app/sep/deps.py` | 38 imports — central DI hub for all SEP plugins |
| `app/sep/clients/pmm.py` | 20+ async methods covering full PMM API surface |
| `app/core/config.py` | Layered settings with Casdoor, Celery, logging, security |
| `app/core/db/crud.py` | Abstract CRUD manager hierarchy governing all data access |
| `app/sep/plugins/alerts/routes.py` | Multi-system integration (PagerDuty, PMM) |
| `app/sep/plugins/alters/pre_checks.py` | MySQL pre-check validation scripts |

---

## Quick Start

```bash
# 1. Set up environment
make venv && source venv/bin/activate

# 2. Run migrations
make migrate

# 3. Start dev server with Celery
LOGGING=debug python3 -m app.main --start-celery

# 4. Run tests
make test

# 5. Lint
make lint
```
