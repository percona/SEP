---
applyTo: "tests/**/*.py"
---

# Tests — Mocking, Factories, Patterns

## Directory layout

Tests mirror app structure exactly. `app/sep/snippets/config.py` → `tests/app/sep/snippets/test_config.py`. Flag tests at the wrong level.

**Don't duplicate fixtures across modules — promote them.** Before adding a fixture or module-level helper, grep the nearest `conftest.py` and sibling modules for an equivalent. Any bootstrap that two or more modules need (in-memory engine + `metadata.create_all`, seed-row builder, client factory) belongs in the nearest shared `conftest.py`, parametrized when call sites differ — not copied per module.

## Factories — never manual dicts

Test data MUST come from factories under `tests/app/factories.py` (`SchemaWriteFactory`, `TableWriteFactory`, `TaskFactory` / `GeneratedTaskFactory`, `PeriodicTaskFactory`, …). Build with `.build()`, customise inline: `CasdoorUserFactory.build(is_admin=True)`. Use mock ID constants from `tests/app/factories.py`.

**Preference order: Factory > `spec=`'d Mock > bare Mock.** Inside the subject of a test, prefer `Factory.build(field=…)` over `MagicMock(spec=Model)` — the factory exercises field validation, where a spec'd mock returns an empty string for a `NonEmptyStr` field and masks the failure. Bare `MagicMock()` / `AsyncMock()` is a smell when the value has a model class to spec against.

**New/tightened constraints need a rejection test.** When a PR tightens a field (`str` → `NonEmptyStr`, adds `min_length` / `field_validator` / `Field(gt=…)`), require a `pytest.raises(ValidationError)` test for the now-invalid input — a happy-path-only test lets the constraint silently revert. **Reachability carve-out:** if moving from a spec'd mock to a factory closes off a branch because the constraint makes that state impossible (an empty-address test where `Node.address` is `NonEmptyStr`), drop the test — don't keep the spec'd mock alive to preserve it.

## Don't drop assertions for unchanged behavior

Editing an existing test MUST NOT remove an `assert` unless the asserted behavior itself changed in the same PR. If the mapping, field, or side effect under assertion is untouched by the diff, the assertion stays — dropping it silently narrows what the test proves and lets a later regression pass green. Sibling tests asserting the same property are the tell: if several parametrize cases assert `events[0].step == "step1"` and one edited case quietly drops it while the step mapping is unchanged, flag it as unintended coverage loss.

## Mock subjects vs boundaries — critical

Every test has a **subject** (SUT + its session, model instances, loop state) and **boundaries** (HTTP clients, subprocess/Nomad, file I/O, time, randomness). Mock only at the boundaries.

**Never mock `AsyncSession` on a session-touching SUT.** If the SUT receives `session: AsyncSession` and performs any session op directly or transitively (`add`, `commit`, `refresh`, `execute`, any `BaseSQLModelManager` method), use the real `session` fixture from `tests/app/tasks/conftest.py`. A mocked session silently accepts every attribute access — the test passes green while production fails on the first real call. Watch for `_session = (AsyncMock(...),)` (1-tuple typo) and `MagicMock(spec=<SQLModel>)` + `AsyncMock(spec=AsyncSession)` together.

**Don't mock the subject.** `patch.object(<SUT class>, "<sibling>")` / `patch("app.<sut_module>.<sibling>")` turn the test into a self-assertion. Always use `spec=`; assert async with `.assert_awaited_once_with()`. ≥3 `patch(...)` against one SUT is **Mockery** — split the SUT.

**Prefer `dependency_overrides` over `patch()` for `Depends` callables.** When a route reaches a callable via `Annotated[T, Depends(fn)]`, override it with `app.dependency_overrides[fn] = lambda: fake`, not `patch("app.<module>.fn", …)` — the patch form forces a `# noqa: F401` re-export in the route module. A `noqa: F401` re-export whose only consumer is a `patch(...)` string in the sibling test is the tell; flag both and rewrite as an override.

**Hermetic handler tests: mock every fan-out point.** If any sibling test for a handler mocks dependency X (`SnippetManager.count`, an API client), every new test asserting on that handler's response body must also mock X — partial mocking diverges between CI (empty DB) and local (populated). Integration tests that explicitly wire a live DB are exempt.

## Body-dep override masks form/JSON parsing — critical

When a route's body is `Annotated[<Model>, Form()]` / `Annotated[<Model>, Body()]`, the test MUST NOT override the dep that materialises that body model (`dependency_overrides[build_<app>_task_payload]`, `dependency_overrides[parse_<resource>_form]`, …). Such overrides remove the Pydantic model from FastAPI's body-field resolution, so body-parsing regressions (422 in production) pass green. At least one test per POST/PUT/PATCH route MUST issue a real `test_client.post(...)` with realistic data and no body-dep override. Overriding `validate_csrf`, `get_current_user`, `get_session`, `get_inventory_api`, `get_tasks_api` is fine.

## Compile-only SQL ≠ engine coverage

`.compile(dialect=postgresql.dialect(), ...)` + `assert "->>" in rendered` verifies the rendered shape, NOT that the engine accepts it. PostgreSQL's `->`/`->>` require `json`/`jsonb` — a compile-only test on a `Text` column passes while production rejects the SQL. Dialect-specific helpers MUST have a real-engine execution test per `(dialect × column type)`. SQLite is not a substitute for PostgreSQL.

## Don't ratify the implementation

`assert "<token>" in compiled_sql` with `<token>` copied verbatim from the SUT is a tautology. Same for HTML — substring matches against template output (`'selected>hosts</option>' in response.text`) ratify the template, not the route's contract. Drive the SUT with inputs and assert observable outputs (status, row count, parsed DOM nodes).

## Loops, enums, settings, private state

- **Loops:** a polling/retry SUT MUST have a test that drives ≥2 iterations.
- **Recovery branches:** any `try`/`except` whose body promises non-trivial recovery (rollback-then-retry, default-fallback, replay) MUST have a test that forces the trigger condition. Pure log-and-reraise is exempt.
- **Enums:** derive from `TaskHistoryStatusEnum.SUCCESS.value`, not `"success"`. When the test's point is that a value *validated into* the enum member (not merely matches the string), assert `field is Enum.MEMBER` (identity) alongside `field.value == "…"` — `StrEnum` equals its raw string, so `==` passes even for a string that bypassed validation.
- **Settings:** capture from the live settings object; don't hardcode the YAML default. The override value MUST differ from the resolved default (`override = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT`) — otherwise the test passes whether the override fired or not.
- **Private state:** `_LATEST_RESULTS`, `_CACHE`, any `_<priv>` module global — expose a public getter.

## Cleanup & duplicates

`TestClient`/`AsyncClient` fixtures reset `dependency_overrides = {}` in teardown. Async: `@pytest.mark.asyncio`, `@pytest_asyncio.fixture`. Two tests differing only in one input → `@pytest.mark.parametrize`.

Never wrap `TestClient(sep_app)` in `with …:` for a unit test — the context-manager form enters `sep_lifespan` → `init_sep_db()` and seeds the Celery beat DB, turning a unit test into a lifespan-dependent one with hidden cross-test coupling. If the lifespan path is genuinely needed, patch the startup chain to a no-op first.
