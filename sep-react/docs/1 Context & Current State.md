# 1. Context & Current State

## Where We Are Today

SEP is a **customer-facing Percona product** (not an internal tool — this framing matters for quality, security, and performance decisions). It is built as a FastAPI application with three mounted sub-applications and a traditional server-rendered UI:

```
app/main.py (main FastAPI app)
├── /api/inventory → Inventory API (standalone sub-app, full REST — cookie + Bearer auth)
├── /api/tasks     → Tasks API (standalone sub-app, full CRUD + execution — cookie + Bearer auth)
└── /              → SEP app (Jinja2 UI, 13 plugins, cookie auth, CSRF middleware)
```

**Current stack:**

- **Backend**: FastAPI, SQLModel/SQLAlchemy (async), Celery (with sqlalchemy-celery-beat), Casdoor OAuth
- **Frontend**: Jinja2 templates (.html.j2), jQuery 3.7.1, vanilla JS, `simple-datatables`, `select2`, moment.js
- **13 plugins** in `app/sep/plugins/`: alerts, alert_troubleshooting, alters, archives, atw, backup, backup_mongo, backup_pg, checksums, dipper, inventory, snippets, tasks (plus report which is template-only)
- **~80+ Jinja2 templates** in `templates/` with shared partials for task chaining, log streaming, task history
- **No frontend build infrastructure**: no `package.json`, no bundler, no TypeScript

**Key existing mechanisms** (shared across plugins, not plugin-specific):

- **SSE log streaming** via `app/sep/routes/stream_logs.py` + `static/js/logs.js`
- **Task chaining** via `static/js/chain-builder.js` + `templates/tasks/partials/chain-builder.html`
- **Task history tables** via `templates/tasks/partials/{running,completed,scheduled}-tasks.html.j2`
- **Service/Schema/Table cascading selectors** via `static/js/schema-selector.js`
- **Alert-on-fail** via `templates/tasks/partials/create-form-alert-on-failure-input.html.j2`
- **CSRF protection** via OWASP Signed Double-Submit Cookie pattern (`app/sep/middleware/csrf.py`), already SPA-compatible per SEP-662

**What we already have that's useful for the migration:**

- Inventory API at `/api/inventory/` — a mature REST API with response models, dependency injection, and pagination-ready CRUD managers. Reference pattern for plugin API routes.
- Tasks API at `/api/tasks/` — full CRUD, execution, history, SSE streaming.
- `OAuth2PasswordBearer` already in `app/api/deps.py` — Bearer token auth already works for the sub-apps. SEP app currently uses cookies but the pattern is established.
- **Snippets plugin as a working schema-driven plugin prototype** — see "The Snippets Pattern" below.

## Prior Decisions & Shipped Work

| Ticket | Status | What |
| --- | --- | --- |
| SEP-235 | Done | React Review Planning — team decided on React with Percona shared packages |
| SEP-464 | Done | Micro-Frontend POC with Webpack Module Federation + React |
| SEP-365 | Done | Inventory table rebuilt in React via CDN (no SPA) |
| SEP-636 | Done | Backend changes for SPA enablement |
| SEP-662 | Done | CSRF token persistence for SPA compatibility (multi-tab POST-safe) |
| SEP-610 | In Review | Running Tasks — first React plugin component with MUI |
| SEP-921 | Ready for Work | JSON API endpoints for checksums plugin (API-first pattern) |

### Existing Epics

| Epic | Status | Scope |
| --- | --- | --- |
| SEP-188 | Ready for Work | Convert SEP into an API |
| SEP-475 | Ready for Work | FE — Inventory React version |

Both epics will likely be superseded by the new, more detailed epic structure produced as part of this migration plan.

## Framework Choice — React, Not Vue

The previous Frontend Migration doc (separate Notion page) contains a thorough Vue vs React analysis. Vue has genuine technical strengths — template affinity with Jinja2, fine-grained reactivity, smaller bundle baseline, and a cohesive official ecosystem. For a greenfield project with a small team, Vue would be a strong choice.

However, the organizational context points decisively to React:

**Prior investment**: Four tickets of shipped React work (SEP-235, SEP-464, SEP-365, SEP-610) plus SEP-921 in progress. A validated Module Federation POC using React. Throwing this away to adopt Vue means rewriting everything and losing the learnings.

**Percona ecosystem**: Percona ships `@percona/percona-ui` — a React component library actively maintained by the PMM frontend team, with a tightly integrated theme system and Storybook. There is no Vue equivalent. See "The `@percona/percona-ui` Adoption" section below.

