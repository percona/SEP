# Plugin skeleton

A ready-to-copy starting point for a new **simple, model-first** SEP plugin — one
form that produces a `run-command` task against a MySQL service. See
[`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the reference and
[`../GETTING_STARTED.md`](../GETTING_STARTED.md) for a full worked example
(`pt-mysql-summary`) built from this skeleton.

The files here use the `.py.tpl` extension on purpose: this folder is **not** a
live plugin, so nothing imports it, it can't be accidentally activated, and it
won't break tests. You turn it into a real plugin by copying it out and dropping
the `.tpl` suffix.

## What's inside

| File | Becomes | Role |
|---|---|---|
| `__init__.py.tpl` | `__init__.py` | Re-exports `app`. |
| `models.py.tpl` | `models.py` | The form: fields + markers (single source of truth). |
| `views.py.tpl` | `views.py` | Section titles, list columns, detail layout, capability flags. |
| `spec.py.tpl` | `spec.py` | Pure `(form, resolved) -> RunCommandSpec` builder. |
| `app.py.tpl` | `app.py` | The `TaskExecutionApp` that derives every route. |

## How to use it

1. **Copy and rename the folder** to your plugin name (snake_case), and drop the
   `.tpl` suffixes:

   ```bash
   cp -r app/sep/plugins/_skeleton app/sep/plugins/myplugin
   cd app/sep/plugins/myplugin
   rm README.md
   for f in *.py.tpl; do mv "$f" "${f%.tpl}"; done
   ```

2. **Replace the placeholder tokens** throughout the copied files:

   | Token | Replace with | Example |
   |---|---|---|
   | `example` | your module name (snake_case) | `myplugin` |
   | `Example` | your class prefix (PascalCase) | `MyPlugin` |
   | `EXAMPLE` | your `TaskOwner` member | `MYPLUGIN` |
   | `example-tool` | the CLI command to run (in `spec.py`) | `my-tool` |
   | `/example` | the plugin URI path (in `app.py`) | `/myplugin` |

   A quick sed pass (macOS `sed -i ''`; GNU `sed -i`):

   ```bash
   sed -i '' -e 's/example-tool/my-tool/g' \
             -e 's/\/example/\/myplugin/g' \
             -e 's/example/myplugin/g' \
             -e 's/Example/MyPlugin/g' \
             -e 's/EXAMPLE/MYPLUGIN/g' *.py
   ```

3. **Add your `TaskOwner`** in `app/tasks/models.py` (e.g. `MYPLUGIN =
   "MYPLUGIN"`).

4. **Activate it** in `settings.yaml` under `SEP.PLUGINS`:

   ```yaml
       - NAME: My Plugin
         MODULE_NAME: myplugin
   ```

5. **Fill in the specifics**: your fields in `models.py`, your command and
   argument assembly in `spec.py`, and your columns/labels in `views.py`.

`TaskExecutionApp` validates the whole definition at construction, so a mistake
(unknown section key, bad list column, malformed `ArgFormat`) fails fast with a
descriptive error the moment the module is imported.
