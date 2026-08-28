# SEP User Guide

A customer-facing introduction to the **Services Enablement Platform (SEP)** and a short
description of every app: what it is for and what it runs on your database hosts.

## Contents

- [What is SEP?](#what-is-sep)
- [How SEP works](#how-sep-works)
- [Apps](#apps)
  - [Inventory](#inventory)
  - [Snippet Manager](#snippet-manager)
  - [Support diagnostics (ATW)](#support-diagnostics-atw)
  - [Schema Change](#schema-change)
  - [Archive](#archive)
  - [MySQL Backups](#mysql-backups)
  - [Checksums](#checksums)
  - [MongoDB Backups](#mongodb-backups)
  - [PostgreSQL Backups](#postgresql-backups)
  - [Dipper Data Collection](#dipper-data-collection)
  - [Alert Templates](#alert-templates)
  - [Alert Troubleshooting](#alert-troubleshooting)
  - [Health & Security Report](#health--security-report)
  - [Task Manager](#task-manager)
  - [Internal components](#internal-components)
- [Common concepts](#common-concepts)

## What is SEP?

SEP (Services Enablement Platform) is a modular web platform that lets Percona engineers and DBAs run standardized  database operations — backups, schema changes, consistency checks, diagnostics, and alerting — against different database technologies from a single interface. Instead of running ad-hoc commands by hand on each host, operators pick a service from an inventory and trigger a well-defined action, while SEP records who ran what, when, and with which result.

SEP is **app-based**: each capability (backups, schema changes, diagnostics, etc.) is a
separate app that adds its own UI and API. Which apps are available is controlled by
the `APPS` (and `TASKS.APPS`) sections of `settings.yaml`, so a deployment can enable
only the apps it needs.

## How SEP works

At a high level:

1. **Sign in.** Users authenticate through Casdoor (OAuth 2.0 / OIDC).
2. **Browse inventory.** SEP keeps an inventory of nodes, services, schemas, and tables,
  typically synced from PMM. Operators select the service they want to act on.
3. **Run an app action.** When an operator triggers an action, SEP dispatches a job to a
  **Nomad** agent that runs on (or close to) the target database host using the `raw_exec`
   driver. The command runs there, and the output and logs are captured back in SEP for
   review and history.
4. **Review results.** Task status, logs, and artifacts are stored and viewable in SEP.

Some apps (alerting and reporting) do not run a command on a database host at all — they
talk to the PMM HTTP API instead.

For deeper technical detail on the deployment topology and per-task data flow, see the
companion customer docs:

- [SEP Task Execution — Data Flow](../sep-task-execution-dfd/README.md)

## Apps

Each entry below lists the app's purpose and the command or tool it executes on the
target host (or notes when it uses an API instead).

### Inventory

**Purpose:** Manage the catalog of nodes, services, schemas, and tables that every other
app acts on.

Inventory lets you browse nodes and services, synchronize the catalog from external
sources (such as PMM), and schedule recurring syncs. The syncers author the catalog and
you read it here: PMM supplies nodes and services, and the MySQL syncer discovers schemas
and tables from the database itself. From a service's detail page you can run a quick
connectivity check for MySQL, PostgreSQL, and MongoDB services.

**What it runs:** an `inventory-sync` background job (runs syncer code on the SEP worker, not
on a database host) and a connectivity check dispatched as a Nomad `run-python` task that
performs a simple `SELECT 1`-style probe using `pymysql` / `psycopg2` / `pymongo`.

**Root requirements:** No

### Snippet Manager

**Purpose:** A catalog of approved, reusable bash and Python diagnostic scripts ("snippets")
that operators can run on a chosen host.

Operators browse, preview, and (for admins) approve snippets, then execute them against an
executor host. Execution history and downloadable artifacts are tracked for each run.

**What it runs:** the selected snippet script itself, dispatched as a Nomad `exec-artifact`
task (bash, via `bash`) or `exec-python-artifact` task (Python, via `python3`).

**Root requirements:** per snippet

### Support diagnostics (ATW)

**Purpose:** Organize approved snippets into a guided taxonomy of troubleshooting scenarios
(for example crashes, performance, replication / HA) grouped by database type.

ATW (Advanced Troubleshooting Wizard) is a navigation layer over Snippet Manager: it helps
operators find the right diagnostic script for a situation and run it.

**What it runs:** nothing of its own — execution is delegated to Snippet Manager, using the
same `exec-artifact` / `exec-python-artifact` tasks.

**Root requirements:** per snippet

### Schema Change

**Purpose:** Apply online MySQL schema changes (`ALTER`s) to a table without blocking reads
and writes.

SEP builds the command from your `ALTER` statement, the target table, and replica-discovery
settings. Creating a change also stores a **dry-run** variant and a **pre-checks** step
(disk space, foreign keys, triggers, etc.) so you can validate before executing for real.

**What it runs:** `**pt-online-schema-change`** (Percona Toolkit), with `--execute` for the
real run and `--dry-run` for the dry-run sibling. The pre-checks step runs a Python script.

**Root requirements:** No

### Archive

**Purpose:** Purge or archive rows from MySQL tables that match a `WHERE` clause.

Use it to delete old data, export rows to a file, or copy rows into another table, with
optional "swap-and-drop" workflows for reclaiming space.

**What it runs:** `**pt-archiver`** (Percona Toolkit) for the purge/archive path, plus
`mysql` and `mysqldump` for the swap-and-drop variants.

**Root requirements:** no

### MySQL Backups

**Purpose:** Schedule and run MySQL/MariaDB backups against inventory services.

Each backup task selects one method and can encrypt and upload results (rsync, S3, or Google
Cloud Storage). Supports logical dumps, physical hot backups (full and incremental), and
continuous binary-log capture.

**What it runs:**

- **Mydumper** — `**mydumper`** for logical SQL dumps.
- **XtraBackup** — `**xtrabackup`**, `**mariadb-backup`**, or `**innobackupex**` for physical
hot backups (with optional prepare, compression, and verification).
- **Binlog** — `**mysqlbinlog`** for continuous remote binary-log capture.

**Root requirements:** XtraBackup only

### Checksums

**Purpose:** Verify MySQL replication consistency between a primary and its replicas.

SEP scopes the check to selected databases/tables and configures how replicas are
discovered, then reports any data drift.

**What it runs:** `**pt-table-checksum`** (Percona Toolkit). Use `--explain` mode to preview
without running.

**Root requirements:** no

### MongoDB Backups

**Purpose:** Manage Percona Backup for MongoDB (PBM) backups and configuration.

Creating a backup configuration typically also sets up logical, physical, and status
operations. Storage, point-in-time recovery, and compression are applied through PBM's
configuration.

**What it runs:** `**pbm backup`** (`--type logical` or `--type physical`), `**pbm config`**
to apply storage/PITR settings, and `**pbm status`** to report state. Requires PBM CLI and a
MongoDB connection URI configured on the target node (see the app's
[README](../../../app/sep/apps/backup_mongo/README.md) for prerequisites).

**Root requirements:** no

### PostgreSQL Backups

> [!NOTE]
> This app is present in SEP but is **not enabled by default**. To use it, add it to the
> `APPS` section of `settings.yaml`.

**Purpose:** Run pgBackRest backups for PostgreSQL inventory services.

Supports full, incremental, and differential backups with configurable retention. The task
can create the stanza configuration and validate it before backing up.

**What it runs:** `**pgbackrest`** — `pgbackrest check` and `pgbackrest stanza-create` as
needed, then `**pgbackrest backup`** with `--type=full`, `--type=incr`, or `--type=diff`.

**Root requirements:** Yes

### Dipper Data Collection

**Purpose:** Run Percona "PCS collect" diagnostic scripts to gather environment and PMM-graph
data from a service, then archive the results and show execution history.

Environment collection is available for MySQL, MongoDB, and PostgreSQL; PMM-graph collection
is MySQL-only.

**What it runs:** the PCS collect scripts —
`pcs-collect-environment-mysql.sh`, `pcs-collect-environment-mongo.sh`,
`pcs-collect-environment-pgsql.sh` (via `exec-artifact` / `bash`), and
`pcs-collect-pmm-mysql.py` (via `exec-python-artifact` / `python3`).

**Root requirements:** Yes for complete results

### Alert Templates

**Purpose:** Manage PMM alert rules and notification routing.

Operators push curated alert templates (for example high CPU, slow queries, replica lag)
into PMM as rules, configure PagerDuty contact points, and restore from saved snapshots of
the alert configuration.

**What it runs:** no command on a database host — all operations are PMM HTTP API calls. A
periodic background job backs up the PMM alert configuration.

**Root requirements:** No

### Alert Troubleshooting

**Purpose:** Connect firing alerts to the diagnostic snippets that help investigate them.

Alerts are grouped by database service type, and each is linked to approved support snippets
so operators can move from "an alert fired" to "run the right diagnostic" in one place.

**What it runs:** nothing of its own — it executes the linked snippets through Snippet
Manager (`exec-artifact` / `exec-python-artifact`).

**Root requirements:** per snippet

### Health & Security Report

**Purpose:** Generate a PMM Health and Security Report for a chosen time window.

The report aggregates advisors, alerts, backups, disk usage, uptime, and inventory from PMM
and renders an HTML/PDF document, which can optionally be uploaded to ServiceNow.

**What it runs:** no command on a database host — it uses the PMM API and generates the PDF
locally.

**Root requirements:** No

## Common concepts

A few ideas apply across most apps:

- **Executor host.** Actions that run a command are dispatched to a Nomad agent on (or near)
the target host. For remote databases (such as RDS/DBaaS) you select which executor host
can reach the database.
- **Credentials live on the host.** The commands read database credentials from files on the
Nomad client — for example `~/.my.cnf` / `~/.mylogin.cnf` for MySQL tools and a MongoDB URI
file for PBM — rather than from SEP itself.
- **History and logs.** Every dispatched task records its status, logs, and any artifacts, so
you can review past runs and download their output from SEP.
