# 6. Per-Plugin Migration Playbook

This page is the day-to-day working document for engineers migrating plugins. It has two sub-playbooks — one for schema-driven plugins (Path A), one for custom React plugins (Path B) — plus a per-plugin checklist and concrete code examples.

## Before Starting Any Plugin

1. **Read the current Jinja2 template(s)** and plugin `routes.py` / `deps.py` / `models.py`. Understand what the plugin actually does before proposing how it should look in React.
2. **Check cross-plugin dependencies** — does this plugin include shared partials that aren't yet migrated? Does it use partials from another plugin's template dir?
3. **Check the backlog** — are there open tickets that affect this plugin's API or UI? Align with them before starting.
4. **Decide Path A or Path B** — reference the plugin classification in Plugin Model. If unsure, ask the team.
5. **Create the ticket** — small, scoped, clearly named (e.g., `SEP-XXXX: Migrate checksums plugin to React (Path A)`).

## Path A — Schema-Driven Plugin

Used for plugins whose UI is "pick a target, fill a form, execute a task, view results" — the majority of plugins.

### Step-by-step

#### 1. Audit the current plugin

Read the current Jinja2 template and document:

- **Data the page needs** (what the route passes into `context`)
- **Form fields and validation rules** (from `models.py` form classes)
- **Dynamic field behavior** (cascades, conditional visibility)
- **Task creation logic** (from `deps.py` `build_*_task_payload()`)
- **Cross-cutting features used** (chaining, alert-on-fail, scheduling, service/schema/table selectors)

Write this up in the ticket description. It becomes the acceptance criteria.

#### 2. Define the plugin schema

Create `app/sep/plugins/{name}/schema.py`:

```python
# app/sep/plugins/checksums/schema.py
from app.sep.plugins.framework.schema import (
    PluginSchema,
    FormSection,
    ServiceField,
    SchemaField,
    ChoiceField,
    BoolField,
    IntegerField,
    Capabilities,
    ListView,
    Column,
)

plugin_schema = PluginSchema(
    name="checksums",
    display_name="Checksums",
    description="Run pt-table-checksum for consistency verification",
    task_type="pt-table-checksum",

    forms=[
        FormSection(
            title="Target",
            fields=[
                ServiceField(
                    name="service",
                    required=True,
                    service_types=["mysql"],
                    label="Service",
                    description="MySQL service to check",
                ),
                SchemaField(
                    name="schema",
                    required=False,
                    depends_on="service",
                    label="Schema (optional)",
                    description="Leave blank to check all schemas",
                ),
            ],
        ),
        FormSection(
            title="Options",
            fields=[
                ChoiceField(
                    name="chunk_size",
                    choices=["1000", "5000", "10000"],
                    default="1000",
                    label="Chunk size",
                ),
                BoolField(
                    name="replicate_check",
                    default=True,
                    label="Enable replication check",
                ),
                IntegerField(
                    name="max_lag",
                    default=60,
                    ge=0,
                    le=3600,
                    label="Max replica lag (seconds)",
                ),
            ],
        ),
    ],

    capabilities=Capabilities(
        chaining=True,
        alert_on_fail=True,
        scheduling=True,
    ),

    list_view=ListView(
        columns=[
            Column("name", label="Name", sortable=True),
            Column("service", label="Service", sortable=True),
            Column("status", label="Status", sortable=True),
            Column("last_run", label="Last run", format="relative", sortable=True),
        ],
        default_sort="-last_run",
    ),
)
```

#### 3. Create the response models

In `app/sep/plugins/{name}/models.py`, add response models following the `{Resource}Base` / `{Resource}Write` / `{Resource}Response` pattern:

