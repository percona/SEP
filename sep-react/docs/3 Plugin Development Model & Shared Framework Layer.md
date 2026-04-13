# 3. Plugin Development Model & Shared Framework Layer

This is the most important architectural page in this document. The plugin development model affects every plugin migration and defines how new plugins will be built going forward. Get this wrong and every plugin rewrite becomes a duplication disaster.

## The Core Insight

When I previously classified plugins as "custom React" versus "schema-driven", I conflated two things:

1. **Plugin-specific UI complexity** (unique forms, unique interactions, unique business logic)
2. **Cross-cutting concerns used by many plugins** (task chaining, SSE log streaming, task history tables, service/schema/table selectors, alert-on-fail)

Category 2 is **shared framework**, not per-plugin. Every task-based plugin uses the chain builder. Every task-based plugin displays execution logs via SSE. Every task-based plugin shows task history in a shared table. Marking a plugin as "custom" because it has a chain builder meant marking almost every plugin as custom — which defeated the point of the schema-driven vision.

<aside>
✅

**The correct model**:

- **Shared framework layer**: Built once in Wave 0. Replaces `logs.js`, `chain-builder.js`, `schema-selector.js`, `running-tasks.html.j2`, `completed-tasks.html.j2`, `scheduled-tasks.html.j2`, `create-form-alert-on-failure-input.html.j2`. Every plugin consumes these as React components or hooks.
- **Schema-driven plugins** (Path A): Declare a Pydantic schema. The React `<SchemaFormRenderer>` auto-generates the form. The plugin writes minimal to zero React code.
- **Custom React plugins** (Path B): Truly complex plugin-specific UI. Write bespoke React components, but still use the shared framework layer for chaining, logs, history, selectors.
</aside>

## The Two Paths

### Path A — Schema-Driven Plugins (default)

**Used by**: most plugins — any plugin whose main UI is "pick a target, fill a form, execute a task, view results".

**What the plugin developer writes:**

1. **Backend API routes** (Python, in `app/sep/plugins/{name}/api_routes.py`) — standard FastAPI routes returning JSON.
2. **A plugin schema** (Python, in `app/sep/plugins/{name}/schema.py`) — declares the form fields, types, validation rules, and layout hints.
3. **The schema endpoint** is served at `/api/plugins/{name}/schema` automatically via a shared dependency.

**What the plugin developer does NOT write:**

- Any React code
- Any form rendering logic
- Any validation rendering logic
- Any log viewer
- Any chain builder
- Any service/schema/table selector
- Any task history table

**What happens at runtime**:

1. The React shell router discovers the plugin (by reading a plugin manifest or via a registration API)
2. When the user navigates to the plugin, the generic `<SchemaDrivenPlugin>` page component fetches the schema from `/api/plugins/{name}/schema`
3. `<SchemaFormRenderer>` renders the form using percona-ui components (TextInput, SelectInput, etc.)
4. On submit, the form POSTs to `/api/plugins/{name}/execute` (or whichever execution endpoint the plugin exposes)
5. The shared `<TaskLogViewer>` streams execution logs via SSE
6. The shared `<TaskHistoryTable>` displays past runs

### Path B — Custom React Plugins (escape hatch)

**Used by**: plugins with genuinely unique UI complexity — multi-step wizards, interactive visualizations, custom real-time displays, external API integrations beyond task execution.

**What the plugin developer writes:**

1. **Backend API routes** (same as Path A)
2. **Custom React page components** in `frontend/packages/plugins/{name}/`
3. Custom hooks for plugin-specific data
4. **Reuses shared framework components** (`<TaskLogViewer>`, `<ChainBuilder>`, `<TaskHistoryTable>`, `<ServiceSelector>`, etc.) — even custom plugins do not reimplement these

**Custom plugins still follow the gateway pattern**: they call SEP plugin routes, which internally proxy to Inventory/Tasks sub-apps. They never call sub-apps directly from the frontend.

## The Snippets Pattern — The Schema-Driven Prototype

<aside>
💡

**SEP already has a working schema-driven plugin**: the **snippets** plugin. Understanding how it works is essential because the migration's schema-driven plugin design extends it rather than inventing something new.

</aside>

**How snippets work today:**

Each snippet is a file (Python, Bash, etc.) with a YAML frontmatter block describing the script's parameters:

```python
#!/usr/bin/env python3
# ---
# parameters:
#   - name: "hostname"
#     type: "str"
#     required: true
#     label: "Target hostname"
#     description: "The hostname to connect to"
#   - name: "verbose"
#     type: "bool"
#     required: false
#     label: "Verbose output"
#     default: false
#   - name: "port"
#     type: "int"
#     required: true
#     default: 3306
#     ge: 1
#     le: 65535
# requires_packages:
#   - "PyMySQL[rsa,ed25519]"
# sudo: "ask"
# ---
import sys
# ... script code ...
```

