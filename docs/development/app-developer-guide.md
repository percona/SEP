# SEP App Developer Guide

This guide takes a contributor with no prior framework knowledge from zero to a
working, conformant SEP app. It covers the app framework under
`app/sep/apps/framework/` — the declarative spine that derives a task app's whole
HTTP router from a single object, the model-first form DSL that drives the create
form and the generated schema, the escape hatches for the cases the spine does
not cover, and how the whole thing is tested.

> **In a hurry?** Jump to [§3 Quickstart](#3-quickstart) to scaffold a running app
> with `make startapp`, then come back for the concepts. Reading top to bottom is
> the recommended path: the Quickstart's very first choice — which scaffolder
> flavor to use — is the decision [§2 Choosing an authoring surface](#2-choosing-an-authoring-surface)
> teaches.

Every code example below is either copied verbatim from a real, CI-exercised app
under `app/sep/apps/` or executed against the live framework. Each example carries
an HTML comment naming its source file and symbol (e.g.
`<!-- src: app/sep/apps/checksums/models.py :: ChecksumsForm -->`) so you can diff
it against the tree as the framework evolves. A reference-integrity test
(`tests/docs/test_guide_references.py`) parses those markers and fails CI if a
cited file or symbol is renamed, moved, or deleted — so a stale example breaks the
build instead of silently misleading the next reader. Two examples that no real
app exercises are labelled `<!-- constructed -->`; they were executed against the
framework before being pasted here.

---

## Table of contents

1. [Mental model](#1-mental-model)
2. [Choosing an authoring surface](#2-choosing-an-authoring-surface)
3. [Quickstart](#3-quickstart)
4. [Form DSL reference](#4-form-dsl-reference)
5. [Escape-hatch ladder](#5-escape-hatch-ladder)
6. [Testing](#6-testing)
7. [Migration cookbook](#7-migration-cookbook)

---

## 1. Mental model

### Two layers: a declarative spine over a composable toolbox

The framework is two layers. Underneath is a **toolbox** of composable helpers —
schema derivation, response builders, cascade helpers, spec builders, the rules
engine. On top is a **declarative spine**: a single `TaskExecutionApp` object whose
constructor arguments ("knobs") describe *what* the app is, and from which the
framework *derives* the entire HTTP surface — schema, list, detail, create, update,
execute, delete — with no hand-written routes.

You describe the app; the framework builds the router. When the declarative knobs
do not express something you need, you reach one rung down the
[escape-hatch ladder](#5-escape-hatch-ladder) into the toolbox, not out of the
framework entirely.

### `BaseApp` vs `TaskExecutionApp`

- **`BaseApp`** (`app/sep/apps/framework/base.py`) is the uniform registry entry:
  the minimal thing the registry can discover, bind, and mount. It carries the
  identity and navigation metadata and an optional API router. Reach for it
  directly only when your app is *not* a task-execution app (the bottom rung of the
  ladder).
- **`TaskExecutionApp`** (`app/sep/apps/framework/apps.py`) is the declarative spine
  for the common case: an app that creates, lists, and runs **tasks**. It subclasses
  `BaseApp` and adds the create-model, views, capabilities, and spec-builder knobs
  from which the task router is derived. Almost every app you write is a
  `TaskExecutionApp`.

A minimal task app is one object. Here is the core of the Checksums app, with the
deprecated Jinja wiring elided (see the [Migration cookbook](#7-migration-cookbook)):

<!-- src: app/sep/apps/checksums/app.py :: app -->
```python
app = TaskExecutionApp(
    name="checksums",
    display_name="Checksums",
    uri_path="/checksums",
    css_class="checksums",
    nav_order=7,
    nav_icon=NavIcon.CHECK_CIRCLE,
    description="Run pt-table-checksum to verify MySQL replication consistency.",
    owner=OWNER,
    create_model=ChecksumsForm,
    views=checksums_views,
    payload_builder=build_checksums_payload,
    capabilities=AppCapabilities(update=True, delete=True),
    service_type=ServiceTypeEnum.MYSQL,
    list_filter=ListFilterConfig(status=True, service_type=True),
    response_context_provider=get_username_mapping,
)
```

Three knobs carry the weight: `create_model` (the form/body model, [§4](#4-form-dsl-reference)),
`views` (section titles, list columns, detail layout, and UI capability flags), and
`capabilities` (which derived mutation routes to switch on, [§5](#5-escape-hatch-ladder)).

### How the registry discovers and activates apps

Apps are **not** wired by hand into a router file. Activation is data, in
`settings.yaml`:

<!-- src: settings.yaml -->
```yaml
default:
  SEP:
    APPS:
      - MODULE_NAME: checksums
        ENABLED: true
```

At startup, `build_app_registry` walks the `SEP.APPS` list in order, imports each
module, and uses its exported `app` object (a `BaseApp` / `TaskExecutionApp`):

<!-- src: app/sep/apps/framework/registry.py :: get_app_registry -->
```python
@lru_cache(maxsize=1)
def get_app_registry() -> AppRegistry:
    """Return the process-wide registry built over ``sep_settings.APPS``."""
    return build_app_registry(sep_settings.APPS)
```

The registry is a lazy `@lru_cache` accessor, built once per process from
`sep_settings.APPS`. `build_apps_router` then iterates that registry and mounts each
app's derived router under `/api/apps/{key}`:

<!-- src: app/sep/api/router.py :: build_apps_router -->
```python
def build_apps_router(registry: AppRegistry) -> APIRouter:
    """Build the ``/apps`` sub-router by iterating the app registry."""
    apps_router = APIRouter(
        prefix="/apps", dependencies=[RequireBearerForUnsafeMethods]
    )
    for app in registry:
        if app.api_router is None:
            continue
        apps_router.include_router(app.api_router, prefix=f"/{app.key}")
    return apps_router
```

> **Location note:** `build_apps_router` lives in `app/sep/api/router.py`, **not** in
> `framework/registry.py`. `get_app_registry()` / `build_app_registry()` live in
> `framework/registry.py`; the router that consumes the registry lives with the
> other SEP API routers.

An app registered with `ENABLED: false` is discovered but its routes are guarded by
a per-app enable check — an admin turns it on from the App Manager without a redeploy.

### What "derived router" means

"Derived router" is the framework's core move: instead of writing `@router.get("/schema")`,
`@router.post("/")`, `@router.put("/{task_name}")`, and so on by hand, you declare
the app object and the framework **derives** those routes from it. The
`GET /schema` form comes from the `create_model` and `views`; `POST /` validates the
body against `create_model` and runs the spec/payload builder; `PUT`/`DELETE` are
switched on by `capabilities` and carry the framework's default protected-task and
running-conflict guards. You do not see the route functions — they are built for you
from the knobs.

### The copy hazard — scaffold, never copy a whole app

> **⚠ Do not copy an existing app to start a new one.** *Every* app in the tree that
> has a `routes.py` — **including every current `TaskExecutionApp`**
> (checksums, alters, archives, backup_mongo, backup_pg, mysql_backups, snippets, and
> the `backup_mongo/restore` and `mysql_backups/restore` sub-apps) —
> still threads a **deprecated** Jinja surface: a `jinja_router` argument, a
> `DeprecatedJinja2Route`, and repo-root templates at `templates/<slug>/*.html.j2`.
> If you copy a whole app, you inherit that deprecated surface. The only clean
> end-to-end starting point is the scaffolder (`make startapp`), whose templates
> under `framework/templates/` carry no legacy wiring.

The rule: **scaffold with `make startapp`; never copy a whole app.** When you want to
*lift a pattern* from an existing app (a form field, a rule, a cascade hook), copy
only that **named construct** — never its `routes.py`, its `jinja_router=` wiring, or
its `templates/` directory. The concrete deprecated surfaces to avoid are:

| Deprecated surface | Modern replacement |
|---|---|
| `jinja_router=` argument on the app | derived JSON router (omit it entirely) |
| `DeprecatedJinja2Route` | derived routes from `create_model` + `views` |
| repo-root `templates/<slug>/*.html.j2` | the React frontend + derived `GET /schema` |
| `alerts/loader.py` layout | the framework's `Capabilities(alert_on_fail=...)` path |

---

## 2. Choosing an authoring surface

Before you scaffold, decide **what kind** of app you are writing. The framework
supports two authoring surfaces, and the scaffolder's three flavors map onto them.

### The routing rule: snippet vs framework app

- **A flat, parameterized script with no inventory cascade** belongs in an
  **in-script YAML snippet** — the Snippet Manager runs it, and the form is described
  in a YAML header alongside the script. Choose this when the check is a single
  command whose only inputs are simple parameters, and it never needs to resolve
  inventory references or enforce relationships between fields.
- **Anything that needs cascade references, cross-field invariants, or import-time
  validation** belongs in a **framework marker-DSL app**. Choose this when the form
  must resolve inventory (service / schema / table / host references), enforce
  cross-field rules (this field is required only when that one is set), or validate
  its shape at class-definition time.

The dividing line is **inventory and invariants**. A snippet is prose-and-parameters;
a framework app is a typed model the server validates and derives a schema from.

### Mapping the three scaffolder flavors

`make startapp` offers three flavors that implement the rule:

| Flavor | Use when | Authoring surface |
|---|---|---|
| `task` | The app runs a task built from a typed form (the common case) — inventory refs, cross-field rules, a derived schema. | Framework marker-DSL app (`create_model` + `views` + a spec/payload builder). |
| `script` | The app executes scripts through the `ScriptSource` seam (like the Snippet Manager). | Framework app wrapping a `ScriptSource`; per-script forms come from the script, not a `create_model`. |
| `base` | The app is not a task-execution app at all — it needs a custom router and does not fit the derived spine. | `BaseApp` with a hand-written `api_router` (the bottom rung of the ladder). |

If in doubt, start with `task`: it is the flavor the spine is built for, and you can
step down to `base` later if the derived router genuinely cannot express your app.

---

## 3. Quickstart

`make startapp` scaffolds a new app end to end. Run it with no `NAME` to enter an
interactive wizard, or pass variables on the command line:

```bash
make startapp NAME=myapp TYPE=task DISPLAY_NAME="My App" \
    DESCRIPTION="Run my check." NAV_ICON=CHECK_CIRCLE
```

Recognised variables: `NAME`, `TYPE` (`task` / `script` / `base`), `DISPLAY_NAME`,
`DESCRIPTION`, `GROUP`, `SERVICE_TYPE`, `NAV_ICON`, `RUN_MODE` (`run-command` /
`run-python`, task flavor only), `COMMAND`, `PAYLOAD`, `SCRIPT`, `NO_INPUT`,
`ENABLE`, `DERIVE_UPDATE`, `DERIVE_DELETE`.

### What the scaffolder generates

For **`task`** (`RUN_MODE=run-command` shown; `run-python` emits `spec_run_python.py`
remapped onto `spec.py` instead of `spec.py`):

```text
app/sep/apps/myapp/
  __init__.py
  app.py          # the TaskExecutionApp definition
  models.py       # the create-form model (marker DSL)
  spec.py         # the run-command spec builder
  views.py        # section layout, list/detail views, capability flags
tests/app/sep/apps/myapp/
  __init__.py
  test_contract.py   # subclasses DerivedRouterContractTests
```

For **`script`**: `app.py`, `constants.py`, `__init__.py`, `source.py`,
`snippets/sample.sh` (replaced by the copied `--script` file when `SCRIPT=` is
supplied), plus `tests/__init__.py` and `tests/test_contract.py`.

For **`base`**: `api_routes.py`, `app.py`, `__init__.py`, `schema.py`, plus
`tests/__init__.py` and `tests/test_contract.py`.

### What the scaffolder writes automatically

The scaffolder registers the app in `settings.yaml` — and **only** `settings.yaml`.
It inserts a `SEP.APPS` entry, **disabled** unless you pass `ENABLE`:

```text
Scaffolded 'task' app 'myapp':
  app:   app/sep/apps/myapp
  tests: tests/app/sep/apps/myapp

Registered 'myapp' DISABLED in settings.yaml. Manage it from the Admin App
Manager (Settings -> Apps) once you have filled in the skeleton.
```

The resulting `settings.yaml` entry:

```yaml
      - MODULE_NAME: myapp
        ENABLED: false
```

### The manual steps that remain

The scaffolder does **not** finish the app for you. After scaffolding:

1. **Fill in the skeleton** — the generated `models.py`, `spec.py`, and `views.py`
   are stubs; write your fields, spec builder, and views.
2. **Register the frontend route and navigation** — this is **not** automated. Add
   the app's route and nav entry in
   `frontend/packages/shell/src/appNavConfig.ts` and
   `frontend/packages/shell/src/appRegistry.tsx`, and supply the `--nav-icon`.
3. **Enable the app** — it is registered **disabled**. Turn it on from the Admin App
   Manager (Settings → Apps), or scaffold with `ENABLE` for a dev box.

Task apps need **no database migration** (tasks are stored generically), and the
scaffolder does not print a `.claude/references` regen step.

### Verify it end to end

Run the generated contract test — it exercises the whole derived HTTP surface
against your definition:

```bash
pytest tests/app/sep/apps/myapp/test_contract.py -v
```

The CI `startapp-check` gate (`make startapp-check`, wired into
`.github/workflows/python.yaml`) proves all three flavors scaffold and pass their
contract suite on every PR.

---

## 4. Form DSL reference

The form DSL is **model-first**: one Pydantic model is *both* the request body the
server validates *and* the source of the derived `GET /schema` form. You annotate
each field with markers — `Ui(...)` for presentation, reference markers for
inventory, `Choices(...)`/`ArgFormat(...)` for behaviour — and the framework derives
the form and the command from them. The public surface is exported from
`app/sep/apps/framework/form_dsl/__init__.py`.

### `AppFormModel` / `TaskFormModel` and `Ui()`

`AppFormModel` is the base form model; `TaskFormModel` extends it for task apps,
supplying the shared `task_name` / `hostname` Task-section fields and the hidden
`alert_on_fail` capability control, so your model declares only its own fields.
`Ui(...)` carries the per-field presentation the type cannot express — label,
section, description, display order, dependency:

<!-- src: app/sep/apps/checksums/models.py :: ChecksumsForm -->
```python
service_id: Annotated[
    int,
    ServiceRef(service_types=(ServiceTypeEnum.MYSQL,), check_connectivity=True),
    Ui(label="Database Host", section="Task"),
]
```

Field **declaration order is load-bearing**: the derived section order follows each
section's first field, and within a section the field order follows declaration
order.

### `ArgFormat`

`ArgFormat` marks a field as a command-line argument and controls how it is rendered
into the command. A bare `ArgFormat()` derives the flag name from the field name;
`ArgFormat("--explain")` pins an explicit flag:

<!-- src: app/sep/apps/checksums/models.py :: ChecksumsForm -->
```python
explain_arg: Annotated[
    bool,
    ArgFormat("--explain"),
    Ui(
        label="Explain (dry run)",
        section="Flags",
        description="Show but do not execute checksum queries",
    ),
] = False
```

### `Choices` and `Option`

`Choices` provides explicit options for a choice field, winning over any
type-derived options. The common form is a tuple of `(value, label)` pairs:

<!-- src: app/sep/apps/checksums/models.py :: ChecksumsForm -->
```python
recursion_method: Annotated[
    str,
    Choices(
        (
            ("default", "Default"),
            ("processlist", "Processlist"),
            ("hosts", "Hosts"),
            ("dsn", "DSN"),
            ("none", "None"),
        )
    ),
    Ui(section="Recursion", required=True),
] = "processlist"
```

When an option must render as **non-selectable** with an explanatory tooltip, use an
`Option(...)` instance instead of a bare tuple. No app in the tree currently needs
this, so the example below is **constructed** and was executed against the framework
(it derives a schema in which the `thorough` option is marked `disabled`):

<!-- constructed -->
```python
strategy: Annotated[
    str,
    Choices(
        (
            Option(value="fast", label="Fast"),
            Option(
                value="thorough",
                label="Thorough",
                disabled=True,
                disabled_reason="Not available on this service tier.",
            ),
        )
    ),
    Ui(label="Strategy", section="Task"),
] = "fast"
```

`Option.disabled` is a UI hint only — server-side rejection of a disabled value
remains the app's `FormRules` responsibility (see the predicate DSL below).

### `FieldWidget`

`FieldWidget` overrides the input widget the frontend renders for a field. For a
multi-line YAML value, `FieldWidget.TEXTAREA`:

<!-- src: app/sep/apps/backup_mongo/models.py :: BackupForm -->
```python
backup_priority: Annotated[
    str | None,
    Ui(
        label="Node Priority (YAML)",
        section="BackupOptions",
        widget=FieldWidget.TEXTAREA,
        description="YAML mapping of mongod addresses to backup priority.",
    ),
] = None
```

### The four reference markers

Four markers bind a field to **inventory**: `ServiceRef`, `SchemaRef`, `TableRef`,
and `HostRef`. They make the field a dropdown resolved from inventory (optionally
`allow_custom=True` to also accept a typed name), and they drive the connectivity
and cascade wiring. The Alters app uses all four together:

<!-- src: app/sep/apps/alters/models.py :: AltersCreate -->
```python
hostname: Annotated[
    NonEmptyStr, HostRef(), Ui(label=EXECUTION_HOST_LABEL, section="Task")
]
service_id: Annotated[
    int,
    ServiceRef(service_types=[ServiceTypeEnum.MYSQL]),
    Ui(label="Database Host", section="Task"),
]
db_schema: Annotated[
    int | StrippedNonEmptyStr,
    SchemaRef(allow_custom=True),
    Ui(
        label="Schema",
        section="data",
        depends_on="service_id",
        description="Schema to alter; pick from inventory or type a name.",
    ),
]
db_table: Annotated[
    int | StrippedNonEmptyStr,
    TableRef(allow_custom=True),
    Ui(
        label="Table",
        section="data",
        depends_on="db_schema",
        description="Table to alter; pick from inventory or type a name.",
    ),
]
```

`depends_on` chains the dropdowns: choosing a service scopes the schema options,
choosing a schema scopes the table options.

### `FormLayout` and `SectionLayout`

Field **membership** and **order** in sections are declared on the model (via
`Ui(section=...)` and declaration order). The section **titles and metadata** — what
the model cannot express — live in `FormLayout` / `SectionLayout` inside the app's
`Views`:

<!-- src: app/sep/apps/checksums/views.py :: checksums_views -->
```python
checksums_views = Views(
    layout=FormLayout(
        sections=(
            TASK_SECTION_LAYOUT,
            SectionLayout(key="Data", title="Data"),
            SectionLayout(key="Recursion", title="Recursion"),
            SectionLayout(key="Flags", title="Flags"),
            SectionLayout(key="Advanced", title="Advanced"),
        )
    ),
    list_view=ListView(columns=default_columns(SERVICE_TYPE_COLUMN)),
    detail_view=DetailView(sections=[...]),
    capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
)
```

`SectionLayout` also carries `collapsible` / `collapsed_by_default` and the
section-level `forbidden` gates shown in the predicate DSL below.

### The predicate DSL (`rules.py`)

For invariants a single field cannot express, the framework has a small predicate
DSL: the field reference `F(...)`, the truthiness predicates (`truthy`, `present`,
…), boolean combinators (`&`, `|`, `not_`), and three rule envelopes — `FailRule`
(predicate-only invariants), `FieldGate` (gate a field or section), and
`CardinalityRule` (bound the count of present fields). App-scoped rules live in a
`FormRules` object on `__form_rules__`.

**`FailRule` + `F`** — MySQL Backups fails validation when a mode-owned boolean is
set outside its mode:

<!-- src: app/sep/apps/mysql_backups/models.py :: BackupCreate -->
```python
__form_rules__: ClassVar[FormRules] = FormRules(
    fail_when=tuple(
        FailRule(
            fail_when=truthy(name) & (F("backup_type") != owner_mode),
            error_fields=[name],
            message=(
                f"{name!r} must not be set when backup_type is not {owner_mode!r}."
            ),
        )
        for owner_mode, names in _MODE_BOOL_FIELDS.items()
        for name in names
    )
)
```

**`FieldGate`** — the same predicate DSL gates a whole section. Here the Mydumper
section is forbidden unless `backup_type == "M"`:

<!-- src: app/sep/apps/mysql_backups/views.py :: mysql_backups_views -->
```python
SectionLayout(
    key="Mydumper",
    title="Mydumper",
    collapsible=True,
    forbidden=(FieldGate(when=F("backup_type") != "M"),),
)
```

**`CardinalityRule`** — bound how many of a set of fields may be present. No app in
the tree uses it, so this example is **constructed** and was executed against the
framework (a form with neither host set is rejected with the custom message):

<!-- constructed -->
```python
__form_rules__: ClassVar[FormRules] = FormRules(
    cardinality_rules=(
        CardinalityRule(
            fields=["primary_host", "secondary_host"],
            min=1,
            message="Select at least one target host.",
        ),
    )
)
```

---

## 5. Escape-hatch ladder

When the declarative knobs do not express what you need, step **down** the ladder one
rung at a time. Each rung is more code than the last; stop at the first one that
covers your case, and prefer a knob over a custom route.

### Rung 1 — `AppCapabilities` flags

The cheapest step: switch derived routes on or off. `AppCapabilities` toggles which
of the derived mutation routes (create, update, delete, execute, detail) the spine
builds. Checksums turns on the derived update and delete:

<!-- src: app/sep/apps/checksums/app.py :: app -->
```python
app = TaskExecutionApp(
    name="checksums",
    ...
    capabilities=AppCapabilities(update=True, delete=True),
)
```

Turning a capability **off** suppresses the derived route so a custom one can take
its place (Alters sets `detail=False` so its satellite-resolving detail route wins).

### Rung 2 — `extra_routes`

When you need a route the spine does not derive (an approval endpoint, a manual
refresh, a download), hand the app a router via `extra_routes`. Snippets carries
three:

<!-- src: app/sep/apps/snippets/app.py :: app -->
```python
app = TaskExecutionApp(
    name="snippets",
    ...
    script_source=snippet_source,
    capabilities_provider=_snippets_capabilities_provider,
    extra_routes=(approval_router, maintenance_router, artifact_router),
)
```

Each router is an ordinary FastAPI `APIRouter`, mounted under the app's prefix:

<!-- src: app/sep/apps/snippets/extra_routes.py :: maintenance_router -->
```python
maintenance_router = APIRouter()


@maintenance_router.post(
    "/refresh", dependencies=[IsApiAuthenticated, IsManualSyncEnabled]
)
async def snippets_api_refresh(
    user: ApiAdminUser, session: SessionDep
) -> RefreshResponse:
    """Refresh the snippets cache from disk."""
    async with track_app_task(session, "snippets"):
        await update_snippets()
    logger.info("Snippets refreshed via JSON API by %s", user.username)
    return RefreshResponse(refreshed_at=utc_now())
```

### Rung 3 — handler overrides

When a derived route's *shape* is right but its response body needs custom
assembly, override the builder rather than replacing the route. PostgreSQL Backups
overrides the list and detail response builders (and their models) so the derived
bodies stay byte-identical to the legacy hand-written ones:

<!-- src: app/sep/apps/backup_pg/app.py :: app -->
```python
app = TaskExecutionApp(
    name="backup_pg",
    ...
    response_builder=build_backup_pg_api_task_response,
    detail_response_builder=build_backup_pg_api_detail_response,
    detail_response_model=BackupTaskDetailResponse,
)
```

`TaskExecutionApp` also exposes `update_handler` / `delete_handler`
(`app/sep/apps/framework/apps.py`) for fully replacing a mutation handler — no app
in the tree overrides those today; the `response_builder` override above is the same
rung one step lighter, so reach for the response builders first.

### Rung 4 — `response_context_provider` and cascade hooks

**`response_context_provider`** injects request-scoped context into every response
builder — the app names a provider, and the framework calls it and threads the
result through. Checksums uses it to resolve the username mapping:

<!-- src: app/sep/apps/checksums/app.py :: app -->
```python
app = TaskExecutionApp(
    name="checksums",
    ...
    response_context_provider=get_username_mapping,
)
```

The provider is an ordinary async callable:

<!-- src: app/sep/deps.py :: get_username_mapping -->
```python
async def get_username_mapping() -> dict[str, str]:
    """Create a mapping from user ID to username using the active auth provider."""
    users = await User.get_users()
    return {str(user.id): user.username for user in users}
```

The body is trimmed to show the provider shape; the real source additionally wraps
the fetch in error handling that logs and returns an empty mapping when the auth
provider is unreachable.

**Cascade hooks** are the heaviest rung short of leaving the spine: when a single
create must fan out into a group of related tasks (a parent plus derived satellites
and predecessors), build a `CascadeCreatePlan`. Alters assembles a parent execute
task, an imperative pre-checks predecessor, and a cascade closure:

<!-- src: app/sep/apps/alters/deps.py :: build_alters_cascade_plan -->
```python
async def build_alters_cascade_plan(
    body: AltersCreate,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> CascadeCreatePlan:
    """Build the cascade create plan for an alters task group."""
    parent_task = await build_alters_task(body, inventory_api)
    pre_checks_template = await build_pre_checks_task_payload(
        parent_task, task_api=tasks_api
    )
    return CascadeCreatePlan(
        parent_write=parent_task,
        form=body,
        cascade=lambda api: cascade_create_alters_group(
            api, parent_task, pre_checks_template, body
        ),
    )
```

The `cascade_create_*` / `cascade_update_*` / `cascade_delete_*` helpers in
`app/sep/apps/framework/cascade.py` are the toolbox the closure calls.

### Rung 5 — fall back to `BaseApp`

If the derived task router genuinely cannot express your app, drop to `BaseApp` with a
hand-written `api_router` (the scaffolder's `base` flavor). You lose the derived
surface but keep registry discovery, activation, and navigation. This is the last
rung — reach it only when every knob and hook above has failed, because a hand-written
router opts out of the contract suite's derived-surface guarantees.

### Script-backed apps: `ScriptSource`

Apps that execute **scripts** rather than a typed form use the `ScriptSource` seam
(`app/sep/apps/framework/script_source.py`): each script supplies its own form
schema, and listing/execute/history derive from the source. Snippets wires one:

<!-- src: app/sep/apps/snippets/script_source.py :: snippet_source -->
```python
snippet_source = ScriptSource(
    script_dir=snippets_settings.SNIPPETS_DIR,
    load_script=_load_script,
    list_scripts=_list_scripts,
    build_form_schema=_build_form_schema,
    build_execution_meta=_build_execution_meta,
    list_response=_list_response,
    static_schema=SNIPPETS_PLUGIN_SCHEMA,
    list_response_model=SnippetResponse,
)
```

The app then passes `script_source=snippet_source` instead of a `create_model`
(`ScriptProtocol` and the `script_helpers.py` helpers back this seam).

---

## 6. Testing

### The derived-router contract suite

Because the router is *derived*, the framework can test the whole HTTP surface
generically. `DerivedRouterContractTests`
(`tests/app/sep/apps/framework/contract_suite.py`) exercises schema, list, detail,
create, update, execute, delete, auth, 404, conflict, connectivity, and injected
extras against the **real** app definition. Your app's contract test is a subclass
that binds the definition to `app_def` — the scaffolder emits exactly this:

<!-- src: tests/app/sep/apps/checksums/test_contract.py :: TestChecksumsContract -->
```python
class TestChecksumsContract(DerivedRouterContractTests):
    """Assert the checksums app's full derived HTTP surface, knob by knob."""

    app_def = checksums_app
    remapped_username = None
```

The suite reads the contract from the app's own knobs, so switching a capability on
or changing a response model is covered automatically — no per-route test to write.
App-specific behaviour the generic suite does not seed (a custom guard, a bespoke
route) gets a standalone test beside the contract subclass.

### The shared fixtures

The suite's fixtures live in `tests/app/sep/apps/conftest.py`: `contract_client` (an
authenticated `TestClient` bound to the app definition under test), `mock_task_api`,
and `mock_inventory_api` (the two boundary APIs, seeded per test):

<!-- src: tests/app/sep/apps/conftest.py :: contract_client -->
```python
def contract_client(
    request: pytest.FixtureRequest,
    regular_user: CasdoorUser,
    mock_task_api: MockTaskAPI,
    mock_inventory_api: MockInventoryAPI,
) -> TestClient:
    """Return an authenticated contract client for the bound definition."""
    return build_contract_client(
        _bound_app_def(request),
        user=regular_user,
        tasks_api=mock_task_api,
        inventory_api=mock_inventory_api,
    )
```

### Factory conventions

Test data comes from `polyfactory` factories in `tests/app/factories.py` — build with
`.build()` and customise inline (`CasdoorUserFactory.build(is_admin=True)`). Never
hand-roll a `dict` for a model a factory already covers. The contract suite's own
task/inventory seeding goes through the `MockTaskAPI` / `MockInventoryAPI` helpers in
`tests/app/sep/apps/framework/kit.py`, not raw dicts.

### How conformance runs in CI

Two CI gates keep apps honest beyond their own contract test:

- **Conformance** — `app/sep/apps/framework/conformance.py` defines structural
  detectors (an app must not carry certain deprecated shapes, must wire the required
  knobs), run per-app by `tests/app/sep/apps/framework/test_conformance.py`.
- **Scaffold check** — `make startapp-check` (`scripts/startapp_check.py`, wired into
  `.github/workflows/python.yaml`) scaffolds all three flavors and runs their contract
  suites on every PR, so the Quickstart above cannot silently rot.

Both run under the ordinary `make test` / CI `pytest` invocation.

---

## 7. Migration cookbook

Moving an existing app onto the framework means **deleting** hand-written surface and
declaring knobs in its place. The framework and its legacy predecessor still coexist
in the tree, so the job is mostly subtraction. Work knob by knob, keeping the wire
format identical (the contract suite catches drift).

### Each deprecated pattern beside its modern replacement

| Deprecated pattern | Modern replacement |
|---|---|
| Hand-written JSON API router (`api_routes.py` with `@router.get`/`@router.post` per verb) | `TaskExecutionApp` knobs (`create_model`, `views`, `capabilities`) — the router is derived. |
| Hand-written `AppSchema` | Derived `GET /schema` from `create_model` + `views` (the `FormLayout`/`SectionLayout`/`Capabilities` carry what the model cannot). |
| `jinja_router=` argument on the app | Nothing — omit it. The derived JSON router replaces it; the frontend is React. |
| `DeprecatedJinja2Route` | Derived routes. |
| Repo-root `templates/<slug>/*.html.j2` | The React frontend consuming the derived schema. |
| `alerts/loader.py` layout | `Capabilities(alert_on_fail=...)` and the framework alert path. |
| Manual arg-string assembly | `ArgFormat` markers + the spec/payload builder. |
| Ad-hoc cross-field `if` checks in a route | The predicate DSL (`FailRule` / `FieldGate` / `CardinalityRule`) on `__form_rules__`. |

### Migration order

1. **Scaffold a sibling** with `make startapp` (do **not** edit in place first) to get
   a clean skeleton to move logic into.
2. **Move the form** into a `create_model` (marker DSL), lifting field types and
   defaults verbatim so the request body is unchanged.
3. **Move presentation** into `views` (`FormLayout`, `ListView`, `DetailView`,
   `Capabilities`).
4. **Move the command/payload logic** into the spec or payload builder.
5. **Switch on capabilities** and, only where the derived route cannot express the
   behaviour, add `extra_routes` or a handler override (walk the
   [escape-hatch ladder](#5-escape-hatch-ladder)).
6. **Delete** the hand-written `api_routes.py`, `AppSchema`, and — last — the
   `jinja_router` / `templates/` surface once the React route is live.
7. **Bind the contract suite** (`DerivedRouterContractTests`) and run it; it fails
   loudly on any wire-format drift from the legacy surface.

The migrated apps in the tree (checksums, backup_pg, mysql_backups, alters,
backup_mongo, snippets) are the worked references — but remember the copy hazard:
lift the *named construct* you need, never the whole app with its lingering
`jinja_router`/`templates/` holdovers.