```python
# app/sep/plugins/checksums/models.py
from datetime import datetime
from sqlmodel import SQLModel
from app.tasks.models import TaskHistoryStatusEnum

class ChecksumTaskBase(SQLModel):
    service_id: int
    schema_name: str | None = None
    chunk_size: int = 1000
    replicate_check: bool = True
    max_lag: int = 60

class ChecksumTaskWrite(ChecksumTaskBase):
    """Input for POST /api/plugins/checksums/"""
    # Shared capabilities
    chain_task_names: list[str] = []
    chain_on_failure: bool = False
    alert_on_fail: bool = False

class ChecksumTaskResponse(ChecksumTaskBase):
    """Output for GET endpoints"""
    name: str
    created_at: datetime
    last_run: datetime | None = None
    status: TaskHistoryStatusEnum | None = None
```

#### 4. Create the API routes

```python
# app/sep/plugins/checksums/api_routes.py
from typing import Annotated
from fastapi import APIRouter, Depends, status
from app.core.exceptions import HTTPNotFoundException
from app.sep.deps import TaskAPI, InventoryAPI
from app.sep.plugins.checksums.models import ChecksumTaskResponse, ChecksumTaskWrite
from app.sep.plugins.checksums.deps import (
    get_checksum_tasks,
    get_checksum_task_by_name,
    build_checksum_task,
)
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.checksums.schema import plugin_schema

router = APIRouter()

# Schema discovery — served at GET /schema
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
    created = await tasks_api.post("/", json=task.model_dump(mode="json"))
    return created

@router.delete("/{task_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checksum_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> None:
    await tasks_api.delete(f"/{task_name}")
```

#### 5. Register the plugin router

Add to `app/sep/api/router.py`:

```python
from app.sep.plugins.checksums.api_routes import router as checksums_router

plugins_router.include_router(checksums_router, prefix="/checksums", tags=["checksums"])
```

#### 6. Create the React plugin package

```
frontend/packages/plugins/checksums/
├── src/
│   ├── index.ts          # Barrel
│   └── routes.ts         # Registers with shell router
└── package.json
```

```tsx
// frontend/packages/plugins/checksums/src/routes.ts
import { SchemaDrivenPlugin } from '@sep/framework';

export const checksumsRoutes = [
  {
    path: '/plugins/checksums/*',
    element: <SchemaDrivenPlugin pluginName="checksums" />,
  },
];
```

That's it. No custom React code. The `SchemaDrivenPlugin` component fetches `/api/plugins/checksums/schema`, renders the form, lists existing tasks, handles execution.

#### 7. Register the plugin with the shell router

```tsx
// frontend/packages/shell/src/router.ts
import { checksumsRoutes } from '@sep/plugin-checksums';
import { reportRoutes } from '@sep/plugin-report';
// ... etc

export const routes = [
  ...checksumsRoutes,
  ...reportRoutes,
  // ...
];
```

#### 8. Test feature parity

- Create a task via the React form, verify it shows up in the history table
- Execute it, verify the log viewer streams logs correctly
- Chain it to another task, verify the chain builder
- Enable alert-on-fail, verify the alert triggers
- Schedule it, verify the scheduled tasks panel
- Delete it
- Cross-check: does the same task show up in the Jinja2 frontend too? It should, both are hitting the same backend

#### 9. Switch routing

Update Nginx to route `/plugins/{name}/*` to React. Add the plugin to the shell's navigation menu. The Jinja2 route becomes `/legacy/plugins/{name}/*` for now, still functional.

#### 10. Mark Jinja2 route deprecated

Add a comment or log line in the Jinja2 route, but leave it functional. Do NOT remove it. Wave 3 removes all deprecated routes in bulk.

### Path A checklist