The backend parses the frontmatter at load time and produces:

- `BaseSnippet.meta` dict (parsed YAML)
- `BaseSnippet.get_execution_model()` — a **dynamically-built Pydantic model** from `meta["parameters"]`
- `BaseSnippet.to_form()` — HTML form with fieldsets, inputs, validation rules

Key classes (in `app/sep/plugins/snippets/models.py`):

- **`SnippetMetaParameter`** (Pydantic model) — declares a single parameter with fields: `name`, `py_type` (`str`/`int`/`float`/`bool`), `required`, `positional`, `label`, `placeholder`, `description`, `group` (fieldset), `min_length`, `max_length`, `pattern`, `gt`, `lt`, `ge`, `le`, `step`, `choices`, `default`, `html_elem` (TEXT vs TEXTAREA), `arg_format`
- **`BaseSnippetArgs`** (Pydantic base) — dynamically instantiated with fields from the parameters list
- **`BaseSnippet`** — the main model, exposes `get_execution_model()`, `to_form()`, `execution_interpreter`, etc.

**Why this matters**: the schema lives **in data** (a Pydantic model or dict), not in code. Anyone who can write a YAML block can create a new snippet. The Pydantic model is generated at runtime from that YAML. There is no hand-written HTML form, no hand-written React component. The UI is a pure function of the schema.

**This is exactly the model we want for all schema-driven plugins.** The migration generalizes the snippets pattern to full plugins.

## Plugin Schema — Design Sketch

<aside>
📌

**Note**: The exact final shape of the plugin schema is a Wave 0 task. The sketch below shows the intent; the implementation team will refine it.

</aside>

```python
# app/sep/plugins/checksums/schema.py
from app.sep.plugins.framework.schema import (
    PluginSchema,
    FormSection,
    ServiceField,
    SchemaField,
    StringField,
    ChoiceField,
    BoolField,
    IntegerField,
    ListView,
    Column,
)

plugin_schema = PluginSchema(
    name="checksums",
    display_name="Checksums",
    description="Run data consistency checks via pt-table-checksum",
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
                    description="The MySQL service to check",
                ),
                SchemaField(
                    name="schema",
                    required=False,
                    depends_on="service",
                    label="Schema",
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
                    label="Max replica lag (s)",
                ),
            ],
        ),
    ],

    # Capabilities the shared framework exposes automatically if enabled
    capabilities=dict(
        chaining=True,
        alert_on_fail=True,
        scheduling=True,
    ),

    list_view=ListView(
        columns=[
            Column("name", label="Name", sortable=True),
            Column("service", label="Service", sortable=True),
            Column("status", label="Status", sortable=True),
            Column("last_run", label="Last run", sortable=True, format="relative"),
        ],
        default_sort="-last_run",
    ),
)
```

The backend exposes this schema at `GET /api/plugins/checksums/schema` (returned as JSON, serialized by the Pydantic model). The React `<SchemaFormRenderer>` reads it and renders the form using percona-ui inputs, with reactive fields (`depends_on="service"` → SchemaField populates when Service changes, via the `ServiceSelector` cascade).

**Schema field types that Wave 0 must ship:**

| Field type | Backend | React rendering | Notes |
| --- | --- | --- | --- |
| `StringField` | Pydantic `str` with constraints | `TextInput` | Min/max length, regex pattern |
| `IntegerField` | Pydantic `int` | `TextInput` type=number | Min/max, step |
| `FloatField` | Pydantic `float` | `TextInput` type=number | Min/max, step |
| `BoolField` | Pydantic `bool` | `SwitchInput` or `CheckboxInput` | Default |
| `ChoiceField` | Pydantic `Literal` / `Enum` | `SelectInput` or `RadioGroup` | Choices + default |
| `MultiChoiceField` | Pydantic `list[str]` | `AutoCompleteInput` multi | Choices |
| `TextAreaField` | Pydantic `str` | `TextInput` multiline | Rows |
| `DateTimeField` | Pydantic `datetime` | `DateTimePickerInput` | Min/max datetime |
| `FileField` | Pydantic bytes / path | `FileInput` | Accept types |
| `ServiceField` | Custom | `ServiceSelector` | Service type filter |
| `SchemaField` | Custom | `SchemaSelector` | Depends on ServiceField |
| `TableField` | Custom | `TableSelector` | Depends on SchemaField |
| `HostField` | Custom | Select from executor hosts context |  |
| `YamlField` | Pydantic `str` | `TextInput` with YAML lint (future) | For backup configs |

