# SEP-1166 mutmut pilot report (DRAFT — local review)

**Status:** Phase 1 local draft. Not yet posted to Jira.

| Field | Value |
|-------|--------|
| Runner | mutmut **3.6.0** |
| Scope | `app/core/db/utils.py` only (`[tool.mutmut].only_mutate`) |
| Test driver | `tests/app/core/db/test_utils.py` |
| Postgres DSN | **unset** — 5 `@pytest.mark.postgres` tests skipped |
| Host | Darwin; `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` |
| Date | 2026-07-28 |
| Method | Stock mutmut + 4 supplemental AC operator patches (restored after each) |

Mutmut show hunks use trampoline-relative line numbers; **Source location** below maps each survivor to the real line in [`app/core/db/utils.py`](../../app/core/db/utils.py).

---

## Exact mutation-test output

### Final progress (from `poetry run mutmut run`)

```text
Running mutation testing
122/122  🎉 58  🫥 37  ⏰ 0  🤔 0  🙁 27  🔇 0  🧙 0
53.48 mutations/second
MUTMUT_EXIT:0
```

Legend (mutmut 3.x):

| Symbol | Meaning |
|--------|---------|
| 🎉 | killed |
| 🫥 | no tests |
| 🙁 | survived |
| ⏰ | timeout |
| 🤔 | suspicious |
| 🔇 | skipped |

### Totals

| Metric | Count |
|--------|------:|
| Generated | 122 |
| Killed | 58 |
| Survived | 27 |
| No tests | 37 |
| Timed out | 0 |
| Suspicious | 0 |

Kill rate among mutants with tests: **58 / (58 + 27) ≈ 68%**.
Including “no tests”: **58 / 122 ≈ 48%**.

### Exact `mutmut results --all true` listing

