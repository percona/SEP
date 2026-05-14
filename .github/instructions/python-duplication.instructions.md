---
applyTo: "**/*.py"
---

# Python — Duplication & Existing-Pattern Reuse

The most common LLM-review failure is approving correct-but-reinvented code. Before accepting any new helper, constant, decorator, or pattern, check whether the codebase already has it.

## DUP-1 — Duplicated literals

Same string or numeric literal appearing in 2+ files in the diff (or 1 in the diff plus 1+ in `main`) MUST be a named constant.

- **Important** if the literal appears in 3+ files, if changing it would require touching every occurrence, or if it encodes a convention (port, key, format string).
- **Minor** if it appears in 2 files and is unlikely to change.
- Flag even **single-file plugin-identity literals** — plugin slug, plugin-owned meta-key, plugin `settings.yaml` key, URL fragment routed to the plugin — they encode a cross-plugin contract. Extract to a module-level constant.
- Don't flag test fixture values or Python builtins.

Concrete cases: `3306`/`5432` ports → `DEFAULT_MYSQL_PORT`/`DEFAULT_POSTGRESQL_PORT` in `app/inventory/constants.py`. `"MYSQL"`/`"POSTGRESQL"` → `ServiceTypeEnum.MYSQL.value`.

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
- **Cross-plugin** — if a route in plugin A processes a domain object owned by plugin B, prefer a classmethod on B's response model (`SnippetResponse.from_snippet(snippet)`) so consumers import and call it.

Don't flag trivial duplication or new code that legitimately needs a different shape.

## Pydantic — declarative over imperative

- Prefer custom field types and `StringConstraints` over `field_validator`.
- Prefer `@computed_field` over externally-set derived fields.
- Use `BaseModel` for containers that accept >1 input shape and must normalise (a `model_validator(mode="before")`) or have derived fields. Plain value bags stay as `NamedTuple`/`@dataclass`.
- When adding a `@dataclass` into a module with existing dataclasses, match the dominant flags (`slots=True`, `frozen=True`, `kw_only=True`).