Most of these map directly to percona-ui components. Only `ServiceField`, `SchemaField`, `TableField`, and `HostField` are genuinely custom — they live in our framework package.

## Shared Framework Layer

These are the React components, hooks, and utilities that Wave 0 delivers. They replace the current `static/js/*.js` files and shared Jinja2 partials.

### Inventory

| Shared component | Replaces | Purpose | Wave 0 scope |
| --- | --- | --- | --- |
| `<SchemaFormRenderer>` | Hand-written HTML forms, plugin `models.py` form classes rendered via Jinja2 | Renders a form from a PluginSchema, hands off values to a submit handler | **Must have** |
| `<TaskLogViewer>`  • `useTaskLogs()` | `static/js/logs.js` (~700 lines), modal + SSE connection | Streams SSE logs for a task history ID, displays stdout/stderr/events with search, download, pause | **Must have** |
| `useExecutionEvents()` | Parts of `logs.js` | Hook for execution events (Nomad job lifecycle) | **Must have** |
| `<TaskHistoryTable>` | `templates/tasks/partials/running-tasks.html.j2`, `completed-tasks.html.j2` | Displays running and completed task runs with status badges, duration, logs button | **Must have** |
| `<ChainBuilder>` | `static/js/chain-builder.js`, `templates/tasks/partials/chain-builder.html` | Visual chain builder with cycle detection, form integration | **Must have** |
| `<ServiceSelector>` | `static/js/schema-selector.js` (service parts) | Service picker with type filter, cascades to `<SchemaSelector>` | **Must have** |
| `<SchemaSelector>` | `static/js/schema-selector.js` (schema parts) | Schema picker, depends on selected service | **Must have** |
| `<TableSelector>` | `static/js/schema-selector.js` (table parts) | Table picker, depends on selected schema | **Must have** |
| `<AlertOnFailField>` | `templates/tasks/partials/create-form-alert-on-failure-input.html.j2` | Alert-on-fail form field, conditional on alert providers | **Must have** |
| `<ScheduledTasksPanel>` | `templates/tasks/partials/scheduled-tasks.html.j2`, `static/js/scheduled.js` | Displays and manages scheduled/periodic tasks | **Should have** (could slip to Wave 1 if time tight) |
| API client | ad-hoc `$.ajax` calls | Axios wrapper + generated types + React Query hooks | **Must have** |
| `<AuthProvider>`  • `useAuth()` | Cookie handling scattered in templates | Auth context, login/logout flows, Bearer token support | **Must have** |
| `<NotificationProvider>`  • `useNotification()` | `templates/partials/messages.html.j2`, `static/js/app.js` | Toast notifications (uses percona-ui `NotistackMuiSnackbar`) | **Must have** |
| Theme provider | Custom CSS | Wraps `@percona/percona-ui` `<ThemeContextProvider theme="sep">` | **Must have** |
| Router + layout | Sidebar partial + custom JS | MUI-based sidebar with plugin navigation, main layout | **Must have** |

### Why build this FIRST (in Wave 0)

If we migrate a plugin **before** the framework layer exists, we either:

1. Reimplement chain building, log streaming, task history, and selectors in that plugin's React code (duplication), or
2. Leave those features broken in the migrated plugin (regression)

Neither is acceptable. The framework layer is therefore a hard prerequisite for any plugin migration beyond the trivial inventory CRUD.

### Validation plan for the framework layer

Wave 0 doesn't ship in a vacuum. The plan is:

1. Build the framework layer components with Storybook stories (each component demonstrated in isolation)
2. Build **one schema-driven plugin (checksums)** end-to-end using the framework
3. Build **one custom React plugin (alters or backup)** end-to-end using the framework to validate the escape-hatch path

If the framework works for both a simple and a complex plugin, it's ready. If not, we adjust before Wave 1 starts.

## Plugin Classification (Corrected)

This classification is based on deep analysis of every plugin's routes, templates, deps, and JS usage. It replaces the earlier incorrect classification.