- [ ] Plugin audit written in the ticket
- [ ] `schema.py` created with `PluginSchema`
- [ ] `models.py` has `{Name}TaskBase`, `{Name}TaskWrite`, `{Name}TaskResponse`
- [ ] `api_routes.py` has list, get, post, delete endpoints with response models
- [ ] Schema endpoint registered via `schema_endpoint()` helper
- [ ] Plugin router registered in `app/sep/api/router.py`
- [ ] Pydantic input models validate all form inputs
- [ ] Task creation logic (`build_*_task_payload`) reused or cleanly adapted
- [ ] React plugin package created, routes registered with shell
- [ ] Manual test: create, view, chain, schedule, execute, delete
- [ ] SSE log streaming verified
- [ ] Feature parity with Jinja2 verified
- [ ] Nginx routing updated
- [ ] Jinja2 route deprecated (commented, still functional)
- [ ] E2E test added (Playwright smoke test)
- [ ] Backend tests added (pytest) for the new API routes
- [ ] Documentation updated if plugin docs exist

## Path B — Custom React Plugin

Used for plugins with genuinely unique UI: alerts, alters, archives.

### When to use Path B

Ask these questions. If **any** answer is yes, it's Path B:

- Does the plugin create multiple related tasks atomically? (alters, archives, backup_mongo partially)
- Does the plugin have a wizard with conditional branching? (alerts backup/restore)
- Does the plugin integrate with an external API that isn't the Tasks or Inventory sub-app? (alerts ↔ PMM)
- Does the plugin have a form with more than ~30 fields and dynamic field dependencies that would explode the schema DSL? (alters, archives)
- Does the plugin have a custom visualization (graph, chart, topology view)? (none currently)

If all answers are no, it's Path A.

### Step-by-step

#### 1. Audit (same as Path A)

Document current behavior in the ticket. Be extra thorough — custom plugins have more hidden complexity.

#### 2. Create backend API routes

Same pattern as Path A — plugin router under `/api/plugins/{name}/`. But the routes may not map cleanly to "list / get / post / delete":

```python
# app/sep/plugins/alters/api_routes.py
from fastapi import APIRouter, Depends, status
from app.sep.plugins.alters.models import (
    AltersTaskResponse,
    AltersTaskWrite,
    AltersPreCheckResponse,
)

router = APIRouter()

# No schema endpoint for custom plugins — the UI is hand-written

@router.get("/", response_model=list[AltersTaskResponse])
async def list_alters_tasks(...): ...

@router.get("/{task_name}", response_model=AltersTaskResponse)
async def get_alters_task(...): ...

@router.post("/", response_model=AltersTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_alters_task(...):
    """Creates three related tasks atomically: execute, dry-run, pre-checks"""
    ...

@router.post("/{task_name}/pre-check", response_model=AltersPreCheckResponse)
async def run_pre_checks(...):
    """Custom endpoint for plugin-specific behavior"""
    ...
```

#### 3. Create the React plugin package

```
frontend/packages/plugins/alters/
├── src/
│   ├── pages/
│   │   ├── AltersListPage.tsx
│   │   ├── AltersCreatePage.tsx
│   │   ├── AltersDetailPage.tsx
│   │   └── AltersEditPage.tsx
│   ├── components/
│   │   ├── AltersFormWizard.tsx     # Custom multi-step form
│   │   ├── AltersArgumentsPreview.tsx
│   │   └── DryRunToggle.tsx
│   ├── hooks/
│   │   ├── useAltersTask.ts
│   │   └── useAltersPreCheck.ts
│   ├── routes.ts                    # Registers with shell router
│   └── index.ts
└── package.json
```

#### 4. Reuse shared framework components

Even custom plugins use `<TaskLogViewer>`, `<ChainBuilder>`, `<TaskHistoryTable>`, `<ServiceSelector>`, etc. Only the form is custom.

```tsx
// frontend/packages/plugins/alters/src/pages/AltersDetailPage.tsx
import { TaskHistoryTable, TaskLogViewer, ChainBuilder } from '@sep/framework';
import { AltersArgumentsPreview } from '../components/AltersArgumentsPreview';

export function AltersDetailPage({ taskName }: { taskName: string }) {
  // ... custom form state ...

  return (
    <Stack spacing={3}>
      <AltersArgumentsPreview task={task} />
      <ChainBuilder taskName={taskName} />
      <TaskHistoryTable taskName={taskName} />
      <TaskLogViewer taskHistoryId={selectedHistoryId} />
    </Stack>
  );
}
```

