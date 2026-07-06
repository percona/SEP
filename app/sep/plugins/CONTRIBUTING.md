# Building a new SEP plugin

SEP plugins turn a **create form** (rendered in the React UI) into one or more
backend **tasks** that run a command or script on an executor host, and manage
that task's whole lifecycle: list, detail, create, update, execute, delete.

This guide is for contributors building a *simple* plugin — one form that
produces a task running a command. It focuses on the **model-first** path, where
you declare your fields once and the framework *derives* the wire schema
(`GET /schema`), the request bodies, and the CRUD routes for you.

At the end there's a complete, copy-pasteable skeleton you can rename and fill
in.

---

## 1. The mental model: three inputs → one `PluginSchema`

The schema a plugin serves is assembled from three things you author:

```
models.py  (fields + validation + markers)  ─┐
views.py   (titles, columns, detail layout) ─┼─►  derive_plugin_schema()  ─►  PluginSchema  ─► GET /schema
cascade    (derived + predecessor specs)    ─┘
```

- **The model** (`models.py`) supplies everything derivable from a field: its
  type, default, label, section, choices, and validation gates.
- **The views** (`views.py`) supply what a model can't express: section titles,
  list-table columns, the detail page, and UI capability flags.
- **The cascade specs** (`derived` / `predecessors`) describe *extra* tasks that
  run alongside or before the main one. Most simple plugins declare **neither**.

For a `TaskExecutionApp` (the recommended path), you never call
`derive_plugin_schema` yourself — the app definition does it internally from
`create_model`, `views`, and `cascade`. A standalone `schema.py` module (like
`alters/schema.py`) is only needed when you hand-build the schema for a bare
`BaseApp`.

---

## 2. Anatomy of a plugin package

```
app/sep/plugins/<name>/
├── __init__.py    # re-export `app`
├── models.py      # AppFormModel subclass (the form) + response model(s)
├── views.py       # Views(layout, list_view, detail_view, capabilities)
├── spec.py        # pure (form, resolved) -> RunCommandSpec builder
├── app.py         # TaskExecutionApp(...) definition
├── deps.py        # optional: custom guards / response builders
└── routes.py      # optional: legacy Jinja UI router
```

Reference examples in the tree, from simplest to most complex:

- **`checksums/`** — the cleanest model-first `TaskExecutionApp`. Copy this.
- **`backup_pg/`** — a `run-python` variant with custom response builders.
- **`alters/`** — the complex end: a hand-written `BaseApp` plus a standalone
  `schema.py` declaring a `-dry-run` derived task and a `-pre-checks`
  predecessor. Read this to understand cascades.

---

## 3. `models.py` — where the fields come from

Subclass `AppFormModel` and annotate each field with DSL **markers**. The markers
ride in `Annotated[...]` metadata; Pydantic ignores them during validation, and
the framework reads them back to build the schema. **Every field needs a `Ui(...)`
marker.**

```python
task_name: Annotated[NonEmptyStr, Ui(label="Task Name", section="task")]
```

### Marker reference

| Marker | Purpose |
|---|---|
| `Ui(label, section, ...)` | **Required on every field.** Presentation only: `label`, `section` (must match a `SectionLayout.key`), `description`, `order`, `required` override, `widget`, and a form-display `default`. |
| `ServiceRef(service_types, check_connectivity=...)` | Inventory service dropdown. Mark **exactly one** `ServiceRef` with `check_connectivity=True` when the model has more than one, or when the create route should probe connectivity. |
| `SchemaRef()` / `TableRef()` | Cascading inventory selectors. **Require** `Ui(depends_on="<field>")` naming the field that drives their options. |
| `HostRef()` | Executor-target (Nomad/Celery) selector. At most one per model. |
| `Choices(((value, label), ...))` | Explicit dropdown options. (Or use an `Enum` / `Literal` base type.) |
| `ArgFormat(template=None)` | Maps the field to a CLI argument. Omit `template` to derive `--kebab-name=${value}` for a value field, or `--kebab-name` for a `bool` flag. Give an explicit template only when the CLI spelling diverges from the field name (e.g. `ArgFormat("--explain")`). |
| `Requires(when=...)` / `Forbidden(when=...)` | Conditional field-level gates using the `F(...)` predicate DSL. |
| `Hidden()` | Keep the field on the model + request body but omit it from the rendered form. |

