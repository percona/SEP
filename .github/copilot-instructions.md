# Copilot Code Review Instructions

This file gives GitHub Copilot the project context it needs when reviewing PRs against SEP. Per-area rules live under `.github/instructions/`.

## Project shape

SEP is a FastAPI application with three mounted sub-applications, each with its own database, Alembic migration chain, and Celery beat:

- `app/inventory/` — nodes, services, schemas, tables; mounted at `/api/inventory`.
- `app/tasks/` — task execution, Nomad/local executors, periodic tasks; mounted at `/api/tasks`.
- `app/sep/` — web UI, Jinja templates, OAuth, apps; mounted at `/`.

SEP apps are FastAPI routers under `app/sep/apps/<name>/` with `routes.py`, `deps.py`, and optional `models.py`. `Annotated[..., Depends(...)]` aliases live in `deps.py`.

The codebase is undergoing an **API-First + React migration** — see `api-first.instructions.md` for rules that apply when a PR touches the API gateway, app schemas, or `frontend/packages/`.

## How to review

1. **Scope first, quality second.** The most common failure mode in code review is approving correct-but-unscoped code. Look at the diff holistically: are all touched files necessary for the stated purpose? Cosmetic rewording in files with no behavior change, function splits that weren't requested, constants extracted for single-use values, parameters added "for future flexibility", and "while I'm here" refactors all signal scope creep. Flag them even when the code is cleaner after — staying focused matters more than incidental polish.
2. **Cite the codebase, not rules.** When flagging a convention, reference an in-tree example (`app/core/utils/fields.py:NN`), not "the project standard" or any internal document. The audience for a review comment is the PR author — don't mention internal tooling, AI, or automation.
3. **Comment tone.** Suggest, don't demand. Prefer "Consider …" / "The codebase does X — see `file.py:line`" over "Violation", "Forbidden". Lead the top-level review with one or two specific strengths.
4. **Comment don'ts.** Never `@`-mention bot accounts (`@copilot`, `@dependabot`, `@coderabbitai`, `@github-actions`, …) — GitHub treats the mention as a wake signal and triggers a duplicate review run; name the bot without the `@` if you must. Never make first-person offers to the operator inside a posted comment ("happy to file a ticket", "let me know if you want me to …") — the only audience on the PR is the author; state any follow-up as a fact ("this belongs in a separate ticket").

## Repo-wide rules (apply to every PR)

- **PR title** follows `SEP-XXX: <description>` — colon, space, non-empty description — when a Jira ticket is associated. Exempt: dependency bumps, version bumps, release branches.
- **HTTP status codes**: `fastapi.status` constants (`status.HTTP_404_NOT_FOUND`) — never raw integers — in route decorators, exception raises, test assertions, `JSONResponse`.
- **Prefer named project exceptions over raw `fastapi.HTTPException`.** Direct `fastapi.HTTPException` is a tech-debt signal — check `app/core/exceptions.py` and `app/core/auth/exceptions.py` first (`HTTPNotFoundException`, `HTTPConflictException`, `HTTPForbiddenException`, `HTTPGoneException`, `HTTPBadRequestException`, etc. already exist). Flag it especially when the same `fastapi.HTTPException(status_code=…, detail=…)` shape appears in 2+ places with the same custom params — that repetition should become a named exception class.
- **Changelog fragments** — user-facing PRs add a file under `changelog.d/` via `make changelog-add TICKET=SEP-XXX SECTION=<added|changed|fixed|security|breaking|config> MSG="…"`. Skip for purely internal changes (CI, refactors, tooling, docs with no user-visible effect), for same-release-cycle fixes (regression from a sibling ticket sharing the unreleased `Fix Version`, linked in Jira via `is caused by`), and for framework-spine-uniform surface (a verb/param/field a shared framework like `TaskExecutionApp` ships once and every migrating app inherits identically — documented once when the framework ships it; add a fragment only for the app-specific delta). Don't expect edits to `[Unreleased]` in `CHANGELOG.md` — that section is assembled at release time.
- **No emojis** in code, comments, docstrings, or commit messages unless the file already uses them.
- **No new files** unless required by the change. Prefer editing existing modules.
- **Dependency edits**: when `pyproject.toml` changes a dependency declaration (`tool.poetry.dependencies`, `tool.poetry.group.*.dependencies`), `poetry.lock` must be updated together via `poetry add` / `poetry remove` / `poetry update`. Non-dependency edits to `pyproject.toml` (ruff config, tool sections) don't require a lockfile update.
