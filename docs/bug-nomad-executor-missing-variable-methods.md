# Bug: NomadExecutor missing `create_nomad_variable` / `delete_nomad_variable` — MUM create/update user always 500

## Summary

Creating or updating a MongoDB user via the MUM plugin fails with
`An unexpected error occurred on the server.` (HTTP 500).  
The root cause is that `NomadExecutor` does not implement the two methods that
`POST /nomad/variables/` calls, so every request dies with an `AttributeError`.

## Steps to reproduce

1. Open the MUM plugin UI.
2. Fill in target, username, password, roles and click **Create user** (or
   **Update user** with a new password).
3. Observe the "An unexpected error occurred" toast.

## Root cause

`app/tasks/routes.py` exposes `POST /nomad/variables/` and `DELETE /nomad/variables/{path}`.  
Both handlers delegate to the executor:

```python
# tasks/routes.py:721
await executor.create_nomad_variable(path=path, data=payload.data, namespace=payload.namespace)

# tasks/routes.py:747
await executor.delete_nomad_variable(path=path, namespace=namespace)
```

`NomadExecutor` (`app/tasks/execution/executors/nomad/models.py`) never
implemented these methods, so any call raises:

```
AttributeError: 'NomadExecutor' object has no attribute 'create_nomad_variable'
```

This bubbles up as a 500 inside `tasks_api`, which `sep_app` then surfaces as
`An unexpected error occurred on the server.`

## Why Nomad variables are used here

When the MUM plugin creates or updates a user it must pass a MongoDB password
to the Nomad job.  Putting the password directly in task meta would store it
in plaintext in the task-history database and expose it in logs.

The `run-python` Nomad job template already supports two config paths:

```hcl
# seed.py – EmbeddedTmpl for the config file
{{- $var := env "NOMAD_META_config_nomad_variable" -}}
{{- if $var -}}{{ with nomadVar $var }}{{ .config }}{{ end }}
{{- else -}}{{ env "NOMAD_META_config" }}{{- end -}}
```

When `config_nomad_variable` is set in task meta the template fetches the
Nomad variable (encrypted at rest), writes the JSON to a config file, and
deletes it after the task completes.  This keeps passwords out of logs and
task history.

## Fix

Added `create_nomad_variable` and `delete_nomad_variable` to `NomadExecutor`
using the `variable` API already provided by the `python-nomad` library:

```python
async def create_nomad_variable(self, path, data, namespace=None):
    items = {k: v if isinstance(v, str) else json.dumps(v) for k, v in data.items()}
    body = {"Path": path, "Items": items}
    if namespace:
        body["Namespace"] = namespace
    try:
        await async_run(self.backend.variable.create_variable, path, body, namespace=namespace)
    except BaseNomadException as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

async def delete_nomad_variable(self, path, namespace=None):
    try:
        await async_run(self.backend.variable.delete_variable, path, namespace=namespace)
    except BaseNomadException as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

Key details:
- Nomad variable `Items` are `map[string]string`; dict values are
  JSON-serialised automatically.
- `async_run` wraps the synchronous python-nomad call in a thread pool,
  matching the pattern used by `validate_job` and `parse_payload`.
- Nomad errors are re-raised as `HTTPException(502)` so the existing
  error-handling in `tasks/routes.py` works without changes.

## Files changed

- `app/tasks/execution/executors/nomad/models.py` — added the two methods
  after `get_hosts`.
