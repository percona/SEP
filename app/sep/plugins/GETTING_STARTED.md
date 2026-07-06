# Getting started: build your first SEP plugin

This is a hands-on walkthrough. You'll start from the [`_skeleton/`](./_skeleton/)
plugin and apply only the changes needed to run
[`pt-mysql-summary`](https://docs.percona.com/percona-toolkit/pt-mysql-summary.html)
— a Percona Toolkit tool that connects to a MySQL server and prints a summary of
its status and configuration — as a managed SEP task with a UI form, list,
detail page, and execute button.

For the *why* behind each concept (the marker reference, the escape-hatch ladder,
cascades), see the reference: [`CONTRIBUTING.md`](./CONTRIBUTING.md). This guide
is the *how*: copy the skeleton, then make a handful of edits.

**What we're building.** A form that asks for a task name, an executor host, and
a MySQL service, plus a few `pt-mysql-summary` options. On create it builds a
`run-command` task like:

```bash
pt-mysql-summary --all-databases --sleep=10 -- --host=10.0.0.5 --port=3306
```

`pt-mysql-summary`'s own options (`--all-databases`, `--sleep`, …) come first; the
MySQL connection options come after `--` and are filled from the selected
inventory service.

**Prerequisites.**

- `pt-mysql-summary` must be installed on the executor host image that runs the
  task.
- The executor must reach the MySQL service and read its credentials (by default
  `pt-mysql-summary` reads the executor's `~/.my.cnf`; wiring an explicit
  `--defaults-file` is covered in "Level up").

Only two files need real edits (`models.py`, `spec.py`); everything else is
handled by the copy + token replacement in Step 1.

---

## Step 1 — Copy the skeleton and rename tokens

Copy the skeleton, drop the `.py.tpl` suffixes, and replace the placeholder
tokens with `pt-mysql-summary` names:

```bash
cp -r app/sep/plugins/_skeleton app/sep/plugins/pt_mysql_summary
cd app/sep/plugins/pt_mysql_summary
rm README.md
for f in *.py.tpl; do mv "$f" "${f%.tpl}"; done

# Order matters: replace the compound tokens before the bare "example".
# (macOS: `sed -i ''`; GNU/Linux: `sed -i`)
sed -i '' -e 's/example-tool/pt-mysql-summary/g' \
          -e 's/\/example/\/mysql-summary/g' \
          -e 's/example/pt_mysql_summary/g' \
          -e 's/Example/PtMysqlSummary/g' \
          -e 's/EXAMPLE/PT_MYSQL_SUMMARY/g' *.py
```

You now have `__init__.py`, `models.py`, `views.py`, `spec.py`, and `app.py`
wired together for a plugin named `pt_mysql_summary` — it already compiles and
would serve a schema. The remaining steps swap the skeleton's placeholder fields
and command for the real ones.

**Checkpoint:** `ls` shows five `.py` files and no `.tpl` / `README.md`.

---

## Step 2 — Register the task owner

Every task carries an `owner` so the framework can filter this plugin's tasks
apart from the rest. Add the value to `TaskOwner` in `app/tasks/models.py`:

```python
class TaskOwner(EnumFieldMixin, StrEnum):
    ...
    BACKUP_PG = "BACKUP_PG"
    PT_MYSQL_SUMMARY = "PT_MYSQL_SUMMARY"   # <-- add this
```

(The renamed `app.py` already references `TaskOwner.PT_MYSQL_SUMMARY`.)

**Checkpoint:** `from app.tasks.models import TaskOwner; TaskOwner.PT_MYSQL_SUMMARY`
resolves.

---

## Step 3 — Set the form fields (`models.py`)

Open `models.py` and replace the skeleton's **Options section** (the placeholder
`mode` / `verbose` / `extra_args` fields) with `pt-mysql-summary`'s options. Leave
the Task section (task name, executor host, MySQL service) exactly as it is.

Replace everything from the `# --- Options section` comment down to the end of the
Options fields with:

