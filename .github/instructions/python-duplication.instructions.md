---
applyTo: "**/*.py"
---

# Python — Duplication & Existing-Pattern Reuse

The most common LLM-review failure is approving correct-but-reinvented code. Before accepting any new helper, constant, decorator, or pattern, check whether the codebase already has it.

## DUP-1 — Duplicated literals

Same string or numeric literal appearing in 2+ files in the diff (or 1 in the diff plus 1+ in `main`) MUST be a named constant.

- **Important** if the literal appears in 3+ files, if changing it would require touching every occurrence, or if it encodes a convention (port, key, format string).
- **Minor** if it appears in 2 files and is unlikely to change.
- Flag even **single-file app-identity literals** — app slug, app-owned meta-key, app `settings.yaml` key, URL fragment routed to the app — they encode a cross-app contract. Extract to a module-level constant.
- Don't flag test fixture values or Python builtins.
- **Field-name sets that mirror a model** — a module-level tuple/list/set of, or dict keyed by, a model's field-name string literals (`RENDERED_FIELDS = ("os_version", "config")`, or a dict keyed by `Capabilities` fields) duplicates the model, the single source of truth. Derive from `Model.model_fields` or hang a `ClassVar` on the model. Caveat: prefer a named allow-set over a blanket `frozenset(Model.model_fields) - {excluded}`, which silently absorbs every future field the model gains.

Concrete cases: `3306`/`5432` ports → `DEFAULT_MYSQL_PORT`/`DEFAULT_POSTGRESQL_PORT` in `app/inventory/constants.py`. Any hardcoded service-type string (`"mysql"`, `"postgresql"`, `"valkey"`, …) → `ServiceTypeEnum.<member>` (it's a `StrEnum` — the member *is* the string).

## DUP-2 — Hand-rolled where a helper exists

| Hand-rolled | Use instead |
|---|---|
| Module-level dict + `time.monotonic()` TTL | `@alru_cache(ttl=N)` / `@ttl_cache(ttl=N)` / `@lru_cache` |
| Raw `SELECT … FROM information_schema.columns` | `sqlalchemy.inspect(conn).get_columns(table)` |
| Dialect branches for idempotent INSERT | `app/core/db/utils.py::idempotent_insert()` |
| Dialect branches for JSON path extraction | `app/core/db/utils.py::func_json_extract()` |
| `SQLField(sa_column=Column(ForeignKey(...)))` | `SQLField(foreign_key=…, ondelete=…)` |
| Hardcoded `"MYSQL"`/`"POSTGRESQL"` | `ServiceTypeEnum.<member>.value` |
| New string/dict/date helper | Check `app/core/utils/` first |
| Raw `session.execute(select(...))` | `BaseSQLModelManager` methods |
| `session.exec(...)` inside a Manager classmethod body | `await cls._exec(session, query)` |
| `Manager.first(...)` then `if obj is None: raise HTTPNotFoundException(...)` | `Manager.get_or_404(session, **f)` |
| `Manager.first(...)` → `if existing: update() else: create()` | `Manager.get_or_create(session, data, filter_include={...})` |
| Inline `datetime.now(UTC)` / `datetime.utcnow()` timestamp | `utc_now()` from `app/core/utils/date_time` (microseconds zeroed) |
| `fastapi.HTTPException` | `HTTPNotFoundException` / `HTTPConflictException` / etc. |
| Inline `RemoteAPI` client | `Annotated[RemoteAPI, Depends(get_*_api)]` in `deps.py` |
| Manual JWT/auth | `CurrentUser = Annotated[User, IsAuthenticated]` |
| `len(v) > 0` `field_validator` | `NonEmptyStr` |
| `.strip().lower()` `field_validator` | `Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True)]` or `LowercaseStr` |

**Rule of thumb.** If a new decorator or class has 15+ lines of state management (timestamps, eviction, key hashing, TTL math), ask "why isn't this `@alru_cache` or `@ttl_cache`?" Flag as **Important**.

## DUP-3 — Idiom inconsistency

Compare each new pattern against the dominant form in sibling files in the same package. Non-dominant forms get **Minor** (or **Important** if divergence creates real maintenance burden). Carve-out: if siblings in the same subtree all use the non-dominant form, the local convention wins.

## DUP-4 — Sibling-route-body duplication

Before accepting a non-trivial block of new code, grep the package's route handlers for the same logic shape — DUP-2 misses this, since route bodies aren't in the helper catalog.

- **Same-package** — extract the duplicated logic into a `Depends()` or helper.
- **Cross-app** — if a route in app A processes a domain object owned by app B, prefer a classmethod on B's response model (`SnippetResponse.from_snippet(snippet)`) so consumers import and call it.

Don't flag trivial duplication or new code that legitimately needs a different shape.

## DUP-5 — Repeated call shape or boilerplate block

- Same function call (name + overlapping kwargs) appearing ≥3 times in one file → extract a thin one-liner wrapper that names the intent (e.g. `hot_field(default)` for repeated `field_with_metadata(default, metadata={...})`).
- A verbatim multi-line setup/teardown block (≥3 lines, `try`/`finally`/`async with`) duplicated ≥2 times across sibling callers → extract a shared context manager or helper.

The wrapper must name the *intent*, not just collapse syntax — a 3-line helper saving 1 line per call with no clear name isn't worth it.

## DUP-6 — Reuse stops at the leading underscore

Before flagging "reuse the existing symbol," check for a `_` prefix. A `_`-prefixed module member is not public — importing it across module boundaries couples the importer to an internal the owner can rename or delete without notice. Fix: define a trivial literal locally, or promote the symbol to public (drop `_`, add to `__all__`) in the owning module and import that. Applies to tests too (they're `SLF001`-exempt, so nothing mechanical catches it).

## DUP-7 — Conformance checks derive their expectation from the verified source

When a diff adds a consistency/conformance check, the expected value must be *derived from* the production function or constant being verified (called, imported, computed) — never re-typed as an independent copy. A re-typed expectation drifts from the code silently and defeats the check.

## DUP-8 — Unit label agrees with the factor and the documented contract

When a value is shown to a human with a unit — an error message, log line, validation failure, or UI string — the label, the conversion factor that produces the number, and the unit in the field's docstring / schema description must all agree. Binary-vs-decimal (KB/KiB, MB/MiB) and seconds-vs-milliseconds mismatches are the common, user-visible drift. Flag when the three diverge.

## Pydantic — declarative over imperative

- Prefer custom field types and `StringConstraints` over `field_validator`.
- Prefer `@computed_field` over externally-set derived fields.
- Use `BaseModel` for containers that accept >1 input shape and must normalise (a `model_validator(mode="before")`) or have derived fields. Plain value bags stay as `NamedTuple`/`@dataclass`.
- When adding a `@dataclass` into a module with existing dataclasses, match the dominant flags (`slots=True`, `frozen=True`, `kw_only=True`).
