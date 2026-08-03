# SEP Architecture — Deployment Topology

Customer-facing static deployment topology of the **Services Enablement Platform (SEP)** as deployed by `sep_installer.sh` against a customer-provided external Nomad cluster.

## Contents

| File | Purpose |
|------|---------|
| [`sep-architecture.mmd`](sep-architecture.mmd) | Mermaid source (`flowchart TB`) of the topology |
| [`security-review-checklist.md`](security-review-checklist.md) | Security sign-off checklist before customer delivery |
| [`exports/sep-architecture.pdf`](exports/sep-architecture.pdf) | Exported PDF — regenerate after editing the `.mmd` |

**Companion tickets — not duplicated here:**

- **SEP-1215** — Dynamic per-task data flow (Level-1 DFD and sequence diagram)
- **SEP-1218** — Nomad driver and deployment detail (raw_exec sandboxing, non-root agent)
- **SEP-1220** — Audit-log retention and PII filtering policy

## Audience

This diagram is intended for a customer security reviewer who needs to assess:

- The exposed network surface of the SEP controller host
- The authentication boundary between human users and machine-to-machine integrations
- Where data flows out of the customer's environment (PMM, internal SEP services)
- Where execution lands inside the customer's environment (Nomad agents on DB hosts)

It is **not** a per-task data flow, retention policy, or driver/sandbox specification — see the companion tickets above.

## Legend

| Symbol | Meaning |
|--------|---------|
| Stadium `(["…"])` | External entity (engineer browser, PMM, customer Nomad cluster, customer DB engine) |
| Rectangle `["…"]` | Process running in the SEP stack or on a DB host |
| Cylinder `[("…")]` | Data store (PostgreSQL, Redis) |
| Solid arrow | Synchronous / primary data flow |
| Dotted arrow | Asynchronous / optional / sync-style traffic |
| Thick arrow `==>` | Customer network boundary (Nomad RPC) |

### Color groupings

| Color | Group |
|-------|-------|
| Pink-red border | Edge ingress (Nginx) |
| Blue border | SEP application processes (Nginx upstream, Casdoor, FastAPI sub-apps) |
| Yellow border | Background workers (Celery beat, Celery worker) |
| Green border | Data plane (PostgreSQL, Redis) |
| Amber border | External services (PMM, customer Nomad) |
| Tan border | Per-DB-host agents and DB engines |

## Topology summary

- **Ingress.** The Percona engineer or DBA reaches the SEP UI over HTTPS on port `8444`. Nginx terminates TLS and serves the React SPA from a build-time bundle (`/home/sep/app/frontend/dist`), forwarding `/api/`, `/artifacts/`, and SSE paths to the FastAPI `app` container on internal port `9000`. Port `9999` exposes the Casdoor login UI through the same Nginx, also TLS-terminated. No SSH tunnel.
- **Authentication.** Human users sign in via **Casdoor** (OAuth 2.0 / OIDC). The SEP App validates Casdoor JWTs and rotates refresh tokens via an `HttpOnly` cookie. Casdoor runs inside the SEP stack as a containerized IdP — there is no external user-cert login.
- **API gateway.** The SEP App is the only FastAPI process exposed through Nginx. `Inventory API` and `Tasks API` listen on internal ports `9001` / `9002` and are reached only through the SEP App (`SEP.INVENTORY_ENDPOINT`, `SEP.TASKS_ENDPOINT` in the rendered `settings.yaml`).
- **Background.** Celery beat schedules periodic tasks (including a TLS-cert-expiry check for Nomad). Celery worker consumes the queue, dispatches Nomad jobs, syncs task state, and pushes PMM annotations.
- **Data plane.** A single PostgreSQL instance hosts the SEP, Inventory, Tasks, and beat-scheduler databases. Redis is the Celery broker. Both are internal-only (no host port published).
- **SEP ↔ Nomad.** The customer-provided Nomad cluster is reached over HTTPS with **mTLS** (Nomad CA validation + SEP client cert/key under `/app/`). The `NomadExecutor` filters Nomad nodes with `Status == ready and raw_exec in Drivers and Drivers.raw_exec.Healthy == true` — **only the `raw_exec` driver is used**; the standard Nomad `exec` driver is never referenced. A periodic `check_nomad_cert_expiry` job watches the configured CA and client cert.
- **DB hosts.** Each DB host runs a Nomad agent advertising the `raw_exec` driver and the local DB engine (MySQL, PostgreSQL, or MongoDB). Job payloads execute as `raw_exec` shell scripts against the local DB.
- **PMM.** PMM is external (customer-deployed or Percona-operated). Inventory uses it for service-catalog sync; Celery worker pushes execution annotations.

