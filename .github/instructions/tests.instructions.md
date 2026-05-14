---
applyTo: "tests/**/*.py"
---

# Tests — Mocking, Factories, Patterns

## Directory layout

Tests mirror app structure exactly. `app/sep/snippets/config.py` → `tests/app/sep/snippets/test_config.py`. Flag tests placed at the wrong level.

## Factories — never manual dicts

Test data MUST come from factories under `tests/app/factories.py` (`SchemaWriteFactory`, `TableWriteFactory`, `TaskWriteFactory`, `PeriodicTaskFactory`, etc.) or polyfactory subclasses. Build with `.build()`, customise inline: `CasdoorUserFactory.build(is_admin=True)`. Flag every manual dict where a matching factory exists.

Use mock ID constants from `tests/app/factories.py` (`MOCK_CREATED_NODE_ID`, etc.) — don't invent literals.

## Mock subjects vs boundaries

Every test has a **subject** (code under test + machinery it directly operates on: its session, model instances, loop state) and **boundaries** (HTTP clients to other services, subprocess/Nomad, file I/O, time, randomness). Mock only at the boundaries. Never mock the subject's primary dependency.

## Never mock `AsyncSession` on a session-touching SUT — CRITICAL

If the SUT receives `session: AsyncSession` and performs ANY session operation directly or transitively (`session.add`, `commit`, `refresh`, `execute`, or any `BaseSQLModelManager.save`/`get_or_404`/`create`/`update`), consider using the real `session` fixture from `tests/app/tasks/conftest.py` (or the analogous inventory/sep fixture), not `AsyncMock(spec=AsyncSession)`.

Mocking `AsyncSession` bypasses SQLAlchemy's entire lifecycle — commit/flush, `expire_on_commit`, relationship loading, deferred columns, identity-map caching, lazy loads. A mocked session silently accepts every attribute access, so a test passes green while production fails on the first real call. If a real-session sibling already covers the same SUT entrypoint and outcome, consider deleting the mock-based duplicate; otherwise consider rewriting it with the real `session` fixture in the same PR.

Sub-cases: tuple-as-session typo (`_session = (AsyncMock(...),)` — trailing comma) silently makes every session call a tuple attribute access. `MagicMock(spec=<SQLModel>)` + `AsyncMock(spec=AsyncSession)` together on the same SUT is the most aggressive variant.

## Spec'd mocks required

Always use `spec=ClassName`. Bare `AsyncMock()` / `MagicMock()` silently accept misspelled attribute access. For async: `AsyncMock(spec=SomeAsync)`; assert with `.assert_awaited_once_with()`, not `.assert_called_once*`.

## Don't mock the subject

Patches like `patch.object(<SUT class>, "<sibling_method>", …)` or `patch("app.<sut_module>.<sibling>", …)` turn the test into a self-assertion. Flag any patch targeting a function/method defined in the same module/class as the SUT. Acceptable: patching imported boundaries.

## Three or more boundary mocks signal a missing seam

A test with ≥3 distinct `patch(...)` calls is **Mockery** — the SUT has too many direct boundary dependencies and needs a seam. Consider splitting the SUT before splitting the test.

## Don't reach into private module state

Tests asserting against `_LATEST_RESULTS`, `_CACHE`, or any `_<priv>` module global are coupled to implementation. Expose a public getter.

## Don't ratify the implementation

`assert "<token>" in compiled_sql` where `<token>` is copied verbatim from the SUT is a tautology. Drive the SUT with inputs and assert on observable outputs.

## Loops must run at least twice

A polling/retry/loop SUT exercised with input that triggers exactly one iteration silently passes on off-by-one bugs. Pick input that drives ≥2 iterations.

## Enum-valued assertions

Derive from the enum (`TaskHistoryStatusEnum.SUCCESS.value`), don't hardcode (`"success"`).

## Cleanup

`TestClient` / `AsyncClient` fixtures MUST reset `dependency_overrides = {}` in teardown. Async tests: `@pytest.mark.asyncio`; async fixtures: `@pytest_asyncio.fixture`.

## Coverage-padding duplicates

Two tests differing only in one input → `@pytest.mark.parametrize`.