```text
## survived (27)
    app.core.db.utils.x_get_async_session_maker_from_engine__mutmut_1: survived
    app.core.db.utils.x_get_async_session_maker_from_engine__mutmut_4: survived
    app.core.db.utils.x_create_app_async_engine__mutmut_2: survived
    app.core.db.utils.x_create_app_async_engine__mutmut_3: survived
    app.core.db.utils.x_create_app_async_engine__mutmut_5: survived
    app.core.db.utils.x_create_app_async_engine__mutmut_6: survived
    app.core.db.utils.x_create_app_async_engine__mutmut_8: survived
    app.core.db.utils.x_json_join_path_elems__mutmut_3: survived
    app.core.db.utils.x_json_join_path_elems__mutmut_4: survived
    app.core.db.utils.x_func_json_extract__mutmut_6: survived
    app.core.db.utils.x_func_json_extract__mutmut_10: survived
    app.core.db.utils.x_func_json_extract__mutmut_15: survived
    app.core.db.utils.x_func_json_extract__mutmut_17: survived
    app.core.db.utils.x_func_json_extract__mutmut_18: survived
    app.core.db.utils.x_func_json_extract__mutmut_20: survived
    app.core.db.utils.x_func_json_extract__mutmut_21: survived
    app.core.db.utils.x_func_json_extract__mutmut_22: survived
    app.core.db.utils.x_func_json_extract__mutmut_30: survived
    app.core.db.utils.x_func_json_extract__mutmut_33: survived
    app.core.db.utils.x_func_json_extract__mutmut_38: survived
    app.core.db.utils.x_func_json_extract__mutmut_40: survived
    app.core.db.utils.x_func_json_extract__mutmut_43: survived
    app.core.db.utils.x_func_json_extract__mutmut_46: survived
    app.core.db.utils.x_idempotent_insert__mutmut_9: survived
    app.core.db.utils.x_compare_type__mutmut_1: survived
    app.core.db.utils.x_compare_type__mutmut_2: survived
    app.core.db.utils.x_compare_type__mutmut_3: survived

## no tests (37)
    app.core.db.utils.x_prepare_unsafe_value_for_json_comparison__mutmut_1: no tests
    app.core.db.utils.x_prepare_unsafe_value_for_json_comparison__mutmut_2: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_1: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_2: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_3: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_4: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_5: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_6: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_7: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_8: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_9: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_10: no tests
    app.core.db.utils.x_acquire_pg_advisory_xact_lock__mutmut_11: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_1: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_2: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_3: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_4: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_5: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_6: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_7: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_8: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_9: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_10: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_11: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_12: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_13: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_14: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_15: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_16: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_17: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_18: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_19: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_20: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_21: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_22: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_23: no tests
    app.core.db.utils.x_check_constraint_lists_members__mutmut_24: no tests

## killed (58)
    app.core.db.utils.x_get_async_session_maker_from_engine__mutmut_2: killed
    app.core.db.utils.x_get_async_session_maker_from_engine__mutmut_3: killed
    app.core.db.utils.x_get_async_session_maker_from_engine__mutmut_5: killed
    app.core.db.utils.x_get_async_session_maker_from_engine__mutmut_6: killed
    app.core.db.utils.x_get_async_session_maker_from_engine__mutmut_7: killed
    app.core.db.utils.x_create_app_async_engine__mutmut_1: killed
    app.core.db.utils.x_create_app_async_engine__mutmut_4: killed
    app.core.db.utils.x_create_app_async_engine__mutmut_7: killed
    app.core.db.utils.x_json_join_path_elems__mutmut_1: killed
    app.core.db.utils.x_json_join_path_elems__mutmut_2: killed
    app.core.db.utils.x_json_join_path_elems__mutmut_5: killed
    app.core.db.utils.x_json_join_path_elems__mutmut_6: killed
    app.core.db.utils.x__column_resolves_to_json__mutmut_1: killed
    app.core.db.utils.x__column_resolves_to_json__mutmut_2: killed
    app.core.db.utils.x_func_json_extract__mutmut_1: killed
    app.core.db.utils.x_func_json_extract__mutmut_2: killed
    app.core.db.utils.x_func_json_extract__mutmut_3: killed
    app.core.db.utils.x_func_json_extract__mutmut_4: killed
    app.core.db.utils.x_func_json_extract__mutmut_5: killed
    app.core.db.utils.x_func_json_extract__mutmut_7: killed
    app.core.db.utils.x_func_json_extract__mutmut_8: killed
    app.core.db.utils.x_func_json_extract__mutmut_9: killed
    app.core.db.utils.x_func_json_extract__mutmut_11: killed
    app.core.db.utils.x_func_json_extract__mutmut_12: killed
    app.core.db.utils.x_func_json_extract__mutmut_13: killed
    app.core.db.utils.x_func_json_extract__mutmut_14: killed
    app.core.db.utils.x_func_json_extract__mutmut_16: killed
    app.core.db.utils.x_func_json_extract__mutmut_19: killed
    app.core.db.utils.x_func_json_extract__mutmut_23: killed
    app.core.db.utils.x_func_json_extract__mutmut_24: killed
    app.core.db.utils.x_func_json_extract__mutmut_25: killed
    app.core.db.utils.x_func_json_extract__mutmut_26: killed
    app.core.db.utils.x_func_json_extract__mutmut_27: killed
    app.core.db.utils.x_func_json_extract__mutmut_28: killed
    app.core.db.utils.x_func_json_extract__mutmut_29: killed
    app.core.db.utils.x_func_json_extract__mutmut_31: killed
    app.core.db.utils.x_func_json_extract__mutmut_32: killed
    app.core.db.utils.x_func_json_extract__mutmut_34: killed
    app.core.db.utils.x_func_json_extract__mutmut_35: killed
    app.core.db.utils.x_func_json_extract__mutmut_36: killed
    app.core.db.utils.x_func_json_extract__mutmut_37: killed
    app.core.db.utils.x_func_json_extract__mutmut_39: killed
    app.core.db.utils.x_func_json_extract__mutmut_41: killed
    app.core.db.utils.x_func_json_extract__mutmut_42: killed
    app.core.db.utils.x_func_json_extract__mutmut_44: killed
    app.core.db.utils.x_func_json_extract__mutmut_45: killed
    app.core.db.utils.x_func_json_extract__mutmut_47: killed
    app.core.db.utils.x_func_json_extract__mutmut_48: killed
    app.core.db.utils.x_idempotent_insert__mutmut_1: killed
    app.core.db.utils.x_idempotent_insert__mutmut_2: killed
    app.core.db.utils.x_idempotent_insert__mutmut_3: killed
    app.core.db.utils.x_idempotent_insert__mutmut_4: killed
    app.core.db.utils.x_idempotent_insert__mutmut_5: killed
    app.core.db.utils.x_idempotent_insert__mutmut_6: killed
    app.core.db.utils.x_idempotent_insert__mutmut_7: killed
    app.core.db.utils.x_idempotent_insert__mutmut_8: killed
    app.core.db.utils.x_idempotent_insert__mutmut_10: killed
    app.core.db.utils.x_compare_type__mutmut_4: killed
```