```python
    # --- Options section: pt-mysql-summary's own flags ----------------------
    all_databases: Annotated[
        bool,
        ArgFormat(),  # derives the flag "--all-databases"
        Ui(
            label="All Databases",
            section="options",
            description="mysqldump and summarize every database",
        ),
    ] = False
    databases: Annotated[
        str,
        ArgFormat(),  # derives "--databases=${value}"; emitted only when non-empty
        Ui(
            label="Databases",
            section="options",
            default=None,
            description="Comma-separated database names to summarize",
        ),
    ] = ""
    sleep: Annotated[
        int,
        ArgFormat(),  # derives "--sleep=${value}"
        Ui(
            label="Sleep",
            section="options",
            description="Seconds to sleep while gathering status counters",
        ),
    ] = 10
```

You can now drop the `Choices` import (no longer used). The Task section already
gives you the `HostRef` executor field and the `check_connectivity` MySQL
`ServiceRef`, so nothing else changes here.

**Checkpoint:** `PtMysqlSummaryForm.model_fields` lists `task_name, hostname,
service_id, all_databases, databases, sleep` (plus the inherited `alert_on_fail`).

---

## Step 4 — Build the command (`spec.py`)

`pt-mysql-summary` takes its own options first, then the MySQL connection options
after a `--` separator. The skeleton's builder only emits the form's `ArgFormat`
args; we need to append the connection args from the resolved service. Replace the
body of `build_pt_mysql_summary_spec` with:

```python
    service = resolved.service
    command = "pt-mysql-summary"
    args = build_command_args(form)

    connection_args = ["--", f"--host={service.node.address}"]
    if service.port is not None:
        connection_args.append(f"--port={service.port}")
    args = args + connection_args

    joined = shlex.join(args)
    return RunCommandSpec(
        command=command,
        args=joined,
        extra_meta={
            "_service_host": service.node.address,
            "_service_port": service.port,
            "_command_line": f"{command} {joined}",
        },
    )
```

For a task targeting a service at `10.0.0.5:3306` with "All Databases" checked,
this produces:

```bash
pt-mysql-summary --sleep=10 --all-databases -- --host=10.0.0.5 --port=3306
```

