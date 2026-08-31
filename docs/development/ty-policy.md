# ty Type-Checking Policy

This document records two decisions about [`ty`](https://github.com/astral-sh/ty),
the static type checker `make typecheck` runs: **which trees are checked**, and
**what severity each diagnostic rule carries**. Both are expressed in
`pyproject.toml` — `[tool.ty.src]` and `[tool.ty.rules]` — and this file is the
rationale behind them.

Type checking is opt-in and local-only. It is deliberately not part of `lint`,
pre-commit, or CI, and `make typecheck` exits non-zero today because of an
existing backlog of diagnostics. That is the expected state, not a regression.

All measurements below were taken with **ty 0.0.49**, the version pinned in the
`typecheck` Poetry group, on branch commit `3eede0dd3` — `dafd2df1` plus the
configuration this policy commits. The counts depend on `[tool.ty.rules]`, so
they do not reproduce at `dafd2df1` alone.

Every number below — the recorded baseline, the two rule tables, and the
sampling record — is a snapshot of that one tree at that one version, and is
**not maintained** against later commits. No decision in this document turns on
any of those values: severity was chosen from what a rule's diagnostics *say*,
so a count that has since moved dates the evidence without reopening the call.
Read the counts as how each call was reached, not as a figure anything checks.

## The checked surface

`[tool.ty.src].include` names the four first-party trees that are checked:

| Tree | Modules | Decision | Reason |
|---|---|---|---|
| `app/` | 516 | in scope | The shipped application. |
| `tests/` | 494 | in scope | A wrong annotation is cheapest to ship in a test and least likely to be caught in review there. |
| `scripts/` | 15 | in scope | First-party release and CI tooling. |
| `sidecar/` | 5 | in scope | First-party PMM side-car code. |
| `**/migrations/**` | — | out of scope | Alembic-generated. |
| `frontend/**` | — | out of scope | Not Python. |

`include` is what makes the surface a decision rather than an accident. Without
it, a bare `ty check` also walks whatever untracked or personal directories
happen to sit in the working tree. **A new first-party tree is not checked until
it is added here**, deliberately.

## `[tool.ty.src]` is authoritative, and `make typecheck` passes no paths

`make typecheck` runs a bare `ty check` with no path arguments, so the surface
comes from `[tool.ty.src]` alone.

The reason is that this leaves exactly **one** definition of the surface. A path
argument in the Makefile and an `include` list in `pyproject.toml` are two places
that can drift apart, and the requirement this policy has to meet is that a bare
`ty check` and `make typecheck` read the same trees. With no argument list they
carry identical inputs by construction, so they cannot disagree — and a developer
running `ty` directly in an editor or shell gets the same surface the Makefile
does, without having to know what the recipe passes.

The trees are additive only when each is checked on its own. Measured one root
at a time, they sum to exactly what a bare `ty check` reports:

```
ty check app         ->   961
ty check tests       ->  2957
ty check scripts     ->     5
ty check sidecar     ->     3
                        ------
             summed      3926   == ty check (bare)

ty check app tests   ->  3916   != 961 + 2957
```

Passed together as an argument list they do not. `ty check app tests` reports
3916, two short of `app` plus `tests`, and the two it drops are real
`invalid-argument-type` diagnostics in `app/tasks/logs/log_reader.py` (lines 424
and 433) that `ty check app` on its own reports. Longer root lists diverge
further, in the same direction — see the caveat below.

So an argument list does not merely restate what `[tool.ty.src]` already says.
It silently loses genuine diagnostics, which makes it wrong rather than
redundant, and only the bare invocation accounts for all 3926.

### A caveat on measuring this

Run-to-run instability was observed while preparing this policy: in one
developer working tree, `ty check` given several directory roots reported about
208 fewer diagnostics on roughly a fifth of runs, with the missing diagnostics
concentrated in `tests/app/tasks/logs/`.

That behaviour **did not reproduce** in a `git archive` export of the same
commit — 24 consecutive runs there returned an identical count — so it is
recorded here as an environment-dependent observation, not as a property of ty
and not as part of the argument for this design. The cause was not identified;
neither the `env/` nor the `.claude/` symlink reproduced it when added to the
export.

Two things are worth taking from it. First, if you are comparing diagnostic
counts between invocations, run each more than once before trusting a
difference. Second, a bare `ty check` was stable in every environment tested
(the 3926 baseline below reproduced on every run in both the working tree and
the frozen export), which is a further reason to prefer it as the form this
project measures against.

## The recorded baseline

Under the committed configuration, at `3eede0dd3` (`dafd2df1` plus this policy):

```
make typecheck  ->  Found 3926 diagnostics   (358 error, 3568 warning), exit 2
ty check        ->  Found 3926 diagnostics, exit 1
```

The two agree because they now carry identical argument lists — none.

That figure predates the artifact suppressions. Under the configuration as it
now stands the same command reports **3,626**; the before/after split and what
moved between them are in *Neutralized dependency-typing artifacts* below.

The two exit codes differ because `make` reports its own status: `ty` exits 1
when it finds diagnostics, and `make` turns any failed recipe into exit 2.

They are **not** guaranteed to be the same binary, and the parity claim carries a
precondition worth restating whenever it is re-checked: `make typecheck` runs
`"${VENV_BIN}"/ty`, and the Makefile resolves `VENV_BIN` three ways, in
precedence order — from `$(POETRY) env info --path` when `POETRY` is set, from
`VIRTUAL_ENV` when it is not, and otherwise from the repository-local
`venv/bin`. That last case is the default for a developer who sets neither
variable. A bare `ty check`, by contrast, runs whatever `ty` is first on
`PATH`. The
`ty = "0.0.49"` pin governs only the former. Before treating agreeing counts as
evidence, confirm `command -v ty` resolves to the same `${VENV_BIN}/ty` and that
`ty --version` reports the pinned version — otherwise the two numbers describe
two different programs.

## Severity policy

### The stance for unlisted rules

`[tool.ty.rules]` opens with `all = "error"`. **A rule that is not listed is an
error.** A rule that starts firing after a code change, or that arrives with a ty
upgrade, therefore shows up loud and forces an explicit decision instead of
inheriting a default nobody chose.

`all = "error"` also switches on the rules ty ships disabled by default, so the
table lists those too — see [Rules ty disables by
default](#rules-ty-disables-by-default).

### How each severity was chosen

Severity was decided by what a rule's diagnostics *say*, read from the files they
land in — never by how many there are. Volume is evidence about cleanup cost, not
about whether a rule is worth keeping.

- **`error`** — the diagnostics are predominantly first-party annotation defects
  with a fix available in this repository, and fixing them improves correctness.
- **`warn`** — the diagnostics mix genuine defects with artifacts of how a
  dependency is typed (SQLModel, pydantic, FastAPI), so neither `error` nor
  `ignore` is honest while those stubs are unshimmed. A `warn` still prints, as
  `warning[...]`, and still exits 0 on its own; it does not reduce output volume.
  It marks a rule as *not yet enforceable*, not as *unimportant*.
- **`ignore`** — reserved for rules with no first-party action available, and for
  conventions this project has not adopted. Every `ignore` names its reason.
  `ignore` is strictly lossier than `warn`, so close calls go to `warn`.

Rules whose severity equals the `all` baseline are still listed explicitly, so
the table is a complete record of what has been deliberately softened.

### Rules at `warn`

Each mixes real defects with dependency-typing artifacts. Sample sizes and file
lists for the ones above 50 hits are in the next section.

| Rule | Hits | Why not `error` |
|---|---:|---|
| `invalid-argument-type` | 2116 | 198 hits are the SQLModel-vs-SQLAlchemy `AsyncSession` split, which has no first-party fix; 325 are genuine `int` vs `int \| None`. |
| `unresolved-attribute` | 863 | 382 are genuine Optional narrowing; the other 481 are test doubles patching private attributes, `object`-typed fixtures, and SQLAlchemy stub gaps. |
| `unknown-argument` | 200 | Dominated by pydantic-settings' `_env_file` / `_secrets_dir`, valid at runtime but absent from the generated `__init__`. |
| `invalid-assignment` | 187 | 83 of 187 are the pydantic `Field(...)` idiom, where ty sees `FieldInfo` assigned to the declared field type. |
| `missing-argument` | 113 | `Settings()` populates its required fields from the environment, which ty cannot see. |
| `call-non-callable` | 38 | Subscripted generics and `object`-typed fixtures, mixed with real calls through `None`. |
| `no-matching-overload` | 34 | Third-party overload sets: `AsyncSession.exec`, `select`, `create_model`. |
| `unresolved-import` | 11 | 8 of 11 are the framework golden-app templates, whose `app.sep.apps.golden_*` modules are scaffolded at test time and do not exist statically. |
| `invalid-parameter-default` | 6 | 4 of 6 are the FastAPI `Query(...)` default idiom. |

### Rules at `error`

Predominantly first-party defects with a fix available here.

| Rule | Hits | What the diagnostics say |
|---|---:|---|
| `invalid-return-type` | 168 | Nullable returns, and generator fixtures annotated as the yielded type rather than as a generator. |
| `not-subscriptable` | 59 | 57 of 59 subscript a value ty knows may be `None`. |
| `invalid-type-form` | 39 | SEP's own dynamic `type[BaseUser]` / `type[BaseModel]` values used as annotations. |
| `unsupported-operator` | 22 | 16 of 22 have an un-narrowed `X \| None` operand; the rest widen an operand to `object`. |
| `invalid-method-override` | 19 | First-party overrides of first-party bases; these are Liskov violations. |
| `not-iterable` | 12 | Includes `async for` over a coroutine that was never awaited. |
| `possibly-unresolved-reference` | 11 | A name read on a path where it may never have been bound. |
| `call-top-callable` | 5 | `callable()` narrowing drops the signature; fixable by annotating the attribute. |
| `unbound-type-variable` | 4 | Type variables left unbound in the `app/core` generics. |
| `invalid-paramspec` | 4 | `*args: P.args` without the matching `**kwargs: P.kwargs`. |
| `invalid-context-manager` | 2 | An `__aexit__` signature that prevents `async with`. |
| `empty-body` | 2 | Implicit `None` return against a non-`None` annotation. |
| `possibly-missing-attribute` | 2 | Attribute read through a partially-narrowed union. |
| `redundant-cast` | 1 | A `cast` the inferred type already satisfies. |
| `possibly-missing-submodule` | 1 | Submodule referenced without being imported. |
| `mismatched-type-name` | 1 | `StrEnum` name does not match the variable it is assigned to. |
| `invalid-yield` | 1 | The yielded value is optional, the annotation is not. |
| `invalid-key` | 1 | Unknown key on a TypedDict. |
| `invalid-base` | 1 | Class base is not a valid type. |
| `invalid-attribute-access` | 1 | Assignment to a `ClassVar` through an instance. |
| `unsupported-dynamic-base` | 1 | Class base computed at runtime, so the hierarchy is unknown. |
| `deprecated` | 1 | Calls a symbol its own library marks deprecated. |

## Sampling record for the high-volume rules

Rules at 50 hits or fewer were read in full — 24 rules, 220 diagnostics. The
nine rules above 50 hits were sampled by first collapsing each diagnostic to its
message shape (backtick-quoted spans replaced), then reading a sample spread
across distinct files and across `app/` and `tests/`. The last two rows are the
default-off rules set to `ignore`; they are sampled on the same terms, because a
suppression needs the same evidence as a severity.

Those two counts partition the table: 24 read in full plus 9 sampled is the 33
entries `[tool.ty.rules]` carries. The 24 include the three default-off rules
kept at `error` (11 + 2 + 1 diagnostics), which are below the 50-hit threshold
like the rest.

| Rule | Hits | Shapes | Files | Sampled | Sampled from |
|---|---:|---:|---:|---:|---|
| `invalid-argument-type` | 2116 | 9 | 251 | 24 | `app/core/config.py`, `app/core/utils/fields.py`, `app/sep/apps/dipper/payloads/pcs-collect-pmm-mysql.py`, `tests/app/tasks/logs/test_log_writer.py`, `tests/app/tasks/logs/test_log_eviction.py`, `tests/app/tasks/logs/test_log_reader.py`, `tests/app/tasks/test_crud.py`, `tests/app/tasks/test_celery.py`, `tests/app/tasks/execution/executors/nomad/test_models.py`, `tests/app/sep/snippets/models/test_meta.py`, `tests/app/sep/snippets/test_masking.py`, `tests/app/sep/apps/mysql_backups/test_payload_snapshot.py`, `tests/app/sep/apps/mysql_backups/variant_specs.py`, `tests/app/sep/apps/framework/kit.py`, `tests/app/sep/apps/framework/test_script_source.py`, `tests/app/sep/apps/framework/test_conformance.py`, `tests/app/sep/apps/framework/test_api.py`, `tests/app/sep/apps/backup_mongo/test_models.py`, `tests/app/sep/apps/alters/test_spec.py`, `tests/app/sep/apps/report/test_service.py`, `tests/app/sep/api/routes/test_settings.py`, `tests/app/sep/api/routes/test_app_state.py`, `tests/app/sep/test_config.py`, `tests/app/sep/test_app_drain.py` |
| `unresolved-attribute` | 863 | 10 | 170 | 24 | `app/core/db/crud.py`, `app/sep/apps/alters/spec.py`, `app/sep/clients/pmm.py`, `app/tasks/celery.py`, `app/tasks/crud.py`, `app/tasks/execution/executors/nomad/models.py`, `tests/app/api/test_deps.py`, `tests/app/core/db/test_utils.py`, `tests/app/core/test_config.py`, `tests/app/sep/api/test_router.py`, `tests/app/sep/api/routes/test_settings.py`, `tests/app/sep/apps/framework/test_registry.py`, `tests/app/sep/apps/mysql_backups/test_xtrabackup_aes256_flags.py`, `tests/app/sep/apps/mysql_backups/test_xtrabackup_aes256_encrypt.py`, `tests/app/sep/apps/mysql_backups/test_xtrabackup_incremental_cycle.py`, `tests/app/sep/db/test_seed.py`, `tests/app/sep/snippets/test_schema.py`, `tests/app/sep/snippets/models/test_meta.py`, `tests/app/sep/sync/test_models.py`, `tests/app/sep/test_override_callbacks.py`, `tests/app/sep/test_periodic_tasks.py`, `tests/app/sep/test_settings_override_integration.py`, `tests/app/tasks/logs/test_log_writer.py`, `tests/app/tasks/settings/test_routes.py` |
| `unknown-argument` | 200 | 2 | 25 | 22 | `app/core/config.py`, `app/sep/apps/framework/form_dsl/derivation.py`, `app/sep/apps/framework/responses.py`, `tests/app/api/routes/test_oauth.py`, `tests/app/core/alerts/providers/test_pagerduty.py`, `tests/app/core/alerts/test_models.py`, `tests/app/core/auth/test_config.py`, `tests/app/core/celery/test_config.py`, `tests/app/core/test_config.py`, `tests/app/core/test_models.py`, `tests/app/core/test_requests.py`, `tests/app/sep/apps/alerts/test_api_routes.py`, `tests/app/sep/apps/backup_pg/test_models.py`, `tests/app/sep/apps/framework/test_rules.py`, `tests/app/sep/apps/framework/test_schema.py`, `tests/app/sep/apps/report/test_config.py`, `tests/app/sep/snippets/models/test_meta.py`, `tests/app/sep/snippets/test_schema.py`, `tests/app/sep/sync/syncers/test_pmm.py`, `tests/app/sep/test_config.py`, `tests/sidecar/test_embedded_settings.py`, `tests/sidecar/test_settings_env.py` |
| `invalid-assignment` | 187 | 5 | 71 | 22 | `app/core/alerts/config.py`, `app/core/config.py`, `app/core/utils/openapi.py`, `app/sep/api/routes/dashboard.py`, `app/sep/apps/alerts/config.py`, `app/sep/apps/backup_mongo/restore/models.py`, `app/sep/apps/checksums/models.py`, `app/sep/apps/framework/registry.py`, `app/sep/clients/pmm.py`, `app/sep/config.py`, `app/sep/snippets/config.py`, `app/sep/sync/syncers/mysql/syncer.py`, `app/tasks/config.py`, `app/tasks/models.py`, `app/tasks/execution/executors/nomad/models.py`, `tests/app/core/settings_override/test_registry.py`, `tests/app/core/settings_override/test_registry_nested.py`, `tests/app/core/settings_override/api/test_registry_helpers.py`, `tests/app/sep/apps/topology/test_topology_payload.py`, `tests/app/tasks/logs/test_log_reader.py`, `tests/app/tasks/test_routes.py`, `tests/app/tasks/execution/executors/nomad/test_models.py` |
| `invalid-return-type` | 168 | 1 | 87 | 22 | `app/core/auth/providers/casdoor/sdk.py`, `app/core/auth/providers/grafana/sdk.py`, `app/core/db/crud.py`, `app/core/db/utils.py`, `app/core/requests/registry.py`, `app/core/utils/fields.py`, `app/sep/api/routes/periodic_tasks.py`, `app/sep/apps/alters/pre_checks.py`, `app/sep/apps/dipper/payloads/pcs-collect-pmm-mysql.py`, `app/sep/apps/dipper/payloads/pcs-collect-pmm-valkey.py`, `app/sep/apps/topology/api_routes.py`, `app/sep/clients/pmm.py`, `app/sep/crud.py`, `app/sep/deps.py`, `app/sep/sync/models.py`, `app/tasks/crud.py`, `tests/app/conftest.py`, `tests/app/core/db/test_list_query.py`, `tests/app/sep/api/routes/test_connectivity_check.py`, `tests/app/sep/apps/snippets/conftest.py`, `tests/app/sep/test_settings_override_worker.py`, `tests/app/tasks/periodic/conftest.py` |
| `missing-argument` | 113 | 3 | 23 | 22 | `app/core/config.py`, `app/sep/apps/framework/registry.py`, `tests/app/api/routes/test_oauth.py`, `tests/app/core/auth/test_models.py`, `tests/app/core/celery/test_config.py`, `tests/app/core/settings_override/test_policy.py`, `tests/app/core/test_config.py`, `tests/app/core/test_models.py`, `tests/app/sep/apps/alters/test_schema.py`, `tests/app/sep/apps/backup_pg/test_models.py`, `tests/app/sep/apps/framework/test_api.py`, `tests/app/sep/apps/framework/test_base.py`, `tests/app/sep/apps/framework/test_registry.py`, `tests/app/sep/apps/framework/test_schema.py`, `tests/app/sep/apps/inventory/test_models.py`, `tests/app/sep/bundle_upload/test_plan.py`, `tests/app/sep/routes/test_artifacts.py`, `tests/app/sep/sync/syncers/mysql/test_syncer.py`, `tests/app/sep/sync/syncers/system_facts/test_syncer.py`, `tests/app/sep/sync/syncers/test_pmm.py`, `tests/sidecar/test_embedded_settings.py`, `tests/sidecar/test_settings_env.py` |
| `not-subscriptable` | 59 | 1 | 23 | 22 | `app/core/auth/providers/casdoor/sdk.py`, `app/sep/apps/backup_mongo/deps.py`, `app/sep/apps/backup_mongo/restore/deps.py`, `app/sep/apps/backup_pg/deps.py`, `app/sep/apps/framework/responses.py`, `app/sep/apps/framework/task_status.py`, `app/sep/apps/tasks/api_routes.py`, `app/sep/clients/pmm.py`, `app/sep/deps.py`, `app/sep/routes/stream_logs.py`, `app/sep/sync/models.py`, `app/tasks/execution/executors/nomad/models.py`, `tests/app/core/auth/test_config.py`, `tests/app/core/test_log.py`, `tests/app/sep/apps/archives/test_api.py`, `tests/app/sep/apps/backup_pg/test_contract.py`, `tests/app/sep/apps/checksums/test_route_args.py`, `tests/app/sep/apps/framework/contract_suite.py`, `tests/app/sep/apps/framework/kit.py`, `tests/app/sep/snippets/test_schema.py`, `tests/app/tasks/test_deps.py`, `tests/app/tasks/execution/executors/nomad/test_models.py` |
| `missing-type-argument` | 559 | 3 | 121 | 20 | `app/core/db/crud.py`, `app/core/db/utils.py`, `app/core/settings_override/api/routes.py`, `app/core/settings_override/lifecycle.py`, `app/sep/apps/framework/apps.py`, `tests/app/core/settings_override/test_lifecycle.py`, `tests/app/core/settings_override/test_worker.py`, `tests/app/sep/apps/alters/test_api_routes.py`, `tests/app/sep/apps/backup_mongo/test_api_routes.py`, `tests/app/sep/apps/backup_mongo/restore/test_api_routes.py`, `tests/app/sep/apps/framework/test_api.py`, `tests/app/sep/apps/framework/test_apps.py`, `tests/app/sep/apps/framework/test_script_source.py`, `tests/app/sep/apps/shared/test_disk_script_source.py`, `tests/app/sep/clients/test_pmm.py`, `tests/app/sep/test_settings_override_integration.py`, `tests/app/sep/test_settings_override_worker.py`, `tests/app/tasks/test_celery_settings_override.py`, `tests/app/tasks/test_settings_override_integration.py`, `tests/app/tasks/execution/executors/nomad/test_models.py` |
| `missing-override-decorator` | 241 | 1 | 54 | 20 | `app/core/alerts/providers/pagerduty.py`, `app/core/auth/providers/casdoor/models.py`, `app/core/auth/providers/grafana/models.py`, `app/core/config.py`, `app/core/db/crud.py`, `app/core/db/sql_types.py`, `app/core/utils/lazy.py`, `app/sep/config.py`, `app/sep/inventory.py`, `app/sep/apps/framework/rules.py`, `app/sep/sync/syncers/pmm.py`, `app/sep/sync/syncers/mysql/syncer.py`, `app/sep/sync/syncers/system_facts/syncer.py`, `app/tasks/execution/executors/celery/models.py`, `app/tasks/execution/executors/nomad/models.py`, `tests/app/core/alerts/test_models.py`, `tests/app/sep/apps/mysql_backups/test_contract.py`, `tests/app/sep/apps/mysql_backups/restore/test_contract.py`, `tests/app/sep/sync/test_models.py`, `tests/app/tasks/execution/test_models.py` |

## `unresolved-attribute` stays reportable

`unresolved-attribute` is deliberately **not** set to `ignore`. It is the rule
that caught the only confirmed real defect found so far — four hard errors on a
single pull request — and 382 of its 863 hits are genuine Optional narrowing of
the `X | None` shape, which is exactly the class of latent `AttributeError` worth
keeping visible.

Its remaining hits are test doubles patching private attributes and gaps in
third-party stubs. Those are addressed by neutralizing the stub noise, not by
silencing the rule. If it ever turns out that no such mechanism can work, that is
a finding to raise against the parent epic — not a reason to ignore the rule
here.

## Neutralized dependency-typing artifacts

The section above promises that the stub noise mixed into the `warn` rules is
addressed by neutralizing it rather than by silencing the rule. This is that
work. **No severity changed here** — `[tool.ty.rules]` is untouched; what changed
is that 446 diagnostics which describe how a *dependency* is typed no longer
report, leaving a first-party remainder that can be sized and fixed.

Measured at `8ab18007e` with ty 0.0.49 via a bare `ty check`: 4,072 diagnostics
before (366 error, 3,706 warning), 3,626 after. Every one of the 446 removed is a
warning, and all 366 errors are untouched.

### The groups, and the discriminant each is classified on

`scripts/classify_ty_diagnostics.py` holds these as executable predicates; the
table is its `report` output, not a parallel record. The discriminant column is
the load-bearing one, because most groups share a rule with genuine defects —
under `unknown-argument`, the pydantic-settings `_secrets_dir` kwarg and a
first-party `PMM` kwarg differ only in the symbol the message names, and
`tests/app/sep/test_config.py` holds both.

| Group | Rule(s) | Hits | via override | via comment |
|---|---|---:|---:|---:|
| `settings-subclass-attributes` | `unresolved-attribute` | 137 | 51 | 86 |
| `pydantic-fieldinfo` | `invalid-argument-type` / `invalid-assignment` | 87 | 29 | 58 |
| `env-populated-required-params` | `missing-argument` | 70 | 63 | 7 |
| `pydantic-settings-private-kwargs` | `unknown-argument` | 63 | 58 | 5 |
| `celery-app-attributes` | `unresolved-attribute` | 31 | 10 | 21 |
| `third-party-overload-sets` | `no-matching-overload` | 18 | 18 | 0 |
| `sa-type-typedecorator` | `invalid-argument-type` | 16 | 11 | 5 |
| `absent-modules` | `unresolved-import` | 9 | 9 | 0 |
| `subscripted-generics-called` | `call-non-callable` | 9 | 9 | 0 |
| `fastapi-query-default` | `invalid-parameter-default` | 4 | 4 | 0 |
| `pygments-textlexer` | `unresolved-import` | 2 | 2 | 0 |
| **Total** | | **446** | **264** | **182** |

One group is additionally confined to a set of paths. `Cannot resolve imported
module` reads identically for a golden-app module scaffolded at test time and for
a first-party import someone mistyped, so the message alone cannot establish the
verdict; `absent-modules` therefore matches only under
`tests/app/sep/apps/framework/golden/` and at
`app/sep/sync/syncers/system_facts/payload.py`, and a mistyped import anywhere
else stays a first-party defect. Every other group's message carries the evidence
on its own and matches at any path.

### Two mechanisms, chosen per (file, rule) pair

A `[[tool.ty.overrides]]` entry in `pyproject.toml` covers the 59 pairs whose
*every* hit of that rule in that file is an artifact — 264 hits. Each entry names
explicit file paths, never a directory wildcard, so it cannot silently widen as
files are added, and softens only the one rule it exists for. Overlapping entries
merge their rule tables, so a file legitimately appears in several.

The 27 pairs that mix take a per-site `# ty: ignore[rule]` comment instead — 182
of them across 27 files. A file-level mechanism cannot discriminate within a
file, and an override there would suppress the genuine defects alongside.

**The two mechanisms are never both applied to one (file, rule) pair.**
`unused-ignore-comment` is unlisted in `[tool.ty.rules]` and so inherits
`all = "error"`; an override makes any comment for the same rule in the same file
unused, which is a new error. The same property makes the suppressions
self-cleaning in the desirable direction: a comment that goes stale as the tree
drifts becomes a build error rather than lingering silently.

Two mechanical constraints govern where a comment may sit:

- **The comment must be on the exact line ty reports**, which is often a
  continuation line inside a multi-line call. On the opening line or the closing
  paren it produces `unused-ignore-comment` *and* leaves the diagnostic firing.
- **`ruff format` relocates a comment that pushes its line past the line
  length** — it explodes the call and re-attaches the comment to the closing
  paren, which is the failing placement above. So placement has to be re-derived
  from ty's output *after* formatting, not before; the tree here is at that
  fixpoint.

### What was *not* neutralized, and why

The sqlmodel-vs-sqlalchemy `AsyncSession` mismatch (201 hits of
`invalid-argument-type`, expecting `sqlmodel.ext.asyncio.session.AsyncSession`
and finding the `sqlalchemy` one) is **first-party, not an artifact**. The two
classes are not parallel declarations by two libraries: the sqlmodel class is a
*subclass* of the sqlalchemy one, adding `exec`, and `app/core/db/crud.py`
imports the subclass and calls `session.exec(...)`. A value typed as the
supertype genuinely cannot satisfy a parameter requiring the subtype, so ty is
right and every hit arises where a test file or helper annotates its own
`session` parameter with the sqlalchemy import. Those hits stay reportable and
belong to the first-party remainder.

Recorded while probing that group, and left for the remainder: `app/core/db/utils.py`
declares `-> async_sessionmaker` while returning the *synchronous*
`sessionmaker` from `sqlalchemy.orm`. Parameterizing the return type surfaces a
latent `invalid-return-type` in the same function. The bare annotation is
repeated in four wrappers — `app/inventory/db.py`, `app/sep/db/engine.py`,
`app/tasks/db/engine.py`, `app/core/celery/db.py`. Fixing the factory and all
four does **not** clear the group (measured: 201 hits before, 202 after), because
the test files' own parameter annotations drive it.

There are no retained exceptions: the script's `RETAINED` list is empty, and
`check` prints it on every run so it cannot grow unnoticed. One site needed the
expression split so that an artifact and a first-party diagnostic of the same
rule stopped sharing a line — `_override_nomad` in
`tests/app/tasks/execution/test_nomad_lifecycle.py`.

### The remainder, as a baseline

Per-rule residual under the committed configuration, measured at `8ab18007e`.
Only the nine `warn` rules had artifacts; the `error` rules are listed together
because none did. This residual is the baseline the follow-up work on the
first-party typing defects is sized and tracked against — dated evidence for
that commit, like the per-rule tables above, not a figure to keep current.

| Rule | Before | Artifacts | Residual |
|---|---:|---:|---:|
| `invalid-argument-type` | 2212 | 16 | 2196 |
| `unresolved-attribute` | 885 | 168 | 717 |
| `unknown-argument` | 205 | 63 | 142 |
| `invalid-assignment` | 194 | 87 | 107 |
| `missing-argument` | 119 | 70 | 49 |
| `call-non-callable` | 38 | 9 | 29 |
| `no-matching-overload` | 36 | 18 | 18 |
| `unresolved-import` | 11 | 11 | 0 |
| `invalid-parameter-default` | 6 | 4 | 2 |
| every rule at `error` | 366 | 0 | 366 |
| **Total** | **4072** | **446** | **3626** |

### Reproducing the split

The fingerprint manifest is a build artifact, not a committed file, so the claim
above is checkable rather than asserted:

```bash
# Capture the base run first: the classifier does not exist at the merge base.
git switch --detach $(git merge-base HEAD origin/main)
ty check --output-format concise > /tmp/ty-base.txt
git switch -
python3 scripts/classify_ty_diagnostics.py baseline --from /tmp/ty-base.txt \
    --out /tmp/ty-baseline.json
python3 scripts/classify_ty_diagnostics.py check --baseline /tmp/ty-baseline.json
```

`check` takes the multiset difference over `(path, rule, message)` fingerprints
and fails unless **every** diagnostic that stopped reporting is one the
classification marks as an artifact. That is what a count comparison cannot
establish: a suppression that hides one artifact *and* one first-party
diagnostic, while some unrelated new diagnostic appears, reconciles to the
expected total. The fingerprint is exactly what `classify` reads, so two
diagnostics sharing one always share a verdict; folding the line and column away
costs the check no precision and lets it survive the reformatting the comments
provoke, which would otherwise report every diagnostic below an edited line as
newly suppressed.

`report` prints the same tables from a live run and names any line holding both
an artifact and a first-party diagnostic of the same rule. It does not flag a
group with no hits: on a neutralized tree every group reaches zero by design.
`check` raises that instead, against the baseline — the only run in which a group
matching nothing means its predicate has gone stale rather than done its job.

## Rules ty disables by default

Because `all = "error"` switches on every rule ty knows, including those it ships
disabled, the table also has to take a position on five rules that were not
reported before this policy existed. Together they add 814 diagnostics.

Three are latent-bug detectors and are kept at `error`:
`possibly-unresolved-reference` (11), `possibly-missing-attribute` (2), and
`unsupported-dynamic-base` (1).

Two are set to `ignore`:

- **`missing-type-argument`** (559) flags a generic used without type arguments.
  Bare generics are widespread and intended here; parameterizing all 559 sites is
  its own decision, not a consequence of choosing a severity for the rules that
  were already firing.
- **`missing-override-decorator`** (241) requires PEP 698's `@override` on every
  overriding method. That is a code convention this project has not adopted, and
  the rule detects its absence rather than any defect.

Neither was reported before this table existed, so ignoring them removes no
signal that was previously available. Both remain easy to reconsider: deleting
the entry restores it to the `all = "error"` baseline.

## Tools that invoke ty with explicit paths

`[tool.ty.src]` governs the **repository baseline** — what a full check covers.
It does not scope a tool that passes explicit file paths, because those paths are
the query. Editors, LSP integrations, and any diff-scoped wrapper that checks
only the files a change touches therefore read `[tool.ty.rules]` for severities
but not `[tool.ty.src]` for scope.

That asymmetry is inherent to a path-scoped query and is deliberate; it is not an
inconsistency to be "fixed" by making such a tool read `include`. It does have
one practical consequence worth knowing: because a rule set to `ignore`
disappears from ty's output entirely, it also disappears from any such tool's
report — which is why close calls in this table go to `warn` rather than
`ignore`.

## Changing this policy

- **Moving a rule's severity** — update its row here, and leave a trailing
  comment on its entry only where the reason is not already carried by the rule
  name and the severity. A move from `warn` to `error` should be able to point
  at the artifacts that stopped being artifacts.
- **Adding a tree** — add it to `[tool.ty.src].include` and to the surface table
  above. Nothing checks a tree that is not listed.
- **Upgrading ty** — new rules arrive at `error` through the `all` baseline, and
  the baseline count will move. Re-measure with a bare `ty check` and update the
  recorded baseline. Only that one figure is re-measured: the per-rule hit
  counts and the sampling record stay as they are, dated evidence for calls
  already made rather than values to keep current.
- **Adding or removing a suppression** — never by hand. Add the shape to
  `GROUPS` in `scripts/classify_ty_diagnostics.py` with the discriminant it
  classifies on, then let `report` say which (file, rule) pairs take an override
  and which take per-site comments. `check` against a baseline from the merge
  base is what establishes that no first-party diagnostic went with it.
- **Do not add path arguments to the `typecheck` target.** See the stability
  measurements above.
