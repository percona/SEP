---
applyTo: "**/*.py"
---

# Python — Docstrings (reStructuredText / Sphinx)

These mechanical checks catch a class of gap that ruff `D` rules miss.

**Python only.** The rST directives, the double-backtick rule, and the imperative-mood rule below describe `app/` and `tests/`. TypeScript and TSX under `frontend/` use **JSDoc** — prose, single backticks, no rST directives. `:param:` / `:return:` / double backticks in a `.ts` file produce doc comments no TS tooling renders; match the nearest sibling modules in the same package instead.

## First line — imperative mood (MANDATORY)

The first word of every function, method, **and class** docstring must be a base-form English verb (`Return`, `Raise`, `Create`, `Validate`, `Represent`, `Describe`, `Carry`). Failure modes:

- **Third-person verb forms** — `Returns …` / `Creates …` / `Validates …` → `Return …` / `Create …` / `Validate …`.
- **Adjective / noun-phrase openings** (predominant miss on Pydantic / SQLModel class docstrings) — `Successful response for X.` → `Represent a successful response for X.`. Hyphenated compound modifiers (`Best-effort …`, `Read-only …`) and participial phrases (`Returning …`, `Computing …`) count as adjective phrases — rewrite as imperative verbs.
- **"When …" / "This …" openings** — describe the function instead of stating its action.
- **Leading adverb** — `Recursively build …` / `Lazily load …` → `Build … recursively` / `Load … lazily`; the imperative verb must be the literal first word.

The mood rule applies in full to test functions too — the `tests/` carve-out governs whether a docstring is *required* and its `:param:` coverage, not its mood. A test docstring that exists opens in imperative mood.

**Touch = Sweep.** When a commit edits a docstring, sweep it in the same commit: (1) the first line for imperative mood — a fix that walks past a noun-phrase opening ratifies it with fresh provenance; (2) a touched `:param:` block for exactly-once coverage of every parameter (no missing, no duplicate); (3) touched `:param:` / `:return:` bodies for out-of-scope content (back-compat notes, caller rationale, history) — strip it; (4) a commit that adds a tested symbol or import widens the module docstring's scope claim; (5) **re-wrap the paragraph** — nothing reflows docstring prose (`ruff format` leaves paragraph fill alone), so substituting a shorter or longer phrase owes the paragraph a re-wrap or it leaves a ragged short line mid-paragraph.

Two further sweeps fire on things the diff *removed* or *contradicted*, not on what it added:

- **Removal.** When a commit deletes an import, moves a helper to a shared module, or replaces an inline implementation with a delegated call, re-read the losing module's docstrings for prose still attributing the removed mechanism to *this* file. The losing module is the one that gets missed — attention is on the gaining module, and the stale prose can sit in a file whose diff is a pure deletion.
- **Correction.** When a commit corrects a fact the codebase asserts — a rename, a re-classification, a moved ownership boundary, an inverted default — grep the touched files for prose still asserting the old fact, *including prose outside the diff hunks*. "Pre-existing, out of scope" does not apply: the prose was true before the commit and is false after it. Ask **what did this change make untrue?** A **partial sweep is self-evidencing** — one corrected occurrence in a file is the cue to grep for the rest.

## Inline literals — double backticks

Use `` ``None`` ``, not `` `None` `` or `"None"`. Single backticks render as italics; plain double-quotes as English — only double backticks produce a code mark.

## Parameter coverage; type directives are optional

When a docstring exists, every parameter other than `self`/`cls` needs a `:param:` block. A summary + `:return:` with no `:param:` entries is **incomplete** — route handlers documenting only the return value while leaving `session`, `request`, and dep-injected aliases undocumented are the predominant failure mode.

The signature's annotation is the source of truth for types, so `:type:` / `:rtype:` are **optional** — default to omitting them, and do **not** flag a `:param:` / `:return:` for lacking one. Add a type directive only when the documented type should intentionally differ from, clarify, or compensate for the annotation (an `Any` whose real contract is narrower, a noisy `Callable[...]` alias better stated in prose, a postponed / `TYPE_CHECKING` import the docs build can't resolve). When a type directive *is* present, it must use the right tag: `:type:` belongs to `:param:` only; `:cvar:` / `:ivar:` use `:vartype:`; use `:rtype:` only alongside `:return:`.

