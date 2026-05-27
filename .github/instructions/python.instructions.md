---
applyTo: "**/*.py"
---

# Python — Types, Imports, Style

Pre-commit runs ruff (lint + format), bandit, and addlicense. Don't flag what these catch: import sorting, quoting, line endings, trailing whitespace, ERA001 commented-out code, generic Bandit findings, license headers. Flag manual-judgment items only.

## Type annotations

- Annotate function parameters, return types, and class-level attributes. The codebase prefers no annotations on local variables, loop variables, or comprehension targets — ruff has `ANN0`/`ANN2` on but `ANN1` off. Don't flag a local annotation by itself; only flag obviously-redundant ones (e.g. `result: dict[str, int] = {}` where the return type already declares it, or `items: list[str] = []` followed by appends of literal strings). When the annotation disambiguates an inferred-wrong type for the IDE or type checker, leave it alone.
- Modern syntax only: `str | None` not `Optional[str]`; `list[str]` not `List[str]`. Target is Python 3.11+.
- Pick the **weakest** abstract type that captures every operation the body performs. If the body only iterates or does `x in xs` membership, prefer `Iterable[T]` over `Sequence[T]` over `list[T]`. Use `list[T]` when the body mutates, indexes, calls `len()`, or iterates more than once. Use `set[T]` over `UniqueList[T]` when order is irrelevant.
- When two parameters fill the same semantic role (within or across functions), annotate with the **same** breadth. Asymmetry like `list[str]` next to `Sequence[str]` — when neither body mutates — should be flagged.
- Avoid `Any` for parameters the library documents concretely: use `Dialect`, `TypeEngine[T]`, `Table`, `AsyncIterator[T]`, a `TypedDict` subclass for known dict shapes, or a concrete model instead of `Any`. Reserve `Any` for genuinely dynamic input.
- NEVER wrap custom field types in `str()`. `StrHttpUrl`, `NonEmptyStr`, `LowercaseStr`, `URIPath`, `UTCDatetime` (in `app/core/utils/fields.py`) are already typed subclasses.

## Imports & suppressions

- Top-level imports only. Inline imports inside function bodies are acceptable ONLY with a verified circular-import justification in the PR description.
- No new `# noqa:` or `# type: ignore:` unless the PR explains why fixing the root cause is impossible. The only standing accepted suppression is `# noqa: ARG002` for unused parameters on parent-class overrides — keep the original parameter name (don't rename to `_param`). Treat `# noqa: TD002, TD003` paired with a malformed TODO as a standards bypass. Required TODO format: `# TODO(<owner>): <description>` then `# <ticket-key>`.

## Style

- **Boolean trap**: `process_data(data, True)` is opaque. Require keyword `validate=True`.
- **Sentinel anti-pattern**: don't write `result = None; try/except; if result is None` — use `try/except/else`.
- **Single-use locals**: inline unless the name documents non-obvious intent, the branch body is ≥10 lines, or the expression has a side effect.
- **Merge boolean-branch returns**: two `if cond: return X` with the same `X` collapse to `if a or b: return X`, unless branches have side effects.
- **Redundant construction**: when the same constructor call returns the same value on every path, extract it once at the top.
- **Collapse trivial guards**: ≤2 cheap preconditions guarding a single-statement body → one positive `if a and b:` over a chain of `if not x: return` guards.
- **Prefer positive form** for a single negated guard whose body is one bare `continue`/`return`/`raise`.
- **Numeric literals**: drop trailing zeros on floats — `0.1` not `0.10`.
- **Empty modules**: if a refactor empties a file, delete it.
- **Comments**: flag NEW inline comments that don't document a non-obvious invariant or workaround.
- **No magic HTTP integers**: `status.HTTP_404_NOT_FOUND`, not `404`.
- **Custom exceptions**: raise `HTTPNotFoundException` / `HTTPConflictException` / `HTTPForbiddenException`, not `fastapi.HTTPException`.
- **Pydantic / SQLModel class body order**: `model_config` first, then fields, then `@field_validator` / `@model_validator`, then methods (`@computed_field` properties before regular methods). `model_config` placed below the fields hides it from a reader scanning the top of the class.
