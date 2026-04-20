# CLAUDE.md — SEP Plugins

Plugin-specific guidance for code under `app/sep/plugins/`. Complements the
project-wide `CLAUDE.md` at the repo root.

## DB Models and Migrations

Plugins that own database tables must follow this layout:

```
app/sep/plugins/<name>/
├── models.py                 # SQLModel table classes (self-contained — see below)
├── migrations/
│   └── versions/
│       └── YYYY_MM_DD_HHMM-<rev>_<slug>.py
```

### Conventions

1. **Table classes live in `<plugin>/models.py`.** Inherit from
   `BaseSQLModel` (int ID) or `BaseUUIDSQLModel` (UUID4 ID). Never
   inherit directly from `SQLModel`.
2. **`models.py` must be self-contained.** Import only from
   `app.core.*`, `app.sep.models`, `app.sep.config`, `sqlalchemy`,
   `sqlmodel`, and other non-plugin-local paths. Do NOT import from
   sibling plugin modules (`crud.py`, `deps.py`, `routes.py`,
   `constants.py`) — the migration-time discovery helper loads
   `models.py` via `importlib.util.spec_from_file_location` to bypass
   the plugin's `__init__.py` (which would otherwise trigger the full
   request-handler graph, including inter-plugin circular imports).
3. **The first revision uses `branch_labels=('<plugin>',)` and
   `down_revision=None`.** Plugin chains are independent roots in the
   SEP Alembic script; they do not extend `sep_main`.
4. **Register the plugin's `versions/` directory in `alembic.ini`.**
   Add it to the `version_locations` line under `[sep]`, joined by
   `:` (on Linux; see `version_path_separator` in the same file).
   Alembic resolves `version_locations` before `env.py` runs, so the
   dir must be listed statically — discovery in `env.py` only loads
   `models.py` into metadata, it does not register paths.

### Generating migrations

**Main SEP chain** (anything under `app/sep/models.py` or
`app/sep/snippets/models/`):

```bash
make makemigrations
```

This now passes `--head=sep_main@head` for the sep app so autogenerate
places the new revision on the main chain.

**Existing plugin chain** (e.g. new alerts revisions):

```bash
make makemigrations-plugin PLUGIN=alerts
```

Wraps `alembic --name sep revision --autogenerate --head=alerts@head`.

**First revision of a new plugin chain** — manual, once per plugin:

```bash
alembic --name sep revision --autogenerate \
    --head=base \
    --branch-label=<plugin> \
    --version-path=$(pwd)/app/sep/plugins/<plugin>/migrations/versions \
    -m "<description>"
```

Then add the new `versions/` path to `alembic.ini`'s `version_locations`
line and commit both files.

### Autogenerate is single-branch-at-a-time

`target_metadata = SQLModel.metadata` covers ALL installed plugin
tables. The `--head=<branch>@head` flag controls where the generated
revision is PLACED — it does NOT restrict which table diffs appear in
the revision body. To keep migrations properly branch-owned:

1. Make schema changes on ONE branch at a time.
2. Run the appropriate `makemigrations*` target.
3. Commit the revision.
4. Move to the next branch.

If you autogenerate a revision that contains operations on tables
belonging to a different branch, hand-edit the file — remove those
operations and generate a separate revision for them under the correct
branch.

### Schema management follows installation, not config

Plugin discovery uses `pkgutil.iter_modules` over
`app.sep.plugins.__path__`. `settings.yaml`'s `SEP.PLUGINS` toggle
controls runtime behavior (which routes mount, which periodic tasks
run); it does NOT remove a plugin's migrations from Alembic's view. A
deployment that previously enabled a plugin and later disables it in
config retains the plugin's tables — they just sit unused. This is
deliberate: if discovery were config-driven, a config flip could leave
Alembic unable to resolve stamped revisions in the DB.

Never use runtime `SQLModel.metadata.create_all` for plugin tables —
always go through Alembic.

### Pip-uninstalling a plugin from a running deployment

Plugin uninstall is a deliberate two-step operator action. Run the
Alembic step BEFORE removing the Python package AND before removing
the `settings.yaml` entry — otherwise Alembic fails to resolve the
stamped head for a plugin whose script dir no longer exists.

**Clean uninstall (drops the plugin's tables):**

```bash
alembic --name sep downgrade <plugin>@base
pip uninstall <plugin-package>
```

Removes the plugin's revision rows from `alembic_version_sep` and
executes every `downgrade()` in the plugin's chain (which typically
drops its tables). Other plugins' branches are untouched.

**Preserve the plugin's data (keep the tables, clear revision state):**

```bash
# Step 1 — read currently-stamped heads from the DB, NOT from the script dir.
alembic --name sep current

# Step 2 — stamp with every surviving head EXCEPT the plugin being removed.
alembic --name sep stamp <hash_a> <hash_c> ...

# Step 3 — uninstall the package.
pip uninstall <plugin-package>
```

Read the survivor list from `alembic current` (DB state), not
`alembic heads` (script state). If the DB is behind any branch's
script head, `current` and `heads` differ — stamping from `heads`
would silently promote unapplied revisions to "applied." Never use
`stamp sep_main@head` alone when other plugins are installed; that
would also clear every other plugin's branch head.
