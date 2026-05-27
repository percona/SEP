---
applyTo: "**/*.py"
---

# Python — Docstrings (reStructuredText / Sphinx)

These mechanical checks catch a class of gap that ruff `D` rules miss.

## First line — imperative mood (MANDATORY)

The first word of every function, method, **and class** docstring must be a base-form English verb (`Return`, `Raise`, `Create`, `Validate`, `Represent`, `Describe`, `Carry`). Failure modes:

- **Third-person verb forms** — `Returns …` / `Creates …` / `Validates …` → `Return …` / `Create …` / `Validate …`.
- **Adjective / noun-phrase openings** (predominant miss on Pydantic / SQLModel class docstrings) — `Successful response for X.` → `Represent a successful response for X.`. Hyphenated compound modifiers (`Best-effort …`, `Read-only …`) and participial phrases (`Returning …`, `Computing …`) count as adjective phrases — rewrite as imperative verbs.
- **"When …" / "This …" openings** — describe the function instead of stating its action.

**Touch = Sweep.** When a commit edits a docstring body, audit the first line for imperative-mood compliance in the same commit — a fix that walks past a noun-phrase opening ratifies the violation with fresh provenance.

## Inline literals — double backticks

Use `` ``None`` ``, not `` `None` `` or `"None"`. Single backticks render as italics; plain double-quotes as English — only double backticks produce a code mark.

## Parameter coverage and pairing

When a docstring exists, every parameter other than `self`/`cls` needs a `:param:` block. A summary + `:return:` with no `:param:` entries is **incomplete** — route handlers documenting only the return value while leaving `session`, `request`, and dep-injected aliases undocumented are the predominant failure mode.

Every `:return:` MUST have a matching `:rtype:`. Flag a missing `:type X:` only when the type is **not** obvious from the signature (`Any`, generic `TypeVar`, `dict[str, Any]` whose runtime shape matters).

## Pydantic / SQLModel fields

Model fields are constructor parameters — document with `:param:` / `:type:`, NOT `:cvar:` / `:vartype:`. Applies to every `BaseModel` / `SQLModel` subclass. Only `ClassVar`-annotated fields use `:cvar:` + `:vartype:`; `:type:` is reserved for `:param:`.

## `:raises:` reflects what actually propagates

When a function re-raises from inner calls — async HTTP (`aiohttp.ClientError`, `asyncio.TimeoutError`), DB (`sqlalchemy.exc.*`), subprocess — `:raises:` must enumerate the families that propagate. Conversely, a function with `try/except` around an inner call does NOT propagate the caught families — trace the actual control flow. `:raises Exception:` is acceptable when enumeration is impractical PROVIDED the prose names the propagating families.

## Synchronise with behaviour changes

When a PR changes a function's behaviour — new code path, changed return-value semantics, new exception family, gained/lost parameter — the summary and the relevant `:return:` / `:raises:` / `:param:` blocks MUST be updated. A summary that still reads correctly about the *original* happy path is **incomplete**, not minimal.

## Don't overstate the contract

A docstring describes what the function/class *actually* does — neither narrower nor broader:

- **Overstated guarantee** — promises an outcome the implementation doesn't enforce (e.g. "raises `AttributeError` for unknown keys" when the code returns a sentinel). REWRITE.
- **Overstated coverage** — module docstring lists call-shapes the tests don't use. REWRITE per the actual call shape.
- **Oversold framing** — defensive measure framed as a stronger guarantee than it provides (e.g. "defends against tampering via a denylist" running on dev-authored input). SOFTEN or REMOVE.

## Not required / out of scope

Skip docstrings on: `__init__`, dunder methods, nested classes, `__init__.py` modules (`D104`–`D107` disabled), trivial self-documenting methods, test functions.

Out of scope (belong in PR / commit / ticket): ticket refs (`SEP-XXXX`), PR numbers, "added for the Y flow", caller lists ("used by `handle_foo()`" — the reader can grep), file:line cross-refs (line numbers go stale — name the symbol).