(`--sleep` is a value arg so it precedes the `--all-databases` flag; the order
among `pt-mysql-summary`'s own options is irrelevant to the tool.) The
`_command_line` meta is what the detail page's "Command line" card renders — the
skeleton's `views.py` already points at `data.meta._command_line`.

**Checkpoint:** calling the builder with a hand-built form and a fake resolved
service returns a `RunCommandSpec` whose `args` match the shape above.

---

## Step 5 — Tidy the app metadata (`app.py`)

The token replacement left the display name as `PtMysqlSummary`. Give it a proper
title and nav position:

```python
app = TaskExecutionApp(
    name="pt_mysql_summary",
    display_name="MySQL Summary",          # <-- was "PtMysqlSummary"
    uri_path="/mysql-summary",
    nav_order=21,                          # <-- pick an unused order
    description=(
        "Run pt-mysql-summary to capture a MySQL server's status and "
        "configuration."
    ),
    owner=TaskOwner.PT_MYSQL_SUMMARY,
    create_model=PtMysqlSummaryForm,
    response_model=PtMysqlSummaryTaskResponse,
    views=pt_mysql_summary_views,
    task_spec_builder=build_pt_mysql_summary_spec,
    capabilities=AppCapabilities(create=True, execute=True, update=True, delete=True),
    service_type=ServiceTypeEnum.MYSQL,
    list_status_filter=True,
    list_service_type_filter=True,
    response_context_provider=get_username_mapping,
)
```

Everything else the skeleton set (`service_type` MySQL, the list filters, the
username-mapping context) is exactly what this plugin wants, so leave it.

`views.py` needs no changes — its Task/Options sections, list columns, and
`_command_line` detail card already match. (Optionally relabel the service field
from "Database Host" to "MySQL Service".)

**Checkpoint:** `from app.sep.plugins.pt_mysql_summary.app import app` constructs
without raising. `TaskExecutionApp` validates the whole definition on import
(schema source, connectivity refs, arg formats, list columns), so any mistake
fails fast with a descriptive error.

---

## Step 6 — Activate the plugin (`settings.yaml`)

The registry only mounts activated modules. Add an entry under `SEP.PLUGINS`:

```yaml
    PLUGINS:
      ...
      - NAME: MySQL Summary
        MODULE_NAME: pt_mysql_summary
```

The registry imports the module, finds the exported `app`, and mounts its router
under `/api/plugins/pt_mysql_summary`.

---

## Step 7 — Run and verify

1. **Schema is served.** Fetch `GET /api/plugins/pt_mysql_summary/schema`. You
   should see two sections (`Task`, `Options`), a host field, a MySQL-only service
   field, and the three option fields with the right widgets (a bool toggle, a
   string, an integer).
2. **UI renders.** "MySQL Summary" appears in the navigation with a create form
   matching the schema.
3. **Create + execute.** Create a task and execute it. Inspect the created task's
   `data.meta.args` — it should be the `pt-mysql-summary ... -- --host=…` command
   from Step 4, and the detail page's "Command line" card should show the full
   invocation.

If the schema 404s, re-check the `settings.yaml` `MODULE_NAME` and that
`__init__.py` re-exports `app`.

---

## Step 8 — Add a test

Mirror an existing plugin's spec test. Create
`tests/app/sep/plugins/pt_mysql_summary/test_spec.py` and assert the builder
produces the expected `command` and `args` for a representative form (copy the
structure from `tests/app/sep/plugins/checksums/test_spec.py`). The framework's
shared conformance suite also exercises every registered app's derived schema and
routes automatically. Run:

```bash
pytest tests/app/sep/plugins/pt_mysql_summary -q
```

---

## Recap

Starting from the skeleton, you:

| Action | File |
|---|---|
| Copied + token-replaced the skeleton | `pt_mysql_summary/` (all five files) |
| Added the owner | `app/tasks/models.py` |
| Swapped in the tool's options | `models.py` |
| Added the `--` MySQL connection args | `spec.py` |
| Tidied title / nav order | `app.py` |
| Activated the plugin | `settings.yaml` |

Everything else — request/response validation, the `GET /schema` wire format, and
the list/detail/create/update/execute/delete routes — was derived from the model.

---

## Level up

Small, high-value extensions once the basics work:

**A mutual-exclusion rule.** `--databases` and `--all-databases` are
contradictory. Forbid one when the other is set with a field gate:

```python
from app.sep.plugins.framework.form_dsl import Forbidden
from app.sep.plugins.framework.rules import truthy

databases: Annotated[
    str,
    ArgFormat(),
    Forbidden(when=truthy("all_databases")),
    Ui(label="Databases", section="options", default=None),
] = ""
```

The framework enforces this both in the React form and server-side on the
request body.

**More options.**

- **A `--list-encrypted-tables` flag.** Add a `bool` field with `ArgFormat()`; the
  flag name is derived from the field name automatically.

- **Explicit credentials.** To connect as a specific user via a defaults file,
  add a `mysql_defaults_file: str` field and append
  `--defaults-file=<path>` to `connection_args` after `--` (this is how the
  `alters` plugin threads `~/.my.cnf`). See `app/sep/plugins/alters/spec.py`.

- **Choices instead of a free-typed option.** For a fixed set of values, use
  `Choices(((value, label), ...))` (or an `Enum` / `Literal` base type) to render
  a dropdown.

For the full marker reference, the escape-hatch ladder, and how to fan a single
form into a *group* of tasks (derived siblings and chained predecessors), read
[`CONTRIBUTING.md`](./CONTRIBUTING.md).

---

Reference: [`pt-mysql-summary` — Percona Toolkit Documentation](https://docs.percona.com/percona-toolkit/pt-mysql-summary.html)
