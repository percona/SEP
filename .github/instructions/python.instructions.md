---
applyTo: "**/*.py"
---

# Python — Types, Imports, Style

Pre-commit runs ruff (lint + format), bandit, and addlicense. Don't flag what these catch: import sorting, quoting, line endings, trailing whitespace, ERA001 commented-out code, generic Bandit findings, license headers. Flag manual-judgment items only.

## Type annotations

- Annotate function parameters, return types, and class-level attributes. Local-variable annotations aren't required (ruff has `ANN0`/`ANN2` on but `ANN1` off), and loop variables and comprehension targets are never annotated. Don't flag a local annotation by itself; flag only ones that merely restate a type the assignment already makes obvious (e.g. `count: int = len(items)`, `name: str = "done"`). Leave an annotation alone when it carries type information inference can't: an empty collection (`items: list[str] = []`), an optional initialized to `None` (`x: Foo | None = None`), or an ambiguous/`Any` return (`payload: dict[str, Any] = response.json()`).
- Modern syntax only: `str | None` not `Optional[str]`; `list[str]` not `List[str]`. Target is Python 3.11+.
- Pick the **weakest** abstract type that captures every operation the body performs. If the body only iterates or does `x in xs` membership, prefer `Iterable[T]` over `Sequence[T]` over `list[T]`. Use `list[T]` when the body mutates, indexes, calls `len()`, or iterates more than once. Use `set[T]` over `UniqueList[T]` when order is irrelevant.
- When two parameters fill the same semantic role (within or across functions), annotate with the **same** breadth. Asymmetry like `list[str]` next to `Sequence[str]` — when neither body mutates — should be flagged.
- Avoid `Any` for parameters the library documents concretely: use `Dialect`, `TypeEngine[T]`, `Table`, `AsyncIterator[T]`, a `TypedDict` subclass for known dict shapes, or a concrete model instead of `Any`. Reserve `Any` for genuinely dynamic input.
- NEVER wrap custom field types in `str()`. `StrHttpUrl`, `NonEmptyStr`, `LowercaseStr`, `URIPath`, `UTCDatetime` (and the other subclasses in `app/core/utils/fields.py`) are already typed — the rule applies to any of them, not just these five.
- **Bare generic containers** erase the element contract — `dict`/`list`/`set`/`tuple`/`frozenset` with no type args is `[Any]`. Supply concrete args; only genuinely heterogeneous content may use `dict[str, Any]` / `list[Any]`.
- **`type[X]` bound** must be the tightest common base of the expected callers; bare `type` (= `type[object]`) is always wrong. When the base can't be imported at runtime, annotate under `TYPE_CHECKING`.
- **Callable return signatures**: a factory returning a callable with a fixed signature spells the parameter list — `Callable[[str, TaskAPI], Awaitable[Task]]`, not `Callable[..., Awaitable[Task]]`. Reserve `...` for genuinely varying signatures.
- **Over-nullable fields**: an `X | None` field whose `after`-validator unconditionally fills it from a non-optional sibling is a defaulting artifact — move the default to a `before`-validator and type the field non-optional. Keep `| None` only when `None` is a legitimate post-construction value.
- **Wire format ≠ field type**: a response/wrapper model field projecting from a canonical sibling (`BaseSQLModel`, an upstream response) mirrors the source's field type (`UTCDatetime`, `NonEmptyStr`, an `Enum` subclass), not the JSON wire type (`str`, `list[str]`).

## Imports & suppressions

- Top-level imports only. Inline imports inside function bodies are acceptable ONLY with a one-line comment adjacent to the import (not in the docstring, not only in the PR description) naming the cycle it breaks.
- No new `# noqa:` or `# type: ignore:` unless the PR explains why fixing the root cause is impossible. The only standing accepted suppression is `# noqa: ARG002` for unused parameters on parent-class overrides — keep the original parameter name (don't rename to `_param`). Treat an author-less `# TODO` with `# noqa: TD002, TD003` as a standards bypass — name an owner. Required TODO format: `# TODO(<owner>): <description>`; don't add a `# <ticket-key>` line — Jira keys never go in comments (see below), so suppressing the missing-link rule (TD003) is the accepted path and the ticket reference lives in the PR.
- **`per-file-ignores`**: a `[tool.ruff.lint.per-file-ignores]` entry keyed on a bare filename (`"contract_suite.py"`) is a basename glob matching every file of that name in the tree — anchor it to the full repo-relative path, or use an inline `# noqa` for specific lines. `exclude` / `extend-exclude` removes the file from all linting *and* formatting — never a bare basename there.

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
- **Comments**: flag NEW inline comments that don't document a non-obvious invariant or workaround; a verbose-but-justified comment is a *tighten* signal (condense to the core *why*), not a delete. Never put a Jira key (`SEP-\d+`) or `fixes #N` in an inline comment (any syntax — Python `#`, Jinja `{# #}`, HTML, JS) — that rationale belongs in the PR/ticket.
- **No magic HTTP integers**: `status.HTTP_404_NOT_FOUND`, not `404` — imported from `fastapi`, not `starlette` (`from fastapi import status`).
- **Custom exceptions**: raise `HTTPNotFoundException` / `HTTPConflictException` / `HTTPForbiddenException`, not `fastapi.HTTPException`.
- **Pydantic / SQLModel class body order**: `model_config` first, then fields, then `@field_validator` / `@model_validator`, then methods (`@computed_field` properties before regular methods). `model_config` placed below the fields hides it from a reader scanning the top of the class.
- **Raw-string prefix**: use `r` / `rb` only when the body contains a literal backslash escape; an `r` prefix on a string with no backslash is misleading noise.
- **Literal-True ternary**: `True if cond else X` → `cond or X`; `False if cond else X` → `not cond and X` — only when `cond` is already boolean-typed (comparison, `isinstance`, membership).
- **None-first ternary**: `value if x is not None else None` → `None if x is None else value` (don't introduce a `not` just to satisfy this).
- **Stub ellipsis**: a `Protocol` method / `@overload` / abstract stub that already has a docstring must not also carry a trailing `...` — the docstring is the body (ruff `PIE790` skips these contexts).
- **Buffer scanning**: flag a Python `for`-loop scanning a byte/string buffer when a C-level builtin (`.count()`, `.find()`, `.split()`, `.translate()`) expresses the same operation — relevant on potentially large buffers (log chunks, file reads, upload bodies).
