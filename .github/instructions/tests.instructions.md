---
applyTo: "tests/**/*.py"
---

# Tests — Mocking, Factories, Patterns

## Directory layout

Tests mirror app structure exactly. `app/sep/snippets/config.py` → `tests/integration/sep/snippets/test_config.py`. Flag tests placed at the wrong level.

## Factories — never manual dicts

Test data MUST come from factories under `tests/factories.py` (`SchemaWriteFactory`, `TableWriteFactory`, `TaskWriteFactory`, `PeriodicTaskFactory`, etc.) or polyfactory subclasses. Build with `.build()`, customise inline: `CasdoorUserFactory.build(is_admin=True)`. Flag every manual dict where a matching factory exists.

Use mock ID constants from `tests/factories.py` (`MOCK_CREATED_NODE_ID`, etc.) — don't invent literals.

## Mock subjects vs boundaries — critical

Every test has a **subject** (SUT + its session, model instances, loop state) and **boundaries** (HTTP clients, subprocess/Nomad, file I/O, time, randomness). Mock only at the boundaries.

**Never mock `AsyncSession` on a session-touching SUT.** If the SUT receives `session: AsyncSession` and performs any session op directly or transitively (`add`, `commit`, `refresh`, `execute`, any `BaseSQLModelManager` method), use the real `session` fixture from `tests/app/tasks/conftest.py`. A mocked session silently accepts every attribute access — the test passes green while production fails on the first real call. Watch for `_session = (AsyncMock(...),)` (1-tuple typo) and `MagicMock(spec=<SQLModel>)` + `AsyncMock(spec=AsyncSession)` together.

If the SUT receives `session: AsyncSession` and performs ANY session operation directly or transitively (`session.add`, `commit`, `refresh`, `execute`, or any `BaseSQLModelManager.save`/`get_or_404`/`create`/`update`), consider using the real `session` fixture from `tests/integration/tasks/conftest.py` (or the analogous inventory/sep fixture), not `AsyncMock(spec=AsyncSession)`.

## Body-dep override masks form/JSON parsing — critical

When a route's body is `Annotated[<Model>, Form()]` / `Annotated[<Model>, Body()]`, the test MUST NOT override the dep that materialises that body model (`dependency_overrides[build_<plugin>_task_payload]`, `dependency_overrides[parse_<resource>_form]`, …). Such overrides remove the Pydantic model from FastAPI's body-field resolution, so body-parsing regressions (422 in production) pass green. At least one test per POST/PUT/PATCH route MUST issue a real `test_client.post(...)` with realistic data and no body-dep override. Overriding `validate_csrf`, `get_current_user`, `get_session`, `get_inventory_api`, `get_tasks_api` is fine.

## Compile-only SQL ≠ engine coverage

`.compile(dialect=postgresql.dialect(), ...)` + `assert "->>" in rendered` verifies the rendered shape, NOT that the engine accepts it. PostgreSQL's `->`/`->>` require `json`/`jsonb` — a compile-only test on a `Text` column passes while production rejects the SQL. Dialect-specific helpers MUST have a real-engine execution test per `(dialect × column type)`. SQLite is not a substitute for PostgreSQL.

## Don't ratify the implementation

`assert "<token>" in compiled_sql` with `<token>` copied verbatim from the SUT is a tautology. Same for HTML — substring matches against template output (`'selected>hosts</option>' in response.text`) ratify the template, not the route's contract. Drive the SUT with inputs and assert observable outputs (status, row count, parsed DOM nodes).

## Loops, enums, settings, private state

- **Loops:** a polling/retry SUT MUST have a test that drives ≥2 iterations.
- **Enums:** derive from `TaskHistoryStatusEnum.SUCCESS.value`, not `"success"`.
- **Settings:** capture from the live settings object; don't hardcode the YAML default. The override value MUST differ from the resolved default (`override = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT`) — otherwise the test passes whether the override fired or not.
- **Private state:** `_LATEST_RESULTS`, `_CACHE`, any `_<priv>` module global — expose a public getter.

## Cleanup & duplicates

`TestClient`/`AsyncClient` fixtures reset `dependency_overrides = {}` in teardown. Async: `@pytest.mark.asyncio`, `@pytest_asyncio.fixture`. Two tests differing only in one input → `@pytest.mark.parametrize`.
