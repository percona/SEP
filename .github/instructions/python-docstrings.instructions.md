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
- **Leading adverb** — `Recursively build …` / `Lazily load …` → `Build … recursively` / `Load … lazily`; the imperative verb must be the literal first word.

The mood rule applies in full to test functions too — the `tests/` carve-out governs whether a docstring is *required* and its `:param:` coverage, not its mood. A test docstring that exists opens in imperative mood.

**Touch = Sweep.** When a commit edits a docstring, sweep it in the same commit: (1) the first line for imperative mood — a fix that walks past a noun-phrase opening ratifies it with fresh provenance; (2) a touched `:param:` block for exactly-once coverage of every parameter (no missing, no duplicate); (3) touched `:param:` / `:return:` bodies for out-of-scope content (back-compat notes, caller rationale, history) — strip it; (4) a commit that adds a tested symbol or import widens the module docstring's scope claim.

## Inline literals — double backticks

Use `` ``None`` ``, not `` `None` `` or `"None"`. Single backticks render as italics; plain double-quotes as English — only double backticks produce a code mark.

## Parameter coverage; type directives are optional

When a docstring exists, every parameter other than `self`/`cls` needs a `:param:` block. A summary + `:return:` with no `:param:` entries is **incomplete** — route handlers documenting only the return value while leaving `session`, `request`, and dep-injected aliases undocumented are the predominant failure mode.

The signature's annotation is the source of truth for types, so `:type:` / `:rtype:` are **optional** — default to omitting them, and do **not** flag a `:param:` / `:return:` for lacking one. Add a type directive only when the documented type should intentionally differ from, clarify, or compensate for the annotation (an `Any` whose real contract is narrower, a noisy `Callable[...]` alias better stated in prose, a postponed / `TYPE_CHECKING` import the docs build can't resolve). When a type directive *is* present, it must use the right tag: `:type:` belongs to `:param:` only; `:cvar:` / `:ivar:` use `:vartype:`; use `:rtype:` only alongside `:return:`.

## Pydantic / SQLModel fields

Model fields are constructor parameters — document with `:param:`, NOT `:cvar:`. The field annotation supplies the type, so a `:type:` is optional. Applies to every `BaseModel` / `SQLModel` subclass. Only `ClassVar`-annotated fields use `:cvar:`; `:type:` is reserved for `:param:`, and a class variable that documents its type uses `:vartype:`. The same rule applies to `@dataclass` (including `frozen=True` / `slots=True`): annotated fields are constructor parameters — use `:param:`, never `:ivar:` / `:cvar:` (those are reserved for true `ClassVar`s or `__post_init__`-assigned attributes).

**Document the serialized default, not the internal constant.** For API-facing model fields, the documented default is the **wire value** a client sends or receives (`"ANY"`, `"nomad"`), never the internal Python symbol (`ANY_OWNER`, `Backend.NOMAD`) — model fields serialize into the OpenAPI schema and generated client SDKs, where the internal name is unresolvable.

## `:raises:` reflects what actually propagates

When a function re-raises from inner calls — async HTTP (`aiohttp.ClientError`, `asyncio.TimeoutError`), DB (`sqlalchemy.exc.*`), subprocess — `:raises:` must enumerate the families that propagate. Conversely, a function with `try/except` around an inner call does NOT propagate the caught families — trace the actual control flow: a family caught by a `try/except` lexically inside the body is OUT; anything executing outside those handlers (before the first `try`, in an `else:`, after a re-raise, in an unwrapped helper call) is IN. Omit `:raises:` entirely when the function propagates nothing (no `raise`, no throwing inner call). `:raises Exception:` is acceptable when enumeration is impractical PROVIDED the prose names the propagating families.

## Generators document `:yield:`, not `:return:`

A generator (sync or async, including `async def` async generators) documents the produced value with `:yield:` — its actual return value is `None`. Any `:rtype:` must be `Generator[...]` / `AsyncGenerator[...]`, never the yielded element type.

## Synchronise with behaviour changes

When a PR changes a function's behaviour — new code path, changed return-value semantics, new exception family, gained/lost parameter — the summary and the relevant `:return:` / `:raises:` / `:param:` blocks MUST be updated. A summary that still reads correctly about the *original* happy path is **incomplete**, not minimal.

## Don't overstate the contract

A docstring describes what the function/class *actually* does — neither narrower nor broader:

- **Overstated guarantee** — promises an outcome the implementation doesn't enforce (e.g. "raises `AttributeError` for unknown keys" when the code returns a sentinel). REWRITE.
- **Overstated coverage** — module docstring lists call-shapes the tests don't use. REWRITE per the actual call shape.
- **Oversold framing** — defensive measure framed as a stronger guarantee than it provides (e.g. "defends against tampering via a denylist" running on dev-authored input). SOFTEN or REMOVE.
- **Overstated runtime/lifecycle guarantee** — framing concurrency/shutdown behaviour as stronger than the code provides (*drains*, *completes cleanly*, *graceful*, *atomic*, *fail-fast* when the code just tears down). SOFTEN.
- **Overstated constraint scope** — a field description or help text paraphrasing a validation rule over a broader set than the validator gates. REWRITE with the exact fields; the same correction is owed on every copy surface (Pydantic `Field(description=...)`, React `FormField`, Jinja tooltip).
- **Misattributed condition** — the docstring ties a value to the wrong cause. REWRITE to name the actual governing condition.

## Don't understate the contract

The reverse of overstating: when a docstring uses applicability language (`Use when…`, `For the case where…`, `Use under…`), it must name **every** supported case — walk from the range the implementation actually accepts back to the prose. An explicit restriction (`only supported with a nested parent; top-level use is undefined`) is a valid, relied-upon contract; silence about a supported case reads identically to an oversight and makes the symbol undiscoverable.

## Name what the reader can't see

- **Load-bearing remote invariants** — when an object's correctness depends on a call at a remote site (a lifespan hook, a periodic task maintaining a denormalized field, a registration site, an event listener, a guard with a non-obvious secondary purpose), name that dependency in the class/object docstring or an adjacent comment. Reviewer prompt: is this object's correctness predicated on a call I can't see from here, and is that call named?
- **Describe intent, not a code-controlled enumeration** — a docstring listing the members of a set the code controls (a `parametrize` list, a module constant, registry entries) goes stale the moment the set changes. Name the intent and the controlling symbol ("every app in `BESPOKE_BASE_APP_PLUGINS`"), not the members. Applies in `tests/` too.
- **Framework/core symbols stay app-agnostic** — a shared framework/core symbol's docstring describes its behaviour in generic terms; naming one downstream app's domain concept (`backup_type`, `snippet_filename`) couples the abstraction's contract to one consumer. Restate as the generic role.

## Not required / out of scope

Skip docstrings on: `__init__`, dunder methods, public nested classes, `__init__.py` modules (`D104`–`D107` disabled), trivial self-documenting methods, test functions.

Out of scope (belong in PR / commit / ticket): ticket refs (`SEP-XXXX`), PR numbers, "added for the Y flow", caller lists ("used by `handle_foo()`" — the reader can grep), file:line cross-refs (line numbers go stale — name the symbol), implementation mechanics / internal how-it-works (state the contract; a maintainer reads the body for the mechanism), changelog-style "now supports X since vY" notes, internal review-standards or process-doc citations (inline the rationale, cite the ticket instead of the doc), and undefined internal jargon ("Layer 2 spine" — name the concrete class or drop it).
