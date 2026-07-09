# Security Review Checklist — SEP Deployment Topology

Complete this checklist before sending the customer the deployment-topology PDF.

**Deliverable:** [`exports/sep-architecture.pdf`](exports/sep-architecture.pdf)
**Diagram source:** [`sep-architecture.mmd`](sep-architecture.mmd)
**Companion docs:** [`README.md`](README.md)

This checklist is scoped to the **static deployment topology**. Task-execution data flow is reviewed by the SEP-1215 checklist; retention / PII handling is reviewed by SEP-1220.

---

## Reviewer information

| Field | Value |
|-------|-------|
| Reviewer name | |
| Review date | |
| Git commit / tag reviewed | |
| PDF generated from commit | |
| Installer SHA-256 reviewed (`sep_installer.sha256`) | |

---

## 1. Ingress and TLS

| # | Question | Pass | Fail | Notes |
|---|----------|:----:|:----:|-------|
| 1.1 | Engineer → SEP ingress is shown as **HTTPS on port 8444** (no SSH tunnel, no plain HTTP) | ☐ | ☐ | |
| 1.2 | Casdoor login UI is shown on **HTTPS port 9999** through the same Nginx | ☐ | ☐ | |
| 1.3 | Port 8080 HTTP-to-HTTPS redirect is either drawn or explicitly described in README | ☐ | ☐ | |
| 1.4 | TLS is terminated at **Nginx only**; upstream traffic to FastAPI sub-apps is internal-network HTTPS | ☐ | ☐ | |
| 1.5 | Server certificate origin (installer-generated or customer-supplied) is documented in README | ☐ | ☐ | |
| 1.6 | No customer-specific hostnames or IPs leak into the diagram or README | ☐ | ☐ | |

---

## 2. Authentication model

| # | Question | Pass | Fail | Notes |
|---|----------|:----:|:----:|-------|
| 2.1 | Human users authenticate via **Casdoor OAuth 2.0 / OIDC**; no client-certificate user login | ☐ | ☐ | |
| 2.2 | JWT validation path (SEP App → Casdoor introspect) is drawn | ☐ | ☐ | |
| 2.3 | Refresh-token cookie (`HttpOnly`, `/api/oauth` scoped) is described in README if mentioned | ☐ | ☐ | |
| 2.4 | Machine-to-machine (SEP ↔ Nomad) is shown as **mTLS** with Nomad CA + client cert | ☐ | ☐ | |
| 2.5 | Internal certificate paths (`/app/ca.pem`, `/app/cert.pem`, `/app/key.pem`) are NOT exposed in the diagram | ☐ | ☐ | |
| 2.6 | Casdoor signing cert and seed organization (`sep`, application `sep-app`) come from `CASDOOR_INIT_JSON_DATA` blob — not hand-edited at runtime | ☐ | ☐ | |

---

## 3. Network boundaries

| # | Question | Pass | Fail | Notes |
|---|----------|:----:|:----:|-------|
| 3.1 | SEP controller host firewall opens TCP **4647 / 8443 / 8444 / 9999** (per SEP MS Playbook) and nothing else SEP-related | ☐ | ☐ | |
| 3.2 | Nomad RPC port **4647** is shown as the SEP-controller ↔ DB-host link | ☐ | ☐ | |
| 3.3 | DB Hosts are labeled "customer" — no implication that SEP installs the DB engine itself | ☐ | ☐ | |
| 3.4 | The PMM box is labeled **external (customer-controlled or Percona-operated)** — no PMM-bundled control plane in the diagram | ☐ | ☐ | |
| 3.5 | The Nomad cluster is labeled **external (customer-provided)** — no PMM-bundled Nomad in the diagram | ☐ | ☐ | |
| 3.6 | No internal SEP-team tools (PagerDuty, ServiceNow) appear without "Percona-internal / optional" framing — or they are omitted entirely | ☐ | ☐ | |

---

## 4. Task execution

| # | Question | Pass | Fail | Notes |
|---|----------|:----:|:----:|-------|
| 4.1 | Diagram states Nomad uses **`raw_exec` driver only** (no Docker driver, no `exec` driver) | ☐ | ☐ | |
| 4.2 | Dispatch direction is **Celery worker → Nomad cluster**, not the reverse | ☐ | ☐ | |
| 4.3 | Tasks API ↔ Nomad read-only path is shown OR explicitly omitted in README | ☐ | ☐ | |
| 4.4 | `check_nomad_cert_expiry` periodic task is mentioned (or the broader "TLS cert expiry alerts" capability is) so the customer knows operational alerts exist on this trust chain | ☐ | ☐ | |
| 4.5 | No diagram element implies SEP can run arbitrary shell on a DB host outside of Nomad agent payloads | ☐ | ☐ | |

---

## 5. Data plane and secrets

| # | Question | Pass | Fail | Notes |
|---|----------|:----:|:----:|-------|
| 5.1 | PostgreSQL is shown as **internal-only** (no host port published) | ☐ | ☐ | |
| 5.2 | Redis is shown as **internal-only**; broker password (`SEP_REDIS_PASSWORD`) origin documented | ☐ | ☐ | |
| 5.3 | The single Postgres instance is described as hosting SEP / Inventory / Tasks / beat schemas (multiple Alembic tracks) | ☐ | ☐ | |
| 5.4 | The `.secrets` file (mode 640, in install dir) is described as the long-lived secret store; secrets do not appear in the diagram | ☐ | ☐ | |
| 5.5 | Casdoor MariaDB-equivalent state volume (`casdoor-data`) is internal-only | ☐ | ☐ | |

---

## 6. External integrations

| # | Question | Pass | Fail | Notes |
|---|----------|:----:|:----:|-------|
| 6.1 | PMM ← Inventory API edge labeled **inventory sync (HTTPS)** | ☐ | ☐ | |
| 6.2 | PMM ← Celery worker edge labeled **execution annotations (HTTPS)** | ☐ | ☐ | |
| 6.3 | No PMM credential or API-key value appears in any artifact | ☐ | ☐ | |
| 6.4 | The optional bundled-PMM scenario (`CREATE_PMM_CONTAINER=1`) is explicitly out of scope in README, or the diagram visibly contradicts it | ☐ | ☐ | |

---

## 7. Boundary statements

| # | Question | Pass | Fail | Notes |
|---|----------|:----:|:----:|-------|
| 7.1 | Audit-log retention and PII filtering are deferred to **SEP-1220** with a visible cross-link | ☐ | ☐ | |
| 7.2 | Dynamic per-task data flow is deferred to **SEP-1215** with a visible cross-link | ☐ | ☐ | |
| 7.3 | Nomad driver / agent sandboxing detail is deferred to **SEP-1218** with a visible cross-link | ☐ | ☐ | |

---

## 8. Deliverable integrity

| # | Question | Pass | Fail | Notes |
|---|----------|:----:|:----:|-------|
| 8.1 | PDF was regenerated from the reviewed `.mmd` commit | ☐ | ☐ | |
| 8.2 | README code-mapping table spot-checked against installer blobs + origin/main | ☐ | ☐ | |
| 8.3 | Engineering lead has signed off below | ☐ | ☐ | |

---

## Sign-off

| Role | Name | Date | Signature / approval |
|------|------|------|----------------------|
| Security reviewer | | | |
| Engineering author | | | |
| Engineering lead | | | |
| Product / PM (optional) | | | |

**Approved for customer delivery:** ☐ Yes  ☐ No — follow-up required

**Follow-up actions (if any):**

1.
2.
