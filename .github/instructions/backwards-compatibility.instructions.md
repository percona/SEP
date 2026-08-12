---
applyTo: "app/**/models.py,app/**/schema.py,app/**/migrations/**/*.py,app/*/db/seed.py,app/sep/apps/**/api_routes.py,settings.yaml"
---

# Backwards Compatibility

SEP runs three API services (SEP, Inventory, Tasks) consumed by the web UI, CLI tools, and background executors. Changes to public contracts can break consumers silently.

## Released-ness is the precondition

Before flagging any break below, check whether the symbol's introducing PR is still inside the current `[Unreleased]` window (its changelog fragment sits unreleased in `changelog.d/`). A symbol that nothing has shipped a dependency on carries no backwards-compatibility obligation — do NOT demand a shim, alias, or two-phase migration for a field / enum / column / config key added earlier in the same unreleased cycle.

## API Response Shape (`*Response` models)

| Safe | Unsafe |
|------|--------|
| Add an **optional** field with a default | Remove or rename a field |
| Widen a type (`int` → `int \| None`) | Narrow a type (`str \| None` → `str`) |
| Add a new enum value to a response field | Change a field's type (`str` → `int`) |
| Add a new response model for a new endpoint | Add a **required** field to an existing response |

Renaming a field — even via `alias` — is breaking. Prefer deprecating: keep the old field, populate it, add the new alongside. Adding a required field to a `*Write` model is also breaking — add it optional with a default.

## Database Schema

The migration-then-deploy window means both old and new code may run against the migrated schema.

| Safe | Unsafe |
|------|--------|
| Add nullable column | NOT NULL without `server_default` |
| Add column with server default | Drop column still read by current release |
| Add new table | Rename column or table |
| Add index | Remove enum value from DB CHECK/ENUM |

Add NOT NULL with `server_default`, or add nullable first, backfill, tighten. Drop/rename in two phases: stop reading in code (deploy), then drop/rename. Removing an enum value from a `StrEnum` used in a DB column orphans rows — migrate first.

Retiring a previously-valid **constrained-vocabulary value** (a `StrEnum` member, a literal-set option, a `task.data["meta"]["args"]` arg, a JSON-config key) needs a one-shot data migration on the owning track. Remediating with in-place read-path coercion (`if value == "old": value = "new"` inside a parser/deserializer) is NOT equivalent — it accumulates unbounded legacy debt. Flag it.

## Enums

Members appear in API responses, DB columns, task payloads, and config. Removing a member breaks all of them. Renaming a member's **value** (string/int) equals removing the old + adding the new. New members are safe iff consumers handle unknown values gracefully — confirm.

## Config Keys (`settings.yaml` / env vars)

- Renaming a key breaks deployments setting the old key. Accept both old and new with a deprecation warning.
- Making an optional key required breaks deployments that omit it — provide a default.
- Changing a key's type (`str` → `list[str]`) breaks existing config files.

## Exception / Error Responses

- Changing an endpoint's error status code (404 → 410) breaks consumers matching on codes.
- Changing the error detail structure (`str` → `dict`) breaks consumers parsing it.
- Adding a new error case (a status code the endpoint didn't return before) is lower-risk but should still be documented.

## Task Payloads

Serialized at task creation, deserialized by executors — potentially on a different code version. Mismatch causes `TaskDataNotFoundInExecutorError`.

- Adding a required field breaks deserialization of already-queued tasks. Use optional fields with defaults.
- Removing a field is safe (Pydantic ignores extras) **unless** the executor reads it.
- Renaming breaks queued tasks and executors reading the old name.

## Seed Data (`app/*/db/seed.py`)

System and periodic tasks are seeded at startup via `get_or_create`. Orphaned periodic tasks matching the service prefix (`sep__`, `tasks__`) are deleted automatically by `init_periodic_tasks_db`.

- Renaming a system task's `name` creates a new entry and orphans the old — scheduled jobs or user periodic tasks referencing the old name break.
- Removing a seed entry deletes it on next startup. Dependent user-configured periodic tasks or Nomad jobs fail silently.
- Renaming a `meta` key in a Nomad job template breaks in-flight jobs dispatched with the old parameter names.
- Changing an `IntervalSchedule` value (30s → 5m) is safe — `get_or_create` updates it in place. Removing the schedule field entirely breaks the periodic task that references it.
- **Narrowing which rows a gating regime *owns* strands the state it already wrote.** The rules above cover orphaned rows breaking *references*; this one covers state surviving with no writer. When a change removes rows from the set some writer maintains — an ownership predicate, an orphan sweep, a `not_in(...)` filter — name what resets the state those rows still carry. `init_periodic_tasks_db` updates `task`, `schedule_model` and `extra_kwargs` on an existing row but **never** `enabled`, so a `PeriodicTask` leaving the owned set keeps whatever `enabled` value the old regime last wrote — permanently, and invisibly to the UI that would otherwise toggle it. Either write the released value through explicitly or state why the surviving value is already correct. Not in scope: rows nothing reads, newly added state, and in-place updates where the writer keeps ownership.

## Changing a settings field's shipped default

Flipping a default (or converting an opt-in to an opt-out) is a behaviour change for every deployment that never set the key. Check that the PR:

- **Enumerates every layer that resolves the value** and decides each — the field default, `settings.yaml`, the shipped profile, env. **The field default is the layer that ships**, not the repository default: a value the repo's own `settings.yaml` overrides is not what an operator running the image gets.
- **Reconciles the docstring in the same change** — the `:param X:` block is a copy surface for the default and goes stale silently.
- **Asserts the advertised default rather than assuming it**, and pins the resolved default per shipped profile with a test.
- **Gives operators an opt-in path back and a changelog note.** A default flip is user-visible even when no contract changed.

## Behavioral asymmetry across processes / deployments / install-states

A feature that behaves differently by process (API vs Celery worker), deployment, or install-state (fresh vs upgraded DB) is a silent-break risk even when no contract changed. Common shapes: HOT-reloaded settings, `server_default` backfill vs ORM default, feature flags, router-level gates, SQLAlchemy event listeners that only fire in the process that registered them. Reviewer prompt: across which axes does the new behaviour NOT propagate uniformly? Each asymmetric axis should be named in the changelog fragment.

## Severity guide

**Critical:** Removed/renamed `*Response` field; NOT NULL without `server_default`; enum member removed/renamed; task payload gained a required field without default; config key renamed without fallback; system or periodic task renamed in seed data; constrained-vocabulary value retired via read-path coercion instead of a data migration.

**Important:** New required field on `*Write`; column dropped still referenced by current code; error status/detail changed; endpoint removed or URL path changed (including a router-level `prefix=` change on `APIRouter` / `include_router`, which silently re-paths every endpoint on that router — confirm the re-path is required by the ticket, since path normalization bundled into unrelated work is also a scope question); seed entry removed; Nomad parameter structure changed; behavioral asymmetry across processes/deployments/install-states not named in the changelog fragment.

**Should note:** New enum member (verify consumers handle unknown values); new optional `*Response` field (confirm the default serializes cleanly); config key added as required (confirm every deployment env will set it).