---

## Survivor → location → test to add (kill map)

### A. `func_json_extract` (SEP-1008 SUT) — 14 survivors

| Mutant ID | Source | Exact mutation (`mutmut show`) | Why it survived | Test to add to kill it |
|-----------|--------|--------------------------------|-----------------|------------------------|
| `x_func_json_extract__mutmut_6` | L164 | `cast(column, JSON)` → `cast(None, JSON)` | Text-column compile still emits a `CAST`; JSON/JSONB arms skip the else-branch. No assert that the cast *target* is the column. | Extend `test_func_json_extract_postgresql_text_column_wraps_in_cast`: assert cast operand is the column name (e.g. `CAST(kwargs AS JSON)` / `kwargs` appears inside the CAST), not only ordered `CAST`/`AS JSON` tokens. |
| `x_func_json_extract__mutmut_10` | L165 | `path_elems[:-1]` → `path_elems[:+1]` | For length-1 paths the loop is empty either way; for nested paths `:+1` may still iterate oddly without failing substring/order asserts. | Nested PG compile test that asserts **exact** intermediate count: one ` -> '` (or `->'`) **before** the final `->>`, and fails if the intermediate key is wrong/missing — e.g. harden `test_func_json_extract_postgresql_json_column_arrow_chain[nested_path]` with regex `\->\s*'meta'\s*\->>\s*'key'` (no substring cheat). |
| `x_func_json_extract__mutmut_15` | L166 | `op("->")` → `op("XX->XX")` | Single-key paths never enter the intermediate loop; nested tests that only check `"->"` as substring still match inside `->>`. | Same nested regex as above requiring a **standalone** intermediate `->` token distinct from `->>`. Would also kill supplemental S2. |
| `x_func_json_extract__mutmut_17` | L166 | `literal(elem, Text, …)` → `literal(elem, None, …)` | Compile-only suite does not assert RHS bind type on intermediate `->`. | Extend `test_func_json_extract_postgresql_mapped_column_binds_path_as_text` (or nested compile): compile without `literal_binds` and assert intermediate binds are `Text` / no `::JSON` on the `->` RHS. |
| `x_func_json_extract__mutmut_18` | L166 | `literal_execute=True` → `None` | Postcompile / string checks only look for `'task'` on the **leaf**; intermediate inlining untested; `None` may still inline. | Nested-path variant of `test_func_json_extract_postgresql_path_is_inlined_for_index_match`: postcompile assert `'meta'` and `'key'` appear inline and **no** `%(` / `:param` placeholders on either arrow RHS. |
| `x_func_json_extract__mutmut_20` | L166 | drop `Text` positional | Same as 17 — type default still “works” for compile. | Same as mutmut_17. |
| `x_func_json_extract__mutmut_21` | L166 | drop `literal_execute=` kw | Defaults may still inline under dialect. | Same as mutmut_18 (postcompile nested inline assert). |
| `x_func_json_extract__mutmut_22` | L166 | `literal_execute=True` → `False` | Ticket-called-out gap: tests see `'task'` with `literal_binds` / weak postcompile, not planner/index identity. | Prefer **real-PG** (`TestFuncJsonExtractOnRealPostgres` / SEP-1148): query using the extract under an expression index and assert index use / equal results; or strengthen postcompile to fail when path is a bound param (`%(…)s`) instead of `'task'`. Apply to **intermediate** keys too. |
| `x_func_json_extract__mutmut_30` | L168 | leaf `literal(..., Text, …)` → `..., None, …` | Leaf type not asserted beyond “compiles”. | Assert compile of mapped-column leaf has text-typed bind (existing mapped-column test only bans `::JSON` — add positive assert on bind type / no JSON cast on leaf RHS). |
| `x_func_json_extract__mutmut_33` | L168 | drop leaf `Text` positional | Same as 30. | Same as mutmut_30. |
| `x_func_json_extract__mutmut_38` | L171 | `json_extract(column, …)` → `json_extract(None, …)` | SQLite/MySQL tests only assert `json_extract` + path string, not the column argument. | Extend `test_func_json_extract_single_key_renders_json_extract` / sqlite nested: assert column name `execution_request` appears as first arg, e.g. `json_extract(execution_request, '$.task')`. |
| `x_func_json_extract__mutmut_40` | L171 | drop `column` positional | Same — arity may shift so path still matches loosely. | Same as mutmut_38 (full `json_extract(<col>, <path>)` shape). |
| `x_func_json_extract__mutmut_43` | L172 | path `literal(..., Text, …)` → `..., None, …` | Path string still present; type ignored. | Keep path assert; add that the path bind is text / inlined (see `test_func_json_extract_sqlite_path_is_inlined_for_index_match` — already strong for inlining; add MySQL twin + type check if needed). |
| `x_func_json_extract__mutmut_46` | L172 | drop path `Text` positional | Same as 43. | Same as mutmut_43. |