### Type drives the widget

`bool` → toggle, `int`/`float` → number, `str` → text, `Enum`/`Literal`/`Choices`
→ dropdown, `datetime` → picker, `list[...]` + choices → multi-select. When the
type is ambiguous, override with `Ui(widget=FieldWidget.TEXTAREA | YAML | CHOICE
| MULTI_CHOICE)`.

### Two load-bearing ordering rules

1. **Field declaration order** determines both the CLI argument order (value args
   first, then flags — see `build_command_args`) and the form section order
   (each section appears where its first field is declared).
2. **`alert_on_fail`** is inherited from `AppFormModel` (as a `Hidden` field), so
   you don't declare it; the framework renders it from the `alert_on_fail`
   capability.

### Cross-field rules

Field-level gates go on the field (`Requires` / `Forbidden`). Rules spanning
multiple fields go in a class-level `__form_rules__ = FormRules(...)` using
`FailRule` / `CardinalityRule`, scoped per-section or plugin-wide. A simple
plugin usually needs none of this.

---

## 4. `views.py` — presentation the model can't express

Return a `Views(...)` bundle:

- `layout=FormLayout(sections=(SectionLayout(key=..., title=...), ...))` — one
  entry per `Ui(section=...)` key you used. **Every section key must appear
  here**, and every section listed here must have at least one field.
- `list_view=ListView(columns=[Column(key=..., label=...), ...])` — each
  `Column.key` must be a field on your **response model** (validated at load).
- `detail_view=DetailView(sections=[...])` — optional; dotted `data.*` paths into
  the stored task.
- `capabilities=Capabilities(chaining=..., scheduling=..., alert_on_fail=...,
  stats=...)` — UI feature toggles.

---

## 5. `spec.py` — turning the form into a task

Write a **pure** `(form, resolved) -> RunCommandSpec` function. It owns only the
command and its args; the framework's `assemble_envelope` wraps it with the
executor target, service name, and connectivity metadata.

`build_command_args(form)` reads your `ArgFormat` markers and emits all value
args (in field order) then all flag args — so for a "run a command with flags"
plugin you write almost no argument code.

```python
def build_example_spec(form: ExampleForm, resolved: ResolvedEntities) -> RunCommandSpec:
    service = resolved.service  # the resolved ServiceRef entity (may be None)
    return RunCommandSpec(
        command="example-tool",
        args=shlex.join(build_command_args(form)),
        extra_meta={"_service_host": service.node.address, "_service_port": service.port},
    )
```

For a Python-script task, return a `RunPythonSpec(config=..., requirements=...,
payload="file://...")` instead (see `backup_pg/spec.py`).

---

## 6. `app.py` — wiring and the escape-hatch ladder

Export a `TaskExecutionApp`. The framework builds the entire derived router from
it (`checksums/app.py` is the canonical minimal example):

```python
app = TaskExecutionApp(
    name="example",
    display_name="Example",
    uri_path="/example",
    nav_order=20,
    description="Run example-tool against a MySQL host.",
    owner=TaskOwner.EXAMPLE,
    create_model=ExampleForm,
    views=example_views,
    task_spec_builder=build_example_spec,
    capabilities=AppCapabilities(create=True, execute=True, update=True, delete=True),
    service_type=ServiceTypeEnum.MYSQL,
    list_status_filter=True,
    list_service_type_filter=True,
)
```

