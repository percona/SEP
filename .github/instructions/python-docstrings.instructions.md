---
applyTo: "**/*.py"
---

# Python — Docstrings (reStructuredText / Sphinx)

These mechanical checks catch a class of gap that ruff `D` rules miss. A non-trivial PR touching public Python should rarely return zero findings here.

## First line — imperative mood (MANDATORY)

The first word of every function, method, **and class** docstring must be a base-form English verb (`Return`, `Raise`, `Create`, `Validate`, `Represent`, `Describe`, `Carry`, `Provide`, `Yield`). Three failure modes:

- **Third-person verb forms** — `Returns the user's name.` / `Creates a backup.` / `Validates input.` → `Return …` / `Create …` / `Validate …`.
- **Adjective or noun-phrase openings** (predominant miss on Pydantic / SQLModel class docstrings) — `Successful response for the manual refresh endpoint.` → `Represent a successful refresh response.`; `Per-deployment capability flags.` → `Describe per-deployment capability flags.`; `API payload describing X.` → `Carry the API payload for X.`.
- **"When …" / "This …" openings** — they describe the function instead of stating its action.

## Inline literals — double backticks

Use `` ``None`` ``, not `` `None` ``. Single backticks render as italics in Sphinx; double backticks render as code.

## Parameter coverage and pairing

When a docstring exists, every parameter other than `self`/`cls` needs a `:param:` block. A docstring with a summary and `:return:` but no `:param:` entries is **incomplete**, not minimal — route handlers documenting only the return value while leaving `session`, `request`, and dep-injected aliases undocumented are the predominant failure mode.

Every `:return:` MUST have a matching `:rtype:`. `:type X:` is recommended for every `:param X:`, but flag a missing `:type:` only when the parameter's type is **not** obvious from the signature (e.g. a parameter annotated as `Any`, a generic `TypeVar`, a `dict[str, Any]` whose runtime shape matters, or a free-function parameter with no annotation). When the signature already documents `name: str | None = None`, an absent `:type name: str | None` is fine.

```python
def create_node(name: str, address: str | None = None) -> Node:
    """Create a new node in the inventory.

    :param name: The node's display name.
    :type name: str
    :param address: The node's network address.
    :type address: str | None
    :return: The newly created node.
    :rtype: Node
    """
```

## Pydantic / SQLModel field documentation

Model fields are constructor parameters — document with `:param:` / `:type:`, NOT `:cvar:` / `:vartype:`. Applies to every `BaseModel` / `SQLModel` subclass, even though fields are written in the class body — they behave as `__init__` parameters.

Only fields annotated as `ClassVar` are true class variables and use `:cvar:` / `:vartype:`. Class variables use `:cvar X:` + `:vartype X:` — NEVER `:type X:`. `:type:` is reserved for `:param:`. Instance variables use `:ivar X:` + `:vartype X:`.

## `:raises:` reflects what actually propagates

When a function re-raises from inner calls — async HTTP (`aiohttp.ClientError`, `asyncio.TimeoutError`), DB (`sqlalchemy.exc.*`), subprocess — `:raises:` must enumerate the families that **propagate**, not just exceptions the function itself raises explicitly.

If enumerating every concrete class is impractical, `:raises Exception:` is acceptable PROVIDED the prose names the propagating families. Functions with no `raise` and no inner calls that can throw omit `:raises:`.

## When docstrings are NOT required

`__init__`, dunder methods, nested classes, `__init__.py` modules (`D104`–`D107` disabled). Trivial methods whose name is self-documenting. Test functions (`test_*.py`).

## Out of scope for docstrings

Move to PR description / commit message / linked ticket: ticket references (`SEP-XXXX`), PR numbers, changelog notes, "added for the Y flow", caller lists ("used by `handle_foo()`" — the reader can grep).