## Source-of-truth notes

The diagram is anchored to the artifacts that the installer actually writes to a customer host. **The repository's `docker-compose.yml` and `data/nginx.conf` are NOT used as a source** — those are dev/test artifacts. The customer-deployed templates are embedded as gzip+base64 blobs inside `sep_installer.sh` and rendered to the install directory by `render_templates_cli` (around line 1317; `printf | base64 -d | gunzip > $outfile.tmp` plus sed substitutions).

| Source | Where | What it pins |
|--------|-------|--------------|
| Installer blob `NGINX_CONFIG` | `sep_installer.sh` line ~1806 → `nginx.conf` | TLS ingress, port mapping, React SPA static path, upstream proxy paths |
| Installer blob `SEP_COMPOSE_YAML` | `sep_installer.sh` line ~1821 → `compose.yaml` | Container list, internal ports, dependencies, network topology |
| Installer blob `SEP_SETTINGS_YAML` | `sep_installer.sh` line ~1863 → `settings.yaml` | Internal service endpoints, OAuth/Casdoor config, Nomad endpoint and TLS material |
| Installer blob `CASDOOR_INIT_JSON_DATA` | `sep_installer.sh` line ~1714 → `casdoor_init.json` | Casdoor seed organization (`sep`), application (`sep-app`), signing cert |
| SEP MS Playbook playbook | `build/ansible/` + [Notion: SEP MS Playbook installation](https://www.notion.so/percona/SEP-MS-Playbook-installation-28e674d091f380ee9ec2f7721646283f) | Host firewall ports (4647 / 8443 / 8444 / 9999), Nomad agent presence on DB hosts, custom CA cert wiring |
| SEP application | `origin/main` at commit `6628d230fd91e89e1be94fad95a124fe3ccb96a1` | OAuth handshake, raw_exec driver filter, Celery wiring |

To regenerate the four blobs from the installer for an offline audit:

```bash
python3 - <<'PY'
import re, base64, gzip, pathlib
text = pathlib.Path('sep_installer.sh').read_text()
out = pathlib.Path('extracted'); out.mkdir(exist_ok=True)
for var, fname in [
    ('CASDOOR_INIT_JSON_DATA', 'casdoor_init.json'),
    ('NGINX_CONFIG', 'nginx.conf'),
    ('SEP_COMPOSE_YAML', 'compose.yaml'),
    ('SEP_SETTINGS_YAML', 'settings.yaml'),
]:
    m = re.search(rf"^{re.escape(var)}='([^']*)'\s*$", text, flags=re.MULTILINE | re.DOTALL)
    (out / fname).write_bytes(gzip.decompress(base64.b64decode(m.group(1))))
PY
```

## Code-mapping table

Every node and cross-subgraph edge in `sep-architecture.mmd` traces to one of the canonical sources. The table maps each element to the file, key, or symbol that pins it.

| Diagram element | Pinned in |
|-----------------|-----------|
| `Nginx` ingress, TLS, React SPA path, `/api/` `/artifacts/` `/stream-logs/` upstream | `NGINX_CONFIG` blob → `nginx.conf` (`server { listen 8444 ssl; … proxy_pass https://app:9000 }`, `server { listen 9999 ssl; … proxy_pass http://casdoor:8000 }`) |
| `Casdoor` IdP, seeded `sep` organization + `sep-app` application | `CASDOOR_INIT_JSON_DATA` blob → `casdoor_init.json` (organizations[0].name `sep`, applications[0].name `sep-app`); compose service `casdoor` on internal port 8000 |
| `SEP App` on port 9000, `Inventory API` on 9001, `Tasks API` on 9002 | `SEP_COMPOSE_YAML` blob → `compose.yaml` services `app`, `inventory_api`, `tasks_api`; `SEP_SETTINGS_YAML` blob → `settings.yaml` keys `SEP.INVENTORY_ENDPOINT`, `SEP.TASKS_ENDPOINT` |
| `Celery beat`, `Celery worker` | `compose.yaml` services `celery_beat`, `celery_worker`; `app/celery.py` (shared Celery app); `app/tasks/celery.py` (`execute_task_queue`, `sync_running_tasks`, `check_nomad_cert_expiry`) |
| `PostgreSQL` (sep + beat-DB) | `compose.yaml` service `db`; `settings.yaml` keys `DATABASE`, `INVENTORY.DATABASE`, `TASKS.DATABASE`, `CELERY.BEAT_DBURI` |
| `Redis` broker | `compose.yaml` service `redis`; `settings.yaml` key `CELERY.BROKER_URL` |
| Engineer → Nginx (HTTPS :8444), Casdoor login (:9999) | `nginx.conf` `server { listen 8444 ssl }` and `server { listen 9999 ssl }`; SEP MS Playbook firewall task opening ports `4647,8443,8444,9999` on the controller |
| SEP App → Casdoor (OAuth introspect + JWT validate) | `app/api/routes/oauth.py` (`/token`, `/login`, `/refresh`, `/logout`); `app/core/auth/providers/casdoor.py` (`introspect_token`, `get_access_token`, `refresh_token_request`) |
| SEP App → Inventory API / Tasks API (HTTPS, internal) | `settings.yaml` keys `SEP.INVENTORY_ENDPOINT=https://inventory_api:9001`, `SEP.TASKS_ENDPOINT=https://tasks_api:9002` |
| Celery worker / Tasks API → Nomad (mTLS) | `app/tasks/execution/executors/nomad/models.py` (`NomadExecutor.backend` builds the client with `cert=(ssl_certfile, ssl_keyfile)`, `verify=ssl_cafile`); `app/tasks/celery.py:check_nomad_cert_expiry` watches `TASKS.NOMAD.SSL_CAFILE` and `TASKS.NOMAD.SSL_CERTFILE` |
| Nomad raw_exec-only filter | `app/tasks/execution/executors/nomad/models.py` — `NomadExecutor.get_hosts()` filter expression `"Status == ready and raw_exec in Drivers and Drivers.raw_exec.Healthy == true"` |
| PMM ← Inventory API (sync) + ← Celery worker (annotations) | `settings.yaml` keys `PMM.ENDPOINT`, `PMM.API_KEY`; `app/core/pmm` annotation helpers used by `app/tasks/celery.py` (`schedule_annotation`, `await_annotation`); `SEP.SYNCERS[]` includes `PMMSyncer` |
| Nomad cluster ↔ DB-host Nomad agents (port 4647) | SEP MS Playbook `build/ansible/ansible-controller-*-test-instance.yaml` firewall task opens TCP `4647`; SEP MS Playbook installation Notion page lists port `4647` as a `db_nodes` pre-check requirement |
| DB-host Nomad agent → local DB (raw_exec) | Topology implication of `raw_exec` + the `app/tasks/execution/executors/nomad/models.py` driver filter; `get_hosts()` returns the node-name→address map used as the dispatch target |

## Edit the diagram

1. Install [Mermaid](https://mermaid.js.org/) support in your editor, or open `sep-architecture.mmd` in [mermaid.live](https://mermaid.live).
2. Edit the `.mmd` source.
3. Re-export the PDF before customer delivery (see below).
4. Spot-check the code-mapping table when the source files move; the pinned origin/main commit above is the contract.

## Export PDF

```bash
./docs/customer/sep-architecture/render.sh
```

The script (`render.sh`) pipes `mermaid-cli` → SVG → HTML-with-`@page A3 portrait` → Chromium headless `--print-to-pdf` and writes `exports/sep-architecture.pdf`. Requires `npx` and a `chromium` (or `chromium-browser` / `google-chrome` / `chrome`) on `PATH`. The pipeline keeps the diagram a single A3 page with crisp vector text — `mermaid-cli`'s `--pdfFit` alone emits a non-standard tall page that some viewers paginate visually, and a PNG-based pipeline pixelates the text.

Commit the updated `.mmd` source alongside README/checklist edits and regenerate the PDF.

## What this diagram does NOT cover

- **Dynamic per-task data flow** (request → snippet/proxy app → executor → DB → log path). See **SEP-1215**.
- **Nomad raw_exec driver semantics, non-root agent, ACL stance, agent sandboxing**. See **SEP-1218**.
- **Audit-log retention, PII filtering, log anonymization, ServiceNow / PagerDuty ingestion**. See **SEP-1220**.
- **The bundled-PMM-container variant** (`CREATE_PMM_CONTAINER=1`). The diagram represents the customer-deployed scenario where PMM is external and Nomad is customer-provided; the `#---PMM---#` block of `compose.yaml` is sed-removed in that scenario.

## Customer-facing hygiene

- All hostnames are generic placeholders (`DB Host 1`, `DB Host 2`); no customer-specific names or IPs appear in the diagram.
- Cert paths in the diagram say "Nomad CA + client cert"; container-local paths (`/app/ca.pem`, `/app/cert.pem`, `/app/key.pem`) are implementation detail.
- PagerDuty and ServiceNow are not on the diagram (Percona-internal). The alerting and ticketing integrations are documented in the data-handling ticket (SEP-1220).