**Hiring & staffing**: Percona's frontend pipeline is React-oriented. Every other Percona frontend project uses React. Using Vue creates a single-framework island inside a React company.

**Future alignment**: The Percona React ecosystem (PMM, OpenEverest, now SEP) is converging. A Vue island would need ongoing cross-framework bridging — a real cost for a 4-person team.

The Vue analysis remains a valuable reference document. The architecture decisions in this migration (API-first, strangler fig pattern, monorepo, plugin model) are largely framework-agnostic and would apply either way — we are keeping the good ideas and executing them with React.

## The `@percona/percona-ui` Adoption

SEP will depend on `@percona/percona-ui` as its primary React component library. This is the **active, maintained** Percona shared component package — not the older `@percona/ui-lib` which has been frozen at v1.1.0 since June 2025.

**Package facts:**

- Repo: [https://github.com/percona/percona-ui](https://github.com/percona/percona-ui) (created 2025-12-16)
- npm: `@percona/percona-ui@1.0.14` (published 2026-04-08)
- Tech: React 18, TypeScript, **MUI v7**, react-hook-form, Emotion for styling
- License: **AGPL-3.0-or-later** — reviewed and cleared for adoption as a hard SEP dependency
- Maintainers: fabio-silva, freenandes (PMM frontend team)
- Activity: 61 commits in last 3 months, biweekly npm releases

**What it provides:**

- **~25 form inputs and components** (TextInput, SelectInput, AutoCompleteInput, RadioGroup, SwitchInput, DateTimePickerInput, CheckboxInput, FileInput, ToggleButtonGroupInput, etc.) all integrated with react-hook-form
- **Layout components**: Card, OverviewCard, Dialog, LabeledContent, ActionableLabeledContent
- **Data display**: Table (built on material-react-table), Stepper, ProgressBar
- **Feedback**: NotistackMuiSnackbar, CodeCopyBlock, CopyToClipboardButton, LoadableChildren
- **Theme system**: base / pmm / sep themes with light and dark modes, design token primitives, `ThemeContextProvider` handling localStorage persistence

**SEP integration already in flight:**

- **PR #9** (open, by nachodd): Adds full SEP theme to percona-ui — purple `#653DF4` primary, brand black `#282727` AppBar, yellow `#F6FE54` accent, technology colors for MySQL/PostgreSQL/MongoDB/Kubernetes/Redis/Valkey, plus full light/dark token scales. Under review.
- **PR #10** (open, by nachodd): Fixes a react-hook-form bundling bug — externalizes it as a peer dependency so consumers get a single shared context. Under review.

These PRs mean Wave 0's frontend work starts with percona-ui already partially prepped for SEP. Once they merge, we install `@percona/percona-ui`, wrap the app in `<ThemeContextProvider theme="sep">`, and inherit the Percona brand automatically.

### License Considerations (AGPL-3.0)

`@percona/percona-ui` is licensed under **AGPL-3.0-or-later**. SEP is a Percona-owned product and ships as a service, so Percona-on-Percona usage is fine. However, AGPL is strict copyleft:

- Any modifications to percona-ui components shipped to SEP users must also be AGPL-compatible
- If SEP ever ships code that cannot be AGPL-compatible (e.g., because of a customer integration requirement), that code must be isolated from percona-ui dependencies
- Community contributions to SEP (plugins, extensions) that use percona-ui components inherit the AGPL obligation

<aside>
⚠️

**Action**: Flag this with Percona legal / the platform team before making percona-ui a hard dependency. This is a pre-Wave-0 blocker, not a blocker for design review. The risk is low (Percona owns both SEP and percona-ui) but the acknowledgement is necessary.

</aside>

## Percona Rebrand Context

Percona is undergoing a company-wide rebrand. Assets live in `env/rebrand/` in the SEP repo:

- **Typography**: **Ardela Edge** (headlines, bold caps), **Poppins** (supporting copy, fallback), **Roboto** (product UI font)
- **Logos**: Horizontal / vertical / logomark SVGs in light, dark, white, yellow, and purple variants plus "The Way is Open" tagline
- **Brand colors**: In the Color Cheat Sheet PDF — **nachodd's PR #9 has already extracted them** for the SEP theme in percona-ui

**Implications for the migration:**

- The rebrand's colors and typography are the target for the React SPA — don't carry over the old Jinja2 theme
- Most of the design token work happens inside `percona-ui` (nachodd's PR #9), not in SEP
- SEP will need to register the Ardela Edge font (custom, not available via Google Fonts) and reference Roboto / Poppins from `@fontsource` or similar
- No explicit rebrand deadline found in the SEP repo — clarify with design / marketing before committing

## OpenEverest Context (formerly "Everest")

Percona Everest was rebranded as **OpenEverest** and the project was restructured. Old references to "Percona Everest" in docs should be updated to "OpenEverest". The main `percona/everest` repo still exists and has its own UI monorepo (`ui/` with workspace packages). `@percona/percona-ui` is effectively a standalone successor to `@percona/ui-lib` from that monorepo — same designer (Pedro Fernandes), same maintainer (Fabio Silva), but consolidated into one package and bumped to MUI v7.

**Implication**: The potential "merge into the React product" mentioned in the previous Frontend Migration doc was about Everest / OpenEverest. That product now lives at [https://github.com/openeverest/openeverest](https://github.com/openeverest/openeverest) (and `percona/everest`), and its UI is still on the old `@percona/ui-lib` (MUI v5). Direct merge compatibility is therefore NOT automatic — both would need to converge on percona-ui + MUI v7 first. This reduces the "future merge" urgency but doesn't invalidate the React choice.

## The Snippets Pattern — The Schema-Driven Plugin Prototype

<aside>
💡

**Critical context for this migration**: the snippets plugin is already a working schema-driven plugin. It uses YAML frontmatter embedded in the snippet script file to declare parameters, then dynamically builds a Pydantic model from that schema at runtime. The form rendering is auto-generated from the parameter list.

</aside>

Key code:

- `app/sep/plugins/snippets/models.py` — defines `SnippetMetaParameter` (Pydantic model for a single parameter with fields like `name`, `py_type`, `required`, `label`, `placeholder`, `description`, `group`, `min_length`, `pattern`, `choices`, `default`, `html_elem`, etc.)
- `BaseSnippet.get_execution_model()` — creates a Pydantic model dynamically from `meta["parameters"]`
- `BaseSnippet.to_form()` — generates HTML form with fieldsets, inputs, validation rules

**This is the prototype for the migration's schema-driven plugin vision.** Instead of inventing a new DSL, we extend this pattern so plugins declare their forms as Python Pydantic schemas, expose them via `/api/plugins/{name}/schema`, and the React `<SchemaFormRenderer>` reads the schema and renders the form using percona-ui's form inputs.

Details in the Plugin Model & Shared Framework subpage.

## Team & Schedule Context

**Team composition** (as of 2026-04-08):

- **2 Backend engineers** (Yan + 1 other, other BE out until 2026-04-22)
- **1 Frontend engineer** (Ignacio "nachodd" Durand — already integrating percona-ui)
- **1 Fullstack engineer** (can work on either side)

**Schedule anchors:**

- **2026-04-14 (Tue)**: Current sprint ends. RC1 of v0.12.0 cut and released.
- **2026-04-15 (Wed)**: New sprint starts. Refactor kickoff.
- **2026-04-15 → 2026-04-28**: **Sprint freeze window**. Other work merges are paused to avoid rework with the old pattern. Only one freeze sprint is available.
- **2026-04-22 (Wed)**: Other BE returns from absence — full team available for second week of freeze sprint.
- **2026-04-29**: Freeze ends. Normal sprints resume. Feature work and plugin migrations run in parallel.

Full timeline and team allocation: see Migration Strategy subpage.

## What This Means for Architecture Decisions

The context above directly shapes several decisions documented in the following pages:

1. **Same-origin deployment**: SEP is a product, customers install it with `sep_installer.sh`. Avoiding separate Docker containers, new services, and CORS dramatically simplifies the operational story.
2. **Security first**: Customers trust SEP with their database infrastructure. Design decisions that trade security for convenience are rejected.
3. **Gateway pattern**: The Inventory and Tasks sub-apps have their own auth and API surface. Exposing them directly to the frontend would leak internal details. SEP proxies and controls the exposed surface.
4. **Schema-driven plugins**: We want plugin creation to be accessible to non-core developers. The snippets pattern proves the idea works. Generalizing it is a primary architectural goal.
5. **Shared framework layer before plugin migrations**: The cross-cutting concerns (log streaming, chaining, history, selectors) must be solved once in React before any plugin migration is productive.
6. **Realistic 2-week Wave 0**: The freeze window is 2 weeks with a team partially reduced in week 1. Wave 0 scope must be tight and parallelizable.