### B. Other survivors in `utils.py` (still in pilot scope) — 13 survivors

| Mutant ID | Source | Exact mutation | Why it survived | Test to add to kill it |
|-----------|--------|----------------|-----------------|------------------------|
| `x_get_async_session_maker_from_engine__mutmut_1` | L66 | `sessionmaker(engine, …)` → `sessionmaker(None, …)` | `test_get_async_session_maker_from_engine` only checks `expire_on_commit` / session class, not bind. | Assert `session_maker.kw["bind"] is engine` (or open a connection and check `session.bind`). |
| `x_get_async_session_maker_from_engine__mutmut_4` | L66 | drop `engine` positional | Same. | Same as mutmut_1. |
| `x_create_app_async_engine__mutmut_2` | L84 | `echo=False` → `echo=None` | `TestCreateAppAsyncEngine` only asserts pool sizing, not `echo`. | Assert `engine.echo is False` (and not truthy). |
| `x_create_app_async_engine__mutmut_3` | L85 | `json_serializer=json_serializer` → `None` | Serializer never asserted. | Round-trip a JSON value through the engine’s serializer / assert `engine.json_serializer is json_serializer` (or encode a non-default type and expect our helper’s behaviour). |
| `x_create_app_async_engine__mutmut_5` | L84 | drop `echo=False` | Default may differ by SQLAlchemy version but still “works”. | Same as mutmut_2. |
| `x_create_app_async_engine__mutmut_6` | L85 | drop `json_serializer=…` | Same as 3. | Same as mutmut_3. |
| `x_create_app_async_engine__mutmut_8` | L84 | `echo=False` → `echo=True` | Pool tests ignore echo. | Assert `engine.echo is False`. |
| `x_json_join_path_elems__mutmut_3` | L101 | `json_path += f"[{elem}]"` → `=` | Digit path branch never exercised (tests use string keys only). | New unit test: `json_join_path_elems("items", "0", "name")` → `"$.items[0].name"` (and fail if digit segment resets the path). |
| `x_json_join_path_elems__mutmut_4` | L101 | `+=` → `-=` | Same — digit branch unused. | Same digit-index path test as mutmut_3. |
| `x_idempotent_insert__mutmut_9` | L197 | `"IGNORE"` → `"ignore"` | MySQL compile assert likely case-insensitive or only checks class/substring loosely. | In `TestIdempotentInsert` MySQL case: assert compiled SQL contains exact `IGNORE` (case-sensitive), not `ignore`. |
| `x_compare_type__mutmut_1` | L244 | `and` → `or` for Text/AutoString | Existing tests only cover AutoJSON vs JSON/JSONB, not Text/AutoString arm. | New test: `compare_type(..., inspected_type=Text(), metadata_type=AutoString())` → `False`; and a negative case where only one side matches → `None` (kills `or`). |
| `x_compare_type__mutmut_2` | L245 | `return False` → `return True` | Only AutoJSON happy-path asserts `False`; Text/AutoString arm untested so this early-return mutant can survive depending on which branch mutmut hit — here it is the Text/AutoString `return False`. | Same Text/AutoString test asserting **exactly** `False` (not `True`/`None`). |
| `x_compare_type__mutmut_3` | L246 | `and` → `or` for AutoJSON/JSON | Existing tests pass when **both** sides match; `or` still returns False. | Negative test: AutoJSON metadata + non-JSON inspected type (e.g. `Integer`) → must be `None` (not `False`). That kills `or`. |

