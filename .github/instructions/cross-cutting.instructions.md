---
applyTo: "app/core/**/*.py,app/sep/deps.py,app/inventory/deps.py,app/tasks/deps.py,app/sep/plugins/shared/**/*.py"
---

# Cross-Cutting Changes — Shared Helpers & Side Effects

Diffs to these paths fan out across all three sub-applications. The bug class this file targets is a change that **passes its own tests** but breaks a caller elsewhere because the new behaviour wasn't audited against every call site.

## Shared-helper changes — audit every caller

When a PR touches `app/core/**`, `app/<service>/deps.py`, `app/sep/plugins/shared/**`, or a base class in `*/models.py` / `*/crud.py` whose subclasses live in multiple packages, the PR description should enumerate every call site and explain how the new behaviour preserves each caller's contract.

Specifically:

- **Signature changes** — every caller must be updated; per-caller justification when defaults or arg types change.
- **Emitted SQL changes** — when a DB helper changes its compiled SQL, callers using column types the new SQL doesn't handle fail at runtime, not compile time. Verify each caller's column types.
- **Return-shape changes** — adding/removing/reordering tuple elements, list → iterator, `None` → sentinel breaks every caller that destructures or matches the old shape.
- **Side-effect changes** — a helper that gained or lost an emit silently rewires every caller.

Flag any diff to these paths that lacks a caller audit. Canonical incident: a `func_json_extract` rewrite framed as a "no-op simplification" broke one caller whose column type the new form didn't support.

## Side-effect coverage on state-field writers

When a diff hooks a side-effect (`schedule_annotation`, `audit.log`, `metrics.emit`, `notify_*`, `alert_*`, `webhook.fire`) into a function that **observes** a state field — a polling loop, a `sync_*` method, an `on_change` handler — the diff is incomplete unless **every other writer to that state field in the same module** also routes through the side-effect.

Failure mode: hooking the side-effect into one observer and missing a parallel write site that mutates the field directly. The missing-behaviour bug doesn't show up in the diff scan — no added/changed line exists on the missing path.

To check:

1. Identify the **state field** the side-effect is keyed on (e.g. `queue_item.status`, `alert.acknowledged`).
2. Grep every writer (`<field> =`) in the affected file and sibling files in the same plugin/service.
3. For each match, ask: does this writer eventually trigger the side-effect? Writers that call the observer the new hook lives in inherit the side-effect. Writers that bypass it silently drop the side-effect — flag as **Critical**.
4. When the field has more than ~3 writers and the side-effect is hooked at only one observer, recommend moving the side-effect to the manager `save()` layer or a SQLAlchemy event listener — only that guarantees coverage on every writer.

## Dependency aliases live in `deps.py`

`Annotated[..., Depends(...)]` aliases MUST live in `app/<service>/deps.py` (or plugin `deps.py`), never in `routes.py`, `models.py`, or `loader.py`. When a dep helper exists (`get_pmm_api`, `get_or_create_alert_folder`), routes and tasks MUST use it — don't construct clients or do lookups inline.

## When to extract a dependency

A route handler should receive **prepared** objects via `Depends(...)` and do only HTTP-layer work. Extract when the body opens with a multi-step lookup / fetch / validation block. Extract feature-flag / config-gate guards (`if not <settings>.<FLAG>: raise HTTPForbiddenException(...)`) even at 2-3 lines — they belong in the route signature for OpenAPI visibility and reuse. Don't extract single attribute accesses, response construction, or endpoint-specific error formatting.

For each opening block in a new route handler, ask "could this object have arrived via `Depends`?" If yes and the block is more than 1–2 lines, flag. Guards are exempt from the line-count threshold.
