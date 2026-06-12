# Plugin migration OpenAPI + schema snapshot harness

A mechanical safety net for the app-framework epic. It snapshots every active
plugin's public HTTP contract — its `/api/plugins/{key}` OpenAPI subtree and its
`GET …/schema` JSON payload — and byte-compares each against a golden file
recorded from `main`. A plugin-migration PR is provably a **no-op** on the
contract when these snapshots stay green, or it is an explicit, reviewed,
additive change when a regenerated golden is part of the diff.

## What it covers

The harness is driven by two test modules plus a shared helper, all under
`tests/app/sep/`:

- `tests/app/sep/test_openapi_snapshot.py` — one golden per configured plugin
  key (`tests/app/sep/snapshots/openapi/<key>.json`).
- `tests/app/sep/test_schema_snapshot.py` — one golden per parameterless
  `GET …/schema` route under a configured plugin prefix
  (`tests/app/sep/snapshots/schema/<slug>.json`).
- `tests/app/sep/snapshot_utils.py` — pure helpers (canonical JSON, subtree
  slicing, `$ref` closure, route discovery, compare/update).

Both modules **discover** their targets from the app rather than hardcoding
plugin keys, so the harness self-maintains. The plugin inventory is derived from
`sep_settings.PLUGINS` (the committed `settings.yaml` default config), not from
live-app path discovery.

The OpenAPI document is built from a **throwaway app over the config-built
`api_router`** (`snapshot_utils.build_plugins_openapi`), not from the
process-global `sep_app`. A sibling conftest (`backup_pg`) injects routers into
`sep_app` at import time, which both freezes `sep_app`'s cached schema for other
tests and perturbs shared `components/schemas` names — so a snapshot read from
`sep_app` would depend on test-suite composition. `api_router` is built once
from `sep_settings.PLUGINS` and is never mutated, so its schema is
deterministic; the snapshot uses the same `operationId` scheme `create_app`
installs on `sep_app`. The schema snapshots (AC2) still issue real
`GET …/schema` requests through the authenticated `test_client` over `sep_app`,
so the recorded payloads reflect the live serialization stack. Content is
sliced strictly within configured `/api/plugins/{key}` prefixes.

Each module also carries a completeness guard
(`test_*_golden_set_is_complete`) that fails when the committed golden set drifts
from the discovered set — so an added or removed plugin/endpoint surfaces as a
missing/orphaned-golden failure rather than silent under-coverage.

### Scope notes

- **Default-config set.** Goldens cover the plugins enabled by the default test
  config. `backup_pg` is **not** covered: it appears only in the
  `env/settings-*team*.yaml` deployment profiles, so it is absent from
  `sep_settings.PLUGINS`. When it (or any plugin) is later added to the default
  config, the completeness guard fails until a reviewed regeneration adds its
  goldens.
- **Recorded for the default test environment (`development`).** The plugin set
  comes from `sep_settings.PLUGINS`, which the YAML loader resolves against the
  active `FASTAPI_ENV` overlay. The whole `test_client`-based suite boots with
  `FASTAPI_ENV` unset → `development`, and the goldens are recorded for that
  profile. Running the snapshot tests under a different `FASTAPI_ENV` changes the
  active plugin set (and the running `sep_app`), so it requires a regeneration
  under that profile — the harness pins the suite's environment, not a hardcoded
  list.
- **The parameterized `snippets/snippet/schema` route is excluded** from the
  schema snapshots: it requires a `snippet_filename` query param resolving a real
  DB snippet, so a bare `GET` returns 422/404 and its output is data-dependent —
  not a stable static golden. Its contract *shape* is still captured inside the
  snippets OpenAPI subtree golden.
- **Nested sub-routers** (e.g. `backup_mongo/restores`) get their own schema
  golden (`backup_mongo__restores.json`) and are folded into the parent's OpenAPI
  subtree by prefix match.

## How to run

The snapshot tests are ordinary tests collected by the standard suite. To run
just the harness:

```bash
pytest tests/app/sep/test_openapi_snapshot.py tests/app/sep/test_schema_snapshot.py
```

On any drift the failing case reports the golden it diverged from and the
regeneration command. A `GET …/schema` route that stops returning `200` fails on
an explicit status assertion *before* the byte-compare, so an auth/enable
regression reads as a clear status failure rather than a confusing diff.

## Regenerating the goldens

When a change to the OpenAPI surface or a schema payload is **intentional**,
regenerate the affected goldens with the update switch:

```bash
SEP_UPDATE_SNAPSHOTS=1 pytest tests/app/sep/test_openapi_snapshot.py tests/app/sep/test_schema_snapshot.py
```

In update mode each snapshot case rewrites its golden and reports `skipped`; the
completeness guards still run. `SEP_UPDATE_SNAPSHOTS` is truthy for any value
other than unset, `""`, `0`, `false`, or `False`.

### When regeneration is legitimate

Regenerate **only** for a deliberate, reviewed, additive change to a plugin's
public contract — a new route, a new schema field, a new enum value that the
ticket intends to ship. Never regenerate to silence an unexplained diff: an
unexpected drift is the harness doing its job, and the diff must be understood
before it is accepted.

### Required diff-review step

A regenerated golden is reviewed exactly like source. The golden diff must appear
in the PR and a reviewer must confirm that every changed byte is an expected
consequence of the change. Treat an un-reviewed golden regeneration as an
un-reviewed contract change.

## Migration coverage policy

Migration tickets must **not** build a duplicate behavioral characterization
suite. Per-plugin behavioral tests already exist (e.g.
`tests/app/sep/plugins/checksums/test_api_routes.py`) and must keep passing
**unmodified** through a migration — that is the no-op proof.

Instead, each migration runs a kickoff **coverage gap-check** on the plugin's
existing suite, confirming the standard contract paths are exercised:

- authentication / authorization,
- 404 / not-owned,
- 422 (validation),
- conflict paths.

Back-fill **only genuine gaps** surfaced by that check. Do not re-characterize
behavior the existing suite already covers — that adds churn without adding
proof, and it is explicitly out of scope for a migration.