## Pydantic / SQLModel fields

Model fields are constructor parameters — document with `:param:`, NOT `:cvar:`. The field annotation supplies the type, so a `:type:` is optional. Applies to every `BaseModel` / `SQLModel` subclass. Only fields genuinely wrapped in `ClassVar[...]` use `:cvar:` — those *are* class variables and keep it; `:type:` is reserved for `:param:`, and a class variable that documents its type uses `:vartype:`. The same rule applies to `@dataclass` (including `frozen=True` / `slots=True`): annotated fields are constructor parameters — use `:param:`, never `:ivar:` / `:cvar:` (those are reserved for true `ClassVar`s or `__post_init__`-assigned attributes).

**Document the serialized default, not the internal constant.** For API-facing model fields, the documented default is the **wire value** a client sends or receives (`"ANY"`, `"nomad"`), never the internal Python symbol (`ANY_OWNER`, `Backend.NOMAD`) — model fields serialize into the OpenAPI schema and generated client SDKs, where the internal name is unresolvable.

## `:raises:` reflects what actually propagates

When a function re-raises from inner calls — async HTTP (`aiohttp.ClientError`, `asyncio.TimeoutError`), DB (`sqlalchemy.exc.*`), subprocess — `:raises:` must enumerate the families that propagate. Conversely, a function with `try/except` around an inner call does NOT propagate the caught families — trace the actual control flow: a family caught by a `try/except` lexically inside the body is OUT; anything executing outside those handlers (before the first `try`, in an `else:`, after a re-raise, in an unwrapped helper call) is IN. Omit `:raises:` entirely when the function propagates nothing (no `raise`, no throwing inner call). `:raises Exception:` is acceptable when enumeration is impractical PROVIDED the prose names the propagating families.

**The rule covers prose, not just the `:raises:` field.** A summary ending "anything else propagates" is the same assertion and is checked the same way — and is the easier one to get wrong, since it's written before the `except` tuple is final and never revisited when the tuple grows. Two things falsify such a claim, and only the first is an exception: families the `except` tuple catches, *including ones reached indirectly* (`ValueError` covers `json.JSONDecodeError`; `UnicodeDecodeError` covers a bare `.decode()`); and **plain `return None` arms**, which are not exceptions at all and so never show up in a `:raises:` audit — an over-cap guard, a wrong-shape guard, or an empty-result guard each converts a failure into a benign value. A function swallowing that broadly is best described as **best-effort** with the full set listed.

When a docstring promises the function *never raises* and something propagates anyway, the defect is in the **code** — adding a `:raises:` entry resolves the inconsistency in the direction callers weren't built for.

## Generators document `:return:`

A generator (sync or async, including `async def` async generators) documents the produced value with **`:return:`**, not `:yield:`. Sphinx's Python domain defines no `yield` field — `PyObject.doc_field_types` carries `param` / `returns` / `rtype` / `raises` and nothing else — so `:yield:` renders as an *unstyled generic field*, defeating the Sphinx compatibility that mandates rST here in the first place. (A "Yields" section exists only under Napoleon's Google/NumPy styles, which this project doesn't use.) Describe the produced value in the `:return:` body; the summary line's `Yield …` opener already tells the reader it's a generator. Any `:rtype:` must be `Generator[...]` / `AsyncGenerator[...]`, never the yielded element type.

Spell it **`:return:`, singular** — `:returns:` is also valid rST but appears nowhere in this tree; keep it that way.

**Touch = Sweep.** A `:yield:` is a finding both when newly added **and** when it is pre-existing inside a docstring span the diff touched — so the tree converts incrementally. Untouched generators stay as they are; don't flag them.

## Synchronise with behaviour changes

When a PR changes a function's behaviour — new code path, changed return-value semantics, new exception family, gained/lost parameter — the summary and the relevant `:return:` / `:raises:` / `:param:` blocks MUST be updated. A summary that still reads correctly about the *original* happy path is **incomplete**, not minimal.