### C. Supplemental AC operators (not stock mutmut IDs)

| ID | Source | Mutation | Result | Test to add if still surviving |
|----|--------|----------|--------|--------------------------------|
| S1 | L167 | `->>` → `->` | **KILLED** by existing compile suite | — |
| S2 | L166 | `->` → `->>` | **SURVIVED** (22 passed) | Same nested **token-safe** regex as mutmut_15 (`\->` not satisfied by `->>`). |
| S3 | L164 | always `expression = column` (no cast) | **KILLED** by text-column cast tests | — |
| S4 | L166 | `literal(elem,…)` → `literal("MUTATED",…)` | **KILLED** by nested_path compile tests | — |

---

## “No tests” functions (37 mutants) — what to add

These never run under `test_utils.py`, so every mutant is `no tests` until a driver exists:

| Function | Source | Mutant count | Tests to add |
|----------|--------|-------------:|--------------|
| `prepare_unsafe_value_for_json_comparison` | L201–217 | 2 | Parametrize PG → `str(value)`; non-PG → identity. |
| `acquire_pg_advisory_xact_lock` | L251–266 | 11 | Mock `Connection`: PG dialect executes `pg_advisory_xact_lock`; non-PG is no-op (no execute). |
| `check_constraint_lists_members` | L269+ | 24 | Fixture CHECK text with quoted members; assert True/False for subset/superset; missing table → False. |

---

## Priority order to kill the SEP-1008-relevant survivors

1. **Nested PG arrow token asserts** (kills mutmut_15, S2, helps mutmut_10).
2. **Postcompile / real-PG inlining** for intermediate + leaf `literal_execute` (kills 18, 21, 22; strengthens 1148).
3. **Cast operand / column identity** on text branch (kills mutmut_6).
4. **SQLite/MySQL `json_extract(col, path)` full shape** (kills 38, 40).
5. Leaf/intermediate `Text` bind typing (kills 17, 20, 30, 33, 43, 46).

---

## Repro

```bash
cd /path/to/SEP   # not mutants/
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_FALLBACK_LIBRARY_PATH}"
unset SEP_TEST_POSTGRES_DSN
poetry run mutmut run
poetry run mutmut results --all true
poetry run mutmut show 'app.core.db.utils.x_func_json_extract__mutmut_22'
```

Config: `[tool.mutmut]` in `pyproject.toml`. Working copy: gitignored `mutants/`.
