# Testing Guidelines

The operational playbook for writing and running tests in SEP. For the layers and the reasoning behind them, see [QA Architecture](qa-architecture.md); for the terse, enforce-able review rules, see [`.github/instructions/tests.instructions.md`](../.github/instructions/tests.instructions.md).

- [Running Tests](#running-tests)
  * [Backend](#backend)
  * [Frontend](#frontend)
- [Where Does My Test Go?](#where-does-my-test-go)
- [Test Design Principles](#test-design-principles)
  * [Mock Only at the Boundaries](#mock-only-at-the-boundaries)
  * [Factories, Never Manual Dicts](#factories-never-manual-dicts)
  * [Don't Ratify the Implementation](#dont-ratify-the-implementation)
- [Environment Management](#environment-management)
- [Continuous Integration](#continuous-integration)

## Running Tests

### Backend

The Python suite is split into lanes selected by marker. The markers are applied automatically per directory, so you never decorate a test by hand.

```shell
make test              # everything, with coverage
make test-unit         # unit lane:        pytest -m unit tests/unit/
make test-integration  # integration lane: pytest -m "integration or not (unit or contract)" tests/
make test-contract     # contract lane:    pytest -m contract tests/contract/ (skips cleanly until M6)
```

### Frontend

```shell
pnpm -r test                              # Vitest unit/component tests across every package
pnpm --filter @sep/framework test:watch   # one package, watch mode
pnpm test:e2e                             # Playwright end-to-end against a vite preview build
```

## Where Does My Test Go?

Tests mirror the `app/` tree exactly. `app/sep/snippets/config.py` → `tests/app/sep/snippets/test_config.py`. A test placed at the wrong level is a review flag.

| You are testing… | Layer | Put it in… |
|------------------|-------|------------|
| A pure backend function (no I/O, no DB, no client) | Unit | `tests/unit/` |
| A route, a session-touching service, plugin wiring | Integration | `tests/app/<mirrors app/ path>` |
| OpenAPI conformance of a mounted app | Contract | `tests/contract/` |
| A React hook, util, or component | Frontend unit | co-located `*.test.tsx` next to the source |
| A full user flow through the shell | End-to-end | `frontend/packages/e2e/tests/` |

## Test Design Principles

### Mock Only at the Boundaries

Every test has a **subject** (the SUT plus its session, model instances, loop state) and **boundaries** (HTTP clients, subprocess/Nomad, file I/O, time, randomness). Mock only the boundaries.

- **Never mock `AsyncSession` on a session-touching SUT.** Use the real `session` fixture from `tests/app/tasks/conftest.py` (or the analogous inventory/sep fixture). A mocked session accepts every attribute access — the test passes green while production fails on the first real call.
- **Don't mock the subject.** Three or more `patch(...)` calls against one SUT is *mockery* — split the SUT instead.
- **Stub external services canonically.** Reach for the helpers in `tests/_stubs/` (`patch_casdoor_sdk`, `patch_nomad_dispatch`, `patch_pmm_metrics`) rather than re-inventing mocks per test.

### Factories, Never Manual Dicts

Test data MUST come from factories under `tests/app/factories.py` (`SchemaWriteFactory`, `TableWriteFactory`, `TaskWriteFactory`, `PeriodicTaskFactory`, …) or their polyfactory subclasses. Build with `.build()` and customise inline:

```python
user = CasdoorUserFactory.build(is_admin=True)
```

Use the mock-ID constants (`MOCK_CREATED_NODE_ID`, …) — don't invent literals.

**Preference order: Factory > `spec=`'d Mock > bare Mock.** A factory exercises field validation; a `spec`'d mock returns an empty string for a `NonEmptyStr` field and masks the failure.

### Don't Ratify the Implementation

`assert "<token>" in compiled_sql` with the token copied verbatim from the SUT is a tautology. Drive the SUT with inputs and assert observable outputs (status code, row count, parsed DOM nodes), not the shape of its own internals.

## Environment Management

- **Markers** are registered in `pyproject.toml` (`unit`, `integration`, `contract`, `syncmysql`).
- **Test env vars** (e.g. `CASDOOR__CLIENT_ID`) are injected by the `env` block under `[tool.pytest.ini_options]` in `pyproject.toml` — no local configuration is required to run the lanes.
- **No external services** are contacted: Casdoor, Nomad, and PMM are stubbed (`tests/_stubs/`); databases use in-memory SQLite fixtures.
- **Parallelism** is on by default (`PYTEST_WORKERS=auto`); override with `make test PYTEST_WORKERS=1` when debugging ordering issues.

## Continuous Integration

Every PR runs the unit, integration, and contract lanes (`.github/workflows/python.yaml`), the frontend Vitest and Playwright jobs, and the dependency audit (`.github/workflows/audit.yaml`: `pip-audit` + `pnpm audit`). Keep new tests inside a lane so CI picks them up automatically.