To fan out into a **group** of tasks, add
`cascade=Cascade(derived=[DerivedTask(...)], predecessors=[ChainedPredecessor(...)])`:

- `DerivedTask(name_suffix="-dry-run", arg_substitutions={"--execute": "--dry-run"})`
  creates a sibling that's a copy of the parent with literal substitutions
  applied to its args/payload.
- `ChainedPredecessor(name_suffix="-pre-checks", on_failure="halt")` creates a
  separate task chained to run *before* the parent.

When the declarative defaults aren't enough, reach for the **lowest** rung that
solves your problem:

1. Toggle a capability (`AppCapabilities`).
2. Override a handler/guard (`update_handler`, `delete_handler`,
   `update_guard`, `create_extra_deps`, `response_builder`, …).
3. Cascade hooks (`cascade=`).
4. `extra_routes` (appended last; a derived route always wins a path collision).
5. Fall through to a bare `BaseApp` + the route-derivation helpers used directly
   (this is what `alters/` does — the rare case).

---

## 7. Register the plugin

1. **Add a `TaskOwner`** enum value in `app/tasks/models.py` (e.g. `EXAMPLE =
   "EXAMPLE"`).
2. **Re-export `app`** from `__init__.py`.
3. **Activate it** in `settings.yaml` under `SEP.PLUGINS`:

   ```yaml
       - NAME: Example
         MODULE_NAME: example
   ```

   The `AppRegistry` imports the module, finds the exported `app`, and mounts its
   router under `/api/plugins/example`.

---

## 8. Tests

The framework ships a conformance suite and golden schema snapshots. Mirror an
existing plugin's tests:

- `tests/app/sep/plugins/framework/contract_suite.py` and `kit.py` — the shared
  conformance harness.
- `tests/app/sep/plugins/checksums/test_spec.py` / `test_schema.py` — copy the
  structure for your plugin's spec and derived schema.

Run the suite for your plugin with:

```bash
pytest tests/app/sep/plugins/example -q
```

---

## 9. Copy-pasteable skeleton

A ready-to-copy skeleton lives in [`_skeleton/`](./_skeleton/) — a complete
minimal plugin that runs `example-tool` against a MySQL service. Its files carry
a `.py.tpl` extension so the folder is never imported, activated, or collected by
tests; you turn it into a real plugin by copying it out and dropping the suffix.

```bash
cp -r app/sep/plugins/_skeleton app/sep/plugins/myplugin
cd app/sep/plugins/myplugin
rm README.md
for f in *.py.tpl; do mv "$f" "${f%.tpl}"; done
```

Then find-replace the placeholder tokens (`example` → your module name,
`Example` → your class prefix, `EXAMPLE` → your `TaskOwner`, `example-tool` → your
command, `/example` → your URI path), add the `TaskOwner` and `settings.yaml`
entry from section 7, and fill in your fields/args. See
[`_skeleton/README.md`](./_skeleton/README.md) for the exact steps (including a
one-line `sed` pass), and [`GETTING_STARTED.md`](./GETTING_STARTED.md) for a full
worked example that builds the `pt-mysql-summary` plugin from this skeleton.

What each file contains:

| File | Role |
|---|---|
| `__init__.py` | Re-exports `app`. |
| `models.py` | `ExampleForm(AppFormModel)` — the fields + markers (single source of truth), plus an `ExampleTaskResponse`. |
| `views.py` | `example_views = Views(...)` — section titles, list columns, detail layout, capability flags. |
| `spec.py` | `build_example_spec(form, resolved)` — the pure `RunCommandSpec` builder. |
| `app.py` | `app = TaskExecutionApp(...)` — derives every route. |

Out of the box that skeleton serves `GET /schema`, renders a create form with a
Task section (name, executor host, MySQL service) and an Options section (mode
dropdown, verbose flag, extra args), builds an `example-tool` run-command task on
create, and supports list, detail, execute, update, and delete — all derived from
the single `ExampleForm` declaration.