#### 5. Register routes with the shell

```tsx
// frontend/packages/plugins/alters/src/routes.ts
import { AltersListPage, AltersCreatePage, AltersDetailPage } from './pages';

export const altersRoutes = [
  { path: '/plugins/alters', element: <AltersListPage /> },
  { path: '/plugins/alters/create', element: <AltersCreatePage /> },
  { path: '/plugins/alters/:taskName', element: <AltersDetailPage /> },
];
```

#### 6. Test feature parity

Same as Path A. For custom plugins, pay extra attention to edge cases the Jinja2 version handles (error states, validation failures, multi-task atomicity).

### Path B checklist

- [ ] Plugin audit written in the ticket (extra thorough)
- [ ] Backend API routes created with response models
- [ ] Backend exposes all plugin-specific endpoints (not just CRUD)
- [ ] React plugin package created
- [ ] Custom components written; use shared framework for chaining/logs/history/selectors
- [ ] react-hook-form used for form state and validation
- [ ] Custom form matches Jinja2 field-for-field (or explicitly documents differences)
- [ ] All plugin-specific business logic preserved (validation, multi-task creation, external API calls)
- [ ] Routes registered with shell
- [ ] Manual test: full feature parity walkthrough
- [ ] SSE log streaming verified
- [ ] E2E test added (Playwright)
- [ ] Backend tests for new API routes
- [ ] Jinja2 route deprecated

## Per-Plugin Wave Assignment (Reference)

| Plugin                                | Path | Wave                   | Est. effort (pair-days) | Notes                                         |
| ------------------------------------- | ---- | ---------------------- | ----------------------- | --------------------------------------------- |
| Framework layer + checksums pilot     | A    | 0                      | 10-15                   | Wave 0 must-have                              |
| First custom pilot (backup OR alters) | B    | 0 (stretch)            | 5-7                     | Validates escape hatch                        |
| inventory                             | A    | 1                      | 2-3                     | Already has API, mostly CRUD                  |
| snippets                              | A    | 1                      | 2-3                     | Already schema-driven on backend              |
| report                                | A    | 1                      | 2                       | Currently template-only, needs backend routes |
| atw                                   | A    | 1                      | 2-3                     | Delegates to snippet infrastructure           |
| dipper                                | A    | 1                      | 3-4                     | Service selection + script preview            |
| tasks                                 | A    | 1                      | 3-5                     | Generic task management                       |
| alert_troubleshooting                 | A    | 1                      | 3-4                     | Snippet execution proxy, accordion UI         |
| backup                                | A    | 2                      | 4-5                     | YAML config, upload providers                 |
| backup_mongo                          | A    | 2                      | 4-5                     | Multi-task atomic creation (backend work)     |
| backup_pg                             | A    | 2                      | 3-4                     | Same pattern as backup                        |
| checksums                             | A    | already done in Wave 0 | —                       | Validates end-to-end                          |
| alters                                | B    | 2                      | 10-14                   | 40+ field custom form, multi-task             |
| archives                              | B    | 2                      | 8-10                    | Similar to alters, apply learnings            |
| alerts                                | B    | 2                      | 10-14                   | PMM integration, backup/restore, PagerDuty    |

**Total (excluding Wave 0)**: ~60-90 pair-days. With ~4 people available, realistic at 15-25 pair-days per week of team capacity, fits in 4-6 weeks — which matches the Wave 1 + Wave 2 schedule.

## Handling Specific Concerns

### SSE log streaming with Bearer auth

**Problem**: EventSource cannot send custom headers — no way to pass `Authorization: Bearer <token>`.

**Options**:

