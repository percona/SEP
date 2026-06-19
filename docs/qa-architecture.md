# QA Architecture — Testing Trophy

Engineering-facing description of the testing architecture adopted by SEP. Defines the layers, the tooling each one uses, and where tests live. Approved under **SEP-1191** and implemented in **SEP-1194**.

## Contents

| File | Purpose |
|------|---------|
| [`testing-guidelines.md`](testing-guidelines.md) | Operational playbook — how to run a lane, where a test goes, what to mock |
| [`.github/instructions/tests.instructions.md`](../.github/instructions/tests.instructions.md) | Terse, enforce-able review rules for `tests/**/*.py` |

This document is the **what and why**; `testing-guidelines.md` is the **how**.

## Audience

This is for engineers writing or reviewing tests in SEP who need to decide:

- Which layer a given test belongs to, and therefore where it lands
- Which tooling and fixtures to reach for in that layer
- Why the suite is split into separate lanes rather than one `make test`

It is **not** a coverage report or a per-plugin test catalogue.

## Shape

SEP follows the **Testing Trophy**, not the classic pyramid: the bulk of the value sits in the *integration* layer, on a fast *unit* base, under a thin *contract* control and a small *end-to-end* cap. The guiding principles are:

- **Shift-left.** Defects are cheaper in the fast lanes — push each property down to the lowest layer that can still prove it.
- **Separation of concerns.** Each layer answers a different question and runs as its own lane, so a red build tells you *where* the contract broke.
- **Continuous integration.** Every lane runs on every PR (see [CI integration](#ci-integration)).
- **Modular test design.** Test data comes from factories and external services from canonical stubs — no hand-rolled dicts or ad-hoc mocks.

## Layers

| Layer | Question it answers | Tooling | Location | Marker | Lane |
|-------|---------------------|---------|----------|--------|------|
| **Unit (backend)** | Does this pure function behave? | pytest | `tests/unit/` | `unit` | `make test-unit` |
| **Unit / component (frontend)** | Does this hook / component / util behave? | Vitest | `frontend/packages/*/src/**/*.test.ts(x)` | — | `pnpm -r test` |
| **Integration (backend)** | Do the wired-together routers, sessions, and plugins honour their contract? | pytest + `TestClient` | `tests/app/` | `integration` | `make test-integration` |
| **Contract** | Does the running API still match its declared OpenAPI schema? | Schemathesis | `tests/contract/` | `contract` | `make test-contract` |
| **End-to-end** | Can a user complete the flow through the real React shell? | Playwright | `frontend/packages/e2e/tests/*.spec.ts` | — | `pnpm test:e2e` |

Each layer ships **one reference example** that documents the canonical pattern by example. Read it before writing your first test in that layer:

- **Unit** — `tests/unit/test_example_string_utils.py`
- **Integration** — `tests/app/test_example_api_route.py`
- **Contract** — `tests/contract/test_example_openapi_contract.py`
- **End-to-end** — `frontend/packages/e2e/tests/example.spec.ts`
- **Frontend unit/component (Vitest)** — the pattern is already established across `frontend/packages/framework/src/` (hooks, utils, components). Use any co-located `*.test.tsx` there as the reference, e.g. `frontend/packages/framework/src/utils/resolvePath.test.ts`.

## Backend markers are applied automatically

The three Python lanes are selected by pytest **markers**, not by directory renames. A per-directory `conftest.py` applies the marker to every test collected under it via `pytest_collection_modifyitems`, so no manual `@pytest.mark.*` decoration is required:

| Directory | `conftest.py` applies |
|-----------|-----------------------|
| `tests/unit/` | `unit` |
| `tests/app/` | `integration` |
| `tests/contract/` | `contract` |

This is deliberate. Integration tests stay in their historical `tests/app/` tree — which mirrors `app/` one-to-one — instead of being forced through a large, churny rename. The marker is the layer; the directory name is incidental.

## External-service stubs

Tests must never hit Casdoor, Nomad, or PMM. `tests/_stubs/` holds the canonical stub surface for each, exposing `patch_*` helpers that point at the **real** client methods:

| Stub | Patches |
|------|---------|
| `tests/_stubs/casdoor.py` | `CasdoorSDK.introspect_token`, `CasdoorSDK.get_user` |
| `tests/_stubs/nomad.py` | `NomadExecutor.dispatch_job` |
| `tests/_stubs/pmm.py` | `PMMRemoteAPI.get_nodes`, `PMMRemoteAPI.get_services` |

These modules document the contract by example today. Milestone **M4** consolidates the per-plugin stubs currently scattered across `conftest.py` modules into this single source of truth, recorded against staging with `vcrpy`.

## CI integration

- `.github/workflows/python.yaml` runs the **unit**, **integration**, and **contract** lanes as separate jobs across the supported Python matrix.
- `.github/workflows/audit.yaml` runs `pip-audit` (Python) and `pnpm audit` (Node), and is required for overall CI success.
- Frontend Vitest (`pnpm -r test`) and Playwright E2E run in the frontend CI jobs.

## What this does NOT cover yet

The architecture lands incrementally. Known deferrals:

- **Stub consolidation (M4).** `tests/_stubs/` documents the contract by example; the per-plugin stubs are not yet folded in.
- **Contract enforcement (M6).** `schemathesis` is not yet declared in `pyproject.toml`, so the contract reference test `pytest.importorskip`s it. The lane therefore runs and **skips cleanly** rather than failing — it does not yet validate any API. Declaring the dependency at M6 turns the contract lane from *structure* into *enforcement*.
