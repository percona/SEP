# SEP Task Execution — Data Flow Diagram

Customer-facing documentation of how data moves through the **Services Enablement Platform (SEP)** during a typical predefined task execution, including the parallel audit and logging path.

## Contents

| File | Purpose |
|------|---------|
| [`sep-task-execution-dfd.mmd`](sep-task-execution-dfd.mmd) | Level-1 DFD (happy path + audit/logging) |
| [`sep-task-execution-sequence.mmd`](sep-task-execution-sequence.mmd) | Sequence diagram (time-ordered detail) |
| [`security-review-checklist.md`](security-review-checklist.md) | Security sign-off before customer delivery (DFD §1–7, Nomad §8) |
| [`../nomad-driver-deployment.md`](../nomad-driver-deployment.md) | Nomad `raw_exec` driver, deployment topology, non-root agent, API access |
| [`exports/sep-task-execution-dfd.pdf`](exports/sep-task-execution-dfd.pdf) | Exported PDF — main DFD (regenerate after `.mmd` changes) |
| [`exports/sep-task-execution-sequence.pdf`](exports/sep-task-execution-sequence.pdf) | Exported PDF — sequence diagram |

**Last diagram export:** regenerate both PDFs after editing `.mmd` files (see [Export PDF](#export-pdf)).

## Legend

| Symbol | Meaning |
|--------|---------|
| Rounded rectangle `([...])` | External entity (engineer, Casdoor, Nomad, PMM, log stack) |
| Rectangle `[...]` | Process (SEP/Tasks/Celery components) |
| Cylinder `[(...)]` | Data store (PostgreSQL, snippet files, Nomad runtime) |
| Solid arrow | Primary data flow |
| Dotted arrow | Secondary / read / alternate path |

### Authentication (engineers)

Human operators authenticate with **Casdoor OAuth** (password or refresh grant). SEP validates each request via **JWT introspection** against Casdoor. Access tokens are sent as `Authorization: Bearer`; the SPA stores refresh tokens in an `HttpOnly` cookie scoped to `/api/oauth`.

**X.509 certificates are not used for engineer identity** in default SEP. Certificates secure **transport** (HTTPS and inter-service mTLS).

### Predefined commands only

The UI does not submit arbitrary shell commands. SEP uses two main execution patterns:

#### Path A — One-shot execute (snippets, dipper)

| Step | What the engineer does | What the server enforces |
|------|------------------------|-------------------------|
| Run | Pick an **approved** snippet (or dipper collector) and submit a **schema-defined** form | No saved task definition; `meta` is built on each run |
| Command | Never typed by the user | Fixed Nomad job type (`exec-artifact`, etc.) plus server-built `meta` (target, interpreter, signed artifact URL) |

**Snippets:** `POST /api/plugins/snippets/.../execute` → `POST /api/tasks/execute/exec-artifact`  
**Dipper:** `POST /api/plugins/dipper/` → same Tasks execute pattern with dipper script metadata.

#### Path B — Create then execute (proxy plugins: checksums, gascan, alters)

| Step | What the engineer does | What the server enforces |
|------|------------------------|-------------------------|
| **Create** | Fill a plugin form (e.g. MySQL service, databases, checksum options) | Plugin resolves inventory entities and builds a **PROXY** task: fixed `meta.command` (e.g. `pt-table-checksum`), `meta.args`, `meta.target` stored in Tasks DB |
| **Execute** | Click **Execute** on a saved task (optional ETA / task chain) | Request body does **not** include a new shell command; Tasks API **merges** stored `meta` from the task definition (`prepare_task_history` for `TaskBackendEnum.PROXY`) |
| **Nomad** | — | Dispatches underlying `run-command` job with merged meta |

**Checksums example (canonical Path B):**

1. **Create:** `POST /api/plugins/checksums/` — `build_checksum_task` assembles `pt-table-checksum` with args from inventory (`app/sep/plugins/checksums/deps.py`, `_assemble_checksum_payload`).
2. **Persist:** `POST /api/tasks/` — task row with `owner=CHECKSUMS`, `backend=PROXY`, `data.task=run-command`.
3. **Execute:** `POST /api/tasks/execute/{task_name}` — body may only contain `eta`, `chain_task_names`; command comes from stored task (`app/sep/plugins/checksums/routes.py`, `checksums_execute`).

The same two-phase pattern applies to **gascan** (`command: gascan`) and **alters** (`command: pt-online-schema-change`).

The Nomad `run-command` template runs `${NOMAD_META_command}` with args from meta; the UI never supplies a free-form command string at execute time.

### What is logged

| Data | Storage | When |
|------|---------|------|
| User identity | `taskhistory.executed_by` (Casdoor user id; `"SYSTEM"` for periodic runs) | Task dispatch |
| Timestamps | `created_at`, `started_at`, `finished_at` | Create + executor sync |
| Command context | `execution_request` JSON (`task`, `target`, `meta`, `payload`) | Create |
| Output | `taskhistory_log` (stdout/stderr chunks) | During/after run |
| Lifecycle | Nomad `task_states` → execution events API | Sync |
| External timeline | PMM annotations | Start / terminal status |
| HTTP context | `request_id`, `correlation_id`, `user` in app logs | Each request (infra stack, not Tasks DB) |

Optional **Presidio anonymization** may mask log content when `anonymize_mask` is enabled for a task owner.

### Where logs live and who can access them

| Store | Access |
|-------|--------|
| **Tasks PostgreSQL** (`taskhistory`, `taskhistory_log`) | Any **authenticated** OAuth user (or `SEP_INTERNAL_TOKEN` service principal) with a valid token can read task history and logs by ID. General list/retrieve APIs do **not** filter by `executed_by`. |
| **PMM** | Users with PMM annotation access for the environment. |
| **Infrastructure logs** | Platform operators with access to the deployment log pipeline. |
| **Snippet approval** | **Admin** users only (`PUT .../approval`). |

**Exception:** Inventory topology bulk history enforces `executed_by == current_user` for specific task/meta combinations.

## Edit the diagrams

1. Install [Mermaid](https://mermaid.js.org/) support in your editor, or use [mermaid.live](https://mermaid.live).
2. Edit `.mmd` files in this directory.
3. Re-export PDF (see below) before customer delivery.

Alternative: import `.mmd` into [diagrams.net](https://app.diagrams.net/) for GUI editing, then export PDF manually.

**Sequence diagram editing:** `mermaid-cli` fails on semicolons, curly braces, and some punctuation inside `Note over` lines and message text. Keep labels simple or split Path B into separate `rect` blocks (as in `sep-task-execution-sequence.mmd`).

## Export PDF

From the repository root:

```bash
npx -y @mermaid-js/mermaid-cli \
  -i docs/customer/sep-task-execution-dfd/sep-task-execution-dfd.mmd \
  -o docs/customer/sep-task-execution-dfd/exports/sep-task-execution-dfd.pdf \
  -b white

# Optional: sequence diagram PDF
npx -y @mermaid-js/mermaid-cli \
  -i docs/customer/sep-task-execution-dfd/sep-task-execution-sequence.mmd \
  -o docs/customer/sep-task-execution-dfd/exports/sep-task-execution-sequence.pdf \
  -b white
```

Commit the updated `.mmd` sources with any README/checklist changes. The PDF under `exports/` may be committed or produced at release time; if committed, regenerate whenever sources change.

## Code mapping (DFD nodes → implementation)

| DFD node | Source (representative) |
|----------|-------------------------|
| P1 OAuth login | `app/api/routes/oauth.py` (`spa_login`) |
| P2 JWT introspection | `app/core/auth/providers/casdoor.py`, `app/models.py` (`from_jwt`) |
| P3 SEP UI | `frontend/packages/shell/src/contexts/auth.tsx`, snippet UI components |
| P4a Snippets plugin API | `app/sep/plugins/snippets/api_routes.py`, `deps.py` |
| P4b Proxy plugin create (checksums) | `app/sep/plugins/checksums/api_routes.py` (`checksums_api_create`), `deps.py` (`build_checksum_task`, `_assemble_checksum_payload`) |
| P4c Proxy plugin execute (checksums) | `app/sep/plugins/checksums/routes.py` (`checksums_execute`) |
| PROXY meta merge | `app/tasks/deps.py` (`prepare_task_history`, lines ~191–193) |
| P5 Tasks API | `app/tasks/routes.py` (`execute_task_name`), `app/tasks/deps.py` |
| D4 Task definitions | `task` table via `POST /api/tasks/`; seed template `run-command` in `app/tasks/db/seed.py` |
| Inventory (Path B) | `app/sep/plugins/checksums/deps.py` (`get_created_entity` for services/schemas/tables) |
| P6 Celery worker | `app/tasks/celery.py` (`dispatch_queue_item`) |
| P7 Nomad executor | `app/tasks/execution/executors/nomad/models.py` |
| P8 Record attribution | `app/tasks/deps.py` (`prepare_task_history`) |
| P9 Persist logs | `app/tasks/logs/log_writer.py`, `app/tasks/crud.py` |
| P10 PMM annotations | `app/core/pmm.py` |
| P11 HTTP request context | `app/core/middleware/log_context.py`, `app/api/deps.py` |
| D1 Snippet store | `app/sep/snippets/`, snippet approval in DB |
| D2 Tasks PostgreSQL | `app/tasks/models.py`, `app/tasks/db/` |
| D3 Nomad runtime | Nomad allocation logs/files (fetched via Nomad API) |
| mTLS transport | `app/core/requests/remote_api.py`, `settings.yaml` (`TASKS.NOMAD`), `generate_certs.sh` |

## Security review

Complete [`security-review-checklist.md`](security-review-checklist.md) and obtain sign-off **before** sending the PDF to a customer.

## Out of scope

- Certificate-based **user** login (not implemented in default SEP)
- Full Nomad/PMM deployment topology (see [Nomad driver & deployment](../nomad-driver-deployment.md))
- Celery-only (non-Nomad) executors except where noted
- Inventory sync flows unrelated to task execution