## Don't overstate the contract

A docstring describes what the function/class *actually* does — neither narrower nor broader:

- **Overstated guarantee** — promises an outcome the implementation doesn't enforce (e.g. "raises `AttributeError` for unknown keys" when the code returns a sentinel). REWRITE.
- **Overstated coverage** — module docstring lists call-shapes the tests don't use. REWRITE per the actual call shape.
- **Oversold framing** — defensive measure framed as a stronger guarantee than it provides (e.g. "defends against tampering via a denylist" running on dev-authored input). SOFTEN or REMOVE.
- **Overstated runtime/lifecycle guarantee** — framing concurrency/shutdown behaviour as stronger than the code provides (*drains*, *completes cleanly*, *graceful*, *atomic*, *fail-fast* when the code just tears down). SOFTEN.
- **Overstated constraint scope** — a field description or help text paraphrasing a validation rule over a broader set than the validator gates. REWRITE with the exact fields; the same correction is owed on every copy surface (Pydantic `Field(description=...)`, the app's `schema.py` help text, React `FormField`).
- **Misattributed condition** — the docstring ties a value to the wrong cause. REWRITE to name the actual governing condition.

## Don't understate the contract

The reverse of overstating: when a docstring uses applicability language (`Use when…`, `For the case where…`, `Use under…`), it must name **every** supported case — walk from the range the implementation actually accepts back to the prose. An explicit restriction (`only supported with a nested parent; top-level use is undefined`) is a valid, relied-upon contract; silence about a supported case reads identically to an oversight and makes the symbol undiscoverable.

## Name what the reader can't see

- **Load-bearing remote invariants** — when an object's correctness depends on a call at a remote site (a lifespan hook, a periodic task maintaining a denormalized field, a registration site, an event listener, a guard with a non-obvious secondary purpose), name that dependency in the class/object docstring or an adjacent comment. Reviewer prompt: is this object's correctness predicated on a call I can't see from here, and is that call named?
- **Describe intent, not a code-controlled enumeration** — a docstring listing the members of a set the code controls (a `parametrize` list, a module constant, registry entries) goes stale the moment the set changes. Name the intent and the controlling symbol ("every app in `BESPOKE_BASE_APP_PLUGINS`"), not the members. Applies in `tests/` too.
- **Framework/core symbols stay app-agnostic** — a shared framework/core symbol's docstring describes its behaviour in generic terms; naming one downstream app's domain concept (`backup_type`, `snippet_filename`) couples the abstraction's contract to one consumer. Restate as the generic role.
- **State the role; don't pin what the reader can grep.** Two shapes rot on the next change and are never edited at the change site: **a count** ("read by seven non-alerts apps", "the only two callers") and **an enumeration of callers or consumers**. Write the *property* instead — not "read by seven non-alerts apps" but "read by every app offering `alert_on_fail`"; not "used by `a.py`, `b.py`, `c.py`" but "shared across the subtree". When the enumeration is genuinely load-bearing, the enforcement belongs in code (a registry, an `__all__`, a guard), with the docstring pointing at it — prose is not a mechanism.
- **A parity claim is scoped to the members it covers.** "The expected row orders are the same literals `TestListQueryPaginatedPostgres` asserts" reads as a guarantee over the whole class; when it holds for only some members it is false for the rest and nothing marks which. Scope the assertion and name the exceptions ("…the all-NULL and `select_related` cases are MySQL-only"). Cross-dialect test classes are the recurring shape.

## Say it once, in the surface that owns it

A docstring states its own symbol's contract and does not restate what another surface already owns. A second copy has no reader of its own, drifts independently, and pads the docstring so the load-bearing parts get skimmed. Three shapes, in widening order:

| Shape | Fix |
|---|---|
| Restates its own adjacent clause — "`None`, the default, places no restriction. `None` leaves every deployment unrestricted." | Delete the echo. |
| Restates another module's canonical `:param:` block — a consuming module repeating what the settings class already documents | Delete the copy, keep the canonical. The `:param:` block is where a reader *configuring* the setting arrives. |
| Carries operator guidance a deployment doc owns — a "Choosing entries." paragraph advising how to pick an allowlist, inside an `app/core/` module docstring | Move it to the operator-facing doc (`sidecar/README.md`, deployment docs), which can name actual keys. |

The third is an **audience** error and the sibling of "framework/core symbols stay app-agnostic": that rule forbids naming a downstream consumer's domain concept, this one forbids addressing a downstream consumer's *human operator*.

## Prose register

Match the register of the surrounding code: state the contract, then stop. A docstring is reference text a reader lands on mid-task, not an explainer. Three drifts recur, none caught by lint, each individually defensible — which is why they accumulate across a PR until the module reads in a different voice from its neighbours. Audit register **across the whole diff at once**; a single instance rarely looks wrong.

- **Bold runs are not headings.** `**Precedence:** environment beats file. **Fallback:** the class default.` → `Environment beats file; absent both, the class default applies.` rST does render `**…**`, so it's valid — it just reads like a slide deck. A lead clause does the same work in the same characters.
- **`--` is not an em dash.** Two hyphens standing in for punctuation is a typewriter habit; most of the parentheticals it wraps are carried better by a comma or a full stop. Where the aside earns a dash, write the character.
- **Name the symbol, not an abstract actor.** "the deployment", "the system", "the caller" invent an agent the reader cannot grep. `Return keys the deployment permits overriding.` → ``Return the keys ``SETTINGS_OVERRIDE_ALLOWED_KEYS`` permits overriding.``

## Not required / out of scope

Skip docstrings on: `__init__`, dunder methods, public nested classes, `__init__.py` modules (`D104`–`D107` disabled), trivial self-documenting methods, test functions.

Out of scope (belong in PR / commit / ticket): ticket refs (`SEP-XXXX`), PR numbers, "added for the Y flow", caller lists (in **module** docstrings as well as function/class ones — "used by `handle_foo()`" (list shape), "only two callers are intended" (intent shape), "internal API for the X workflow" (named-workflow shape), "both `X` and `Y` share this helper" (shared-by shape, which reads as role description but pins the same list)), file:line cross-refs (line numbers go stale — name the symbol), implementation mechanics / internal how-it-works (state the contract; a maintainer reads the body for the mechanism), and changelog-style "now supports X since vY" notes.

Three more, each an **unreachable pointer** — a reference a reader of the shipped source cannot follow:

- **Internal review-standards / process-doc citations and prose pointers to planning artifacts** — "documented in the plan", "the plan's edge-case table", "per the design doc". Inline the *rationale itself*; any pointer, to the plan **or** the tracking ticket, belongs in the PR description.
- **A bare ordinal into a ticket's acceptance criteria** — "the criterion-7 rework", "(AC #3)", "Guard AC4". The easiest to miss because it names no artifact at all: it reads as a label rather than a cross-reference while resolving to strictly less than "the plan" does. Blocked on Touch = Sweep, in `tests/` too — the `tests/` relaxation governs whether a docstring is *required* and its mood, never whether it may cite an unreachable artifact.
- **Tracking directives that render** — `.. todo::`, `.. deprecated::` used as a reminder, any admonition whose body describes work not yet done. Delete it; the docstring carries the **current** contract. Worse than the prose form on two counts: Sphinx renders it as a visible admonition, so a docs reader is actively pointed at work they cannot look up, and a directive reads as sanctioned by the toolchain. A single instance is its own tell — a `.. todo::` that is the only one in `app/` and `tests/` is a leftover, not a convention.

Also out of scope: **any prose stand-in for a symbol that exists** — layer/tier numbering ("the Layer 2 spine"), internal codenames, pipeline-stage nicknames, **and personified actors** ("the deployment", "the operator", "the environment") standing in for the setting or constant that actually carries the behaviour. The personified variant is the commoner one and the harder to notice, because it's ordinary English rather than jargon: it reads as clear prose while naming nothing greppable, and it smuggles in a contrast between two actors where the code has one mechanism ("the code, rather than the deployment, refuses the override" invites a search for a deployment-side actor that doesn't exist). Name the symbol and the sentence collapses back into a fact.