| Plugin | Path | Complexity | Reason |
| --- | --- | --- | --- |
| snippets | A (Schema) | LOW | Already schema-driven (YAML frontmatter). Just needs the React form renderer |
| inventory | A (Schema) | LOW | CRUD with existing Inventory API. Lists/details only |
| checksums | A (Schema) | MEDIUM | Form → task. Large form (~20 fields) but no custom interactions |
| report | A (Schema) | MEDIUM | Simple form + result display (template-only today, needs backend routes) |
| atw | A (Schema) | MEDIUM | Single-route, delegates to snippet execution |
| dipper | A (Schema) | MEDIUM | Service selection + script preview + execution history |
| alert_troubleshooting | A (Schema) | MEDIUM | Snippet execution proxy with output polling, accordion of alerts |
| tasks | A (Schema) | MEDIUM | Generic task management; mostly shared components + schema form |
| backup | A (Schema) | MEDIUM | YAML backup config, upload providers. May need custom config preview panel (could be a schema field extension) |
| backup_mongo | A (Schema) | MEDIUM | PBM with multi-task atomic creation. The multi-task creation is a backend concern; the form itself is schema-driven |
| backup_pg | A (Schema) | MEDIUM | Same pattern as backup |
| alerts | B (Custom) | HIGH | Not task-based. PMM API integration, backup/restore logic, PagerDuty, custom error handling |
| alters | B (Custom) | HIGH | 40+ field form in 963-line template, atomic multi-task creation (execute + dry-run + pre-checks), complex argument construction, dry-run mode toggle, dynamic field dependencies |
| archives | B (Custom) | HIGH | 30+ field form in 1021-line template, YAML config manipulation, multi-task orchestration |

**Summary**: **11 schema-driven plugins, 3 custom React plugins.**

### Custom-plugin rationale (the 3 HIGH plugins)

**alerts** is not task-based — it doesn't create Celery/Nomad tasks. It integrates with PMM's alerting API, handles backup/restore of alert configurations, manages PagerDuty contact points, and has complex retry/conflict-resolution error handling. None of this fits the "form → task → execution" mold. It needs a custom React UI.

**alters** has a form so large and dynamic that it cannot be reasonably described as a static schema. It creates three related tasks atomically (execute, dry-run, pre-checks), toggles between execute and dry-run modes, parses pt-online-schema-change arguments, validates executor-host matching, and has complex field dependencies. The schema-driven path could in theory handle this with enough schema DSL extensions, but the resulting schema would be more complex than custom React.

**archives** has the same shape as alters — massive form, multi-task creation, YAML config manipulation — and is the second-largest form in the codebase (1021-line template).

For all three, **the custom React code still uses the shared framework layer**: the `<TaskLogViewer>`, `<ChainBuilder>`, `<TaskHistoryTable>`, and selectors are reused. Only the form itself is custom.

### Complexity is not inherited from cross-cutting concerns

A plugin is **not** HIGH just because it streams logs, supports chaining, or shows task history. Every task-based plugin does all of those things, and they are all handled by the framework layer. A plugin is HIGH only if its plugin-specific UI is irreducibly complex.

## Implications for Future Plugin Development

The schema-driven plugin model is intended to enable **plugin creation by non-core developers** — including customers and partners in the future. The goals:

1. **Write a Python schema file and a few API routes** and get a working UI for free
2. **No frontend expertise required** to create a simple plugin
3. **Plugin schema is data, not code** — could eventually support schemas declared in config files (like snippets frontmatter) or even in the UI
4. **Complex plugins still possible** via the Path B escape hatch

This is a **strategic** goal, not a Wave 0 deliverable. Wave 0 ships the framework layer that makes it possible. Later work will refine the schema DSL, add more field types, and explore file-based or UI-based plugin declaration.

**Not in scope for this migration**: The fully declarative "just write a YAML file and drop it in a folder" plugin creation flow. The snippets plugin already does that for snippets; generalizing to full plugins with API endpoints and custom logic is a follow-up initiative.

## Upcoming Complexity to Design For

The backlog contains work that the plugin model should anticipate:

- **SEP-927 Epic (Connectivity Checks)** — auto pre-checks on task creation, manual check button in inventory. The schema-driven plugin model should support "pre-check" form sections and progress indicators.
- **SEP-511 Epic (Data Masking)** — decrypt masked logs/files, admin PII selection UI. The `<TaskLogViewer>` needs to support conditional decryption. The schema system needs conditional fields.
- **SEP-923/924/925 (Pagination)** — all list views need pagination from day 1. The `<TaskHistoryTable>` and the schema-driven list view must ship with pagination.
- **SEP-187 (Class-based viewsets)** — the backend plan to consolidate plugin CRUD into class-based viewsets. Aligns with the schema-driven pattern: a plugin declares its viewset + schema and gets both API routes and UI.
- **SEP-379 (SSE log streaming improvements)** — offset parameter, pause/resume. The `useTaskLogs()` hook design must support both.

These are not Wave 0 scope, but the Wave 0 framework design must not foreclose them.