1. **Keep SSE endpoints cookie-authenticated during transition.** The React SPA logs in via Casdoor → gets a Bearer token for API calls AND a cookie for SSE. Works because we're same-origin. When the cookie auth is retired in Wave 3, revisit.
2. **Single-use query param token.** SSE endpoint accepts `?token=<short-lived-single-use-token>` as a fallback. Token is issued via a short-lived authenticated endpoint.
3. **WebSocket replacement.** Migrate log streaming to WebSocket, which does support custom headers via the initial connection. Big change, not Wave 0 scope.

**Recommendation**: Option 1. It's the smallest change, SEP-662 already makes cookie-based SSE SPA-compatible, and Wave 3 is where we revisit.

### Gateway for existing API consumers

**Problem**: The current frontend calls `/api/inventory/*` and `/api/tasks/*` from Jinja2 templates and JS. The gateway pattern says these shouldn't be exposed to the frontend.

**Migration path**:

1. During Wave 0, audit every frontend reference to `/api/inventory/*` and `/api/tasks/*`
2. For each reference, add a plugin route that proxies it (most inventory references are service/schema/table lookups — those become `<ServiceSelector>` etc. using plugin-level endpoints)
3. Jinja2 templates continue using the direct sub-app routes during transition (backward compat)
4. React uses only plugin routes — never sub-app routes
5. Wave 3: Inventory and Tasks sub-apps are demoted to internal-only (no longer mounted at `/api/inventory/` / `/api/tasks/`)

**Don't break Jinja2 during Wave 0 by cutting off the direct routes**. The cut happens in Wave 3.

### YAML form fields (backup plugin)

**Problem**: Backup plugins use YAML for task configuration — a free-text field with structure. Not cleanly representable as a set of discrete form fields.

**Options**:

1. **Keep YAML as-is** — schema has a `YamlField` type that maps to a TextInput with optional YAML validation. Path A stays feasible.
2. **Decompose into structured fields** — migrate away from YAML, use the schema DSL to represent the config. Much more work, breaks backward compat.

**Recommendation**: Option 1 for the migration. Add YAML linting later if desired. Don't try to boil the ocean.

### Multi-task atomic creation (alters, archives, backup_mongo)

**Problem**: Some plugins create multiple related tasks atomically (e.g., alters creates execute + dry-run + pre-checks as a unit).

**Options for schema-driven path**:

- The plugin's `POST /api/plugins/{name}/` backend endpoint creates all related tasks internally. The React form just submits once. The "atomicity" is a backend concern.
- For **alters** specifically, this still isn't enough — alters has dry-run mode toggling and other UI complexity. It's Path B anyway.
- For **backup_mongo**, the multi-task creation is backend-only (4 sub-tasks for config/logical/physical/status) and doesn't affect the form UI. Can be Path A.

### Cross-plugin shared partials

**Problem**: Templates include partials from other plugins (`templates/tasks/partials/*.html.j2` is used by every task-based plugin).

**Migration path**:

- The shared partials become framework components (Wave 0): `<ChainBuilder>`, `<TaskHistoryTable>`, etc.
- Each plugin migration consumes the framework components — no more shared partial imports
- Shared partials are deleted in Wave 3

## Definition of Done per Plugin Migration

A plugin migration is DONE when:

1. React UI matches Jinja2 feature parity (acceptance criteria in ticket)
2. Backend API endpoints exist with response models and tests
3. Schema / plugin package committed
4. Nginx routing updated (the plugin's URL goes to React)
5. Jinja2 route marked deprecated but left functional
6. E2E test (Playwright) smoke-tests the main flow
7. QA signoff
8. Ticket closed with PR link
9. Plugin appears in the shell navigation menu
10. No regressions in unrelated plugins

## Definition of Done per Wave

**Wave 0**: framework layer + two plugin pilots, Nginx/CI/Docker updated, freeze can end.

**Wave 1**: all schema-driven plugins migrated, feature parity verified.

**Wave 2**: all custom plugins migrated, framework layer validated under real custom plugin load.

**Wave 3**: legacy deleted, no more `/legacy/*`, no more `.html.j2` templates, no more jQuery or vendor JS.
