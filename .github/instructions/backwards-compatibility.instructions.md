---
applyTo: "app/**/models.py,app/**/schema.py,app/*/migrations/**/*.py,app/*/db/seed.py,app/sep/apps/**/api_routes.py,settings.yaml"
---

# Backwards Compatibility

SEP runs three API services (SEP, Inventory, Tasks) consumed by the web UI, CLI tools, and background executors. Changes to public contracts can break consumers silently.

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

## Enums

Members appear in API responses, DB columns, task payloads, and config. Removing a member breaks all of them. Renaming a member's **value** (string/int) equals removing the old + adding the new. New members are safe iff consumers handle unknown values gracefully — confirm.

## Config Keys (`settings.yaml` / env vars)

- Renaming a key breaks deployments setting the old key. Accept both old and new with a deprecation warning.
- Making an optional key required breaks deployments that omit it — provide a default.
- Changing a key's type (`str` → `list[str]`) breaks existing config files.

## Exception / Error Responses

- Changing an endpoint's error status code (404 → 410) breaks consumers matching on codes.
- Changing the error detail structure (`str` → `dict`) breaks consumers parsing it.

## Task Payloads

Serialized at task creation, deserialized by executors — potentially on a different code version. Mismatch causes `TaskDataNotFoundInExecutorException`.

- Adding a required field breaks deserialization of already-queued tasks. Use optional fields with defaults.
- Removing a field is safe (Pydantic ignores extras) **unless** the executor reads it.
- Renaming breaks queued tasks and executors reading the old name.

## Seed Data (`app/*/db/seed.py`)

System and periodic tasks are seeded at startup via `get_or_create`. Orphaned periodic tasks matching the service prefix (`sep__`, `tasks__`) are deleted automatically by `init_periodic_tasks_db`.

- Renaming a system task's `name` creates a new entry and orphans the old — scheduled jobs or user periodic tasks referencing the old name break.
- Removing a seed entry deletes it on next startup. Dependent user-configured periodic tasks or Nomad jobs fail silently.
- Renaming a `meta` key in a Nomad job template breaks in-flight jobs dispatched with the old parameter names.

## Severity guide

**Critical:** Removed/renamed `*Response` field; NOT NULL without `server_default`; enum member removed/renamed; task payload gained a required field without default; config key renamed without fallback; system task renamed.

**Important:** New required field on `*Write`; column dropped still referenced by current code; error status/detail changed; endpoint removed or path changed; seed entry removed; Nomad parameter structure changed.
