# App migration OpenAPI + schema snapshot harness

A mechanical safety net for the app-framework epic. It snapshots every active
app's public HTTP contract — its `/api/apps/{key}` OpenAPI subtree and its
`GET …/schema` JSON payload — and byte-compares each against a golden file
recorded from `main`. An app-migration PR is provably a **no-op** on the
contract when these snapshots stay green, or it is an explicit, reviewed,
additive change when a regenerated golden is part of the diff.

## What it covers

The harness is driven by two test modules plus a shared helper, all under
`tests/app/sep/`:

- `tests/app/sep/test_openapi_snapshot.py` — one golden per configured app
  key (`tests/app/sep/snapshots/openapi/<key>.json`).
- `tests/app/sep/test_schema_snapshot.py` — one golden per parameterless
  `GET …/schema` route under a configured app prefix
  (`tests/app/sep/snapshots/schema/<slug>.json`).
- `tests/app/sep/snapshot_utils.py` — pure helpers (canonical JSON, subtree
  slicing, `$ref` closure, route discovery, compare/update).

Both modules **discover** their targets from the app rather than hardcoding
app keys, so the harness self-maintains. The app inventory is derived from
`sep_settings.APPS` (the committed `settings.yaml` default config), not from
live-app path discovery.

The OpenAPI document is built from a **throwaway app over the config-built
`api_router`** (`snapshot_utils.build_plugins_openapi`), not from the
process-global `sep_app`. A sibling conftest (`backup_pg`) injects routers into
`sep_app` at import time, which both freezes `sep_app`'s cached schema for other
tests and perturbs shared `components/schemas` names — so a snapshot read from
`sep_app` would depend on test-suite composition. `api_router` is built once
from `sep_settings.APPS` and is never mutated, so its schema is
deterministic; the snapshot uses the same `operationId` scheme `create_app`
installs on `sep_app`. The schema snapshots (AC2) still issue real
`GET …/schema` requests through the authenticated `test_client` over `sep_app`,
so the recorded payloads reflect the live serialization stack. Content is
sliced strictly within configured `/api/apps/{key}` prefixes.

Each module also carries a completeness guard
(`test_*_golden_set_is_complete`) that fails when the committed golden set drifts
from the discovered set — so an added or removed app/endpoint surfaces as a
missing/orphaned-golden failure rather than silent under-coverage.

### Scope notes

- **Default-config set.** Goldens cover the apps enabled by the default test
  config. `backup_pg` is **not** covered: it appears only in the
  `env/settings-*team*.yaml` deployment profiles, so it is absent from
  `sep_settings.APPS`. When it (or any app) is later added to the default
  config, the completeness guard fails until a reviewed regeneration adds its
  goldens.
- **Recorded for the default test environment (`development`).** The app set
  comes from `sep_settings.APPS`, which the YAML loader resolves against the
  active `FASTAPI_ENV` overlay. The whole `test_client`-based suite boots with
  `FASTAPI_ENV` unset → `development`, and the goldens are recorded for that
  profile. Running the snapshot tests under a different `FASTAPI_ENV` changes the
  active app set (and the running `sep_app`), so it requires a regeneration
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

Regenerate **only** for a deliberate, reviewed, additive change to an app's
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
suite. Per-app behavioral tests already exist (e.g.
`tests/app/sep/apps/checksums/test_routes.py`) and must keep passing
**unmodified** through a migration — that is the no-op proof.

Instead, each migration runs a kickoff **coverage gap-check** on the app's
existing suite, confirming the standard contract paths are exercised:

- authentication / authorization,
- 404 / not-owned,
- 422 (validation),
- conflict paths.

Back-fill **only genuine gaps** surfaced by that check. Do not re-characterize
behavior the existing suite already covers — that adds churn without adding
proof, and it is explicitly out of scope for a migration.

## Conformance suite (framework invariants)

Where the snapshot harness pins each app's *byte-for-byte* contract, the
conformance suite enforces the app-framework's *structural* invariants
mechanically, so they are caught in `make test`/CI instead of by reviewer memory.

- `app/sep/apps/framework/conformance.py` — pure detector functions, each
  taking one registry input plane and returning a list of violation strings
  (empty when the invariant holds).
- `tests/app/sep/apps/framework/test_conformance.py` — per-detector unit
  tests, a synthetic `TaskExecutionApp` exercising the migrated-only detectors
  before any app is migrated, and a suite that iterates `get_app_registry()`.

The checks:

- **No duplicate capability control** (hard-fail, every schema-bearing app). A
  capability the React `SchemaFormRenderer` already renders (today only
  `alert_on_fail`, via `CAPABILITY_RENDERED_CONTROLS`) must not also appear as an
  explicit form field — that is a duplicate control. Operates on the `GET …/schema`
  wire payload, traversing both `forms[]` and `entities[].forms[]`.
- **Migrated-only structural checks** (gated on `isinstance(app, TaskExecutionApp)`;
  dormant until the first migration): capability/route consistency, list/detail
  view fields resolve to real `response_model` fields, and create-model schema
  derivation succeeds.
- **Registry-level checks**: no two routes collide on `(path, method)`, the merged
  app OpenAPI builds, and every operation carries a summary-or-description floor.
- **Transitional drift** (warning-level): reuses
  `form_dsl.check_form_conformance`, re-exported here so the suite imports every
  check from one module. Dormant today (no registry app exposes both a create
  model and a hand-written schema).

### The duplicate `alert_on_fail` removal

The suite's trigger was a systemic duplicate: five apps (`alters`, `archives`,
`backup_mongo`, `backup_pg`, `mysql_backups`) each declared both an explicit
`alert_on_fail` `BoolField` **and** `capabilities.alert_on_fail=True`, while the
renderer already draws the capability-driven control under the same wire key. The
explicit field was removed from each schema (`archives` also drops its now-empty
"Alert & Connectivity" section). This changes only the `GET …/schema` instance
payload — the **rendered form is unchanged** (the control still renders from the
capability), and the submitted payload, the response models, the `alert_on_fail`
task field, and the OpenAPI request bodies are all retained. The schema goldens
were regenerated in the same change; the OpenAPI goldens stay green without
regeneration. `backup_pg` is not in the default config (see the scope note above),
so its removal is validated by `tests/app/sep/apps/backup_pg/test_models.py`,
not the registry suite.
