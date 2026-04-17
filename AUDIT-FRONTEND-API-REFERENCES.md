# Gateway Audit: Frontend-to-Backend API References

---

## Table of Contents

1. [Cascading Selectors — `/inventory-api/*`](#1-cascading-selectors--inventory-api)
2. [SSE Log Streaming — `/stream-logs/*`](#2-sse-log-streaming--stream-logs)
3. [File Listing and Download — `/files/*`](#3-file-listing-and-download--files)
4. [Execution Events — `/execution-events/*`](#4-execution-events)
5. [Periodic Task CRUD — `/periodic/*`](#5-periodic-task-crud--periodic)
6. [Task Stop — `/stop-task/*`](#6-task-stop--stop-task)
7. [Artifact Download — `/artifacts/*`](#7-artifact-download--artifacts)
8. [Alert Troubleshooting — Dynamic `baseUri`](#8-alert-troubleshooting--dynamic-baseuri)
9. [Alerts CRUD — `/alerts/*`](#9-alerts-crud--alerts)
10. [Additional Direct Route — `/alters/table/{id}/details`](#10-additional-direct-route--alterstableiddetails)

---

## Router Registration — `app/sep/main.py`

All proxy routes are conditionally registered in [app/sep/main.py](app/sep/main.py#L136) based on which plugins are enabled


### Quick Reference

| Prefix | Backend file | Purpose |
|---|---|---|
| **[`/inventory-api`](#1-cascading-selectors--inventory-api)** ([L136](app/sep/main.py#L136)) | `app/sep/api/routes.py` | Enabled if `alters`, `archives`, `tasks`, `backup`, `backup_mongo`, or `checksums` plugins are active |
| **[`/stream-logs`](#2-sse-log-streaming--stream-logs)** ([L137](app/sep/main.py#L137)) | `app/sep/routes/stream_logs.py` | Server-sent events (SSE): stream task logs and execution events in real time |
| **[`/files`](#3-file-listing-and-download--files)** ([L138](app/sep/main.py#L138)) | `app/sep/routes/download_files.py` | List and download task output files | 
| **[`/execution-events`](#4-execution-events)** ([L139](app/sep/main.py#L139)) | `app/sep/routes/execution_events.py` | Fetch full event logs for completed tasks | 
| **[`/periodic`](#5-periodic-task-crud--periodic)** ([L140](app/sep/main.py#L140)) | `app/sep/routes/periodic_tasks.py` | Create, read, update, delete scheduled (periodic) tasks | 
| **[`/stop-task`](#6-task-stop--stop-task)** ([L141](app/sep/main.py#L141)) | `app/sep/routes/stop_task.py` | Stop or cancel a running or pending task |
| **[`/artifacts`](#7-artifact-download--artifacts)** ([L145](app/sep/main.py#L146)) | `app/sep/routes/artifacts.py` | It is used to download artifact files. |

---

## 1. Cascading Selectors — `/inventory-api/*`

### Backend proxy — `app/sep/api/routes.py` (exposed at `/inventory-api`)

| Route | Method | Backend call | Description |
|---|---|---|---|
 | `/inventory-api/services/{service_id}/schemas` | `GET` | Inventory API `GET /services/{service_id}/schemas?` | Returns `[{id, name}]` list of schemas for a service|
| `/inventory-api/schemas/{schema_id}/tables` | `GET` | Inventory API `GET /schemas/{schema_id}/tables?` | Returns `[{id, name}]` list of tables for a schema |

### Shared JS utility — `static/js/schema-selector.js`

| Line | Function | HTTP method | URL pattern | Description |
|---|---|---|---|---|
| [#L26](https://github.com/percona/SEP/blob/main/static/js/schema-selector.js#L26) | `fetchSchemas(serviceId, search)` | `GET` | `/inventory-api/services/${serviceId}/schemas?search=...` | Fetches schema list for a service |
| [#L35](https://github.com/percona/SEP/blob/main/static/js/schema-selector.js#L35) | `fetchTables(schemaId, search)` | `GET` | `/inventory-api/schemas/${schemaId}/tables?search=...` | Fetches table list for a schema |

`fetchSchemas` and `fetchTables` are **shared utilities**; they are not called here directly but are exported to every template that loads this script. The calls below trace through to these two functions.

### Template call sites (all indirect via `schema-selector.js`)

| File | Line | Call | Context |
|---|---|---|---|
| `templates/alters/partials/create-form.html.j2` | [~L619](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L619) | `fetchSchemas(serviceId)` | Populate schema dropdown on service change |
| `templates/alters/partials/create-form.html.j2` | [~L664](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L664) | `fetchTables(schemaId)` | Populate table dropdown on schema change |
| `templates/alters/partials/create-form.html.j2` | [~L729](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L729) – [~L755](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L755) | `fetchSchemas(selectedService)` - `fetchTables(foundSchemaId)` | `checkTypedSchemaTable()` — manual input validation |
| `templates/alters/partials/edit-form.html.j2` | [~L655](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L655) | `fetchSchemas(serviceId)` | Same as create-form, on service change |
| `templates/alters/partials/edit-form.html.j2` | [~L707](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L707) | `fetchTables(schemaId)` | Same as create-form, on schema change |
| `templates/alters/partials/edit-form.html.j2` | [~L958](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L958) – [~L983](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L983) | `fetchSchemas(selectedServiceId)` - `fetchTables(matchedSchemaKey)` | `initSource()` — pre-populate selectors from existing task data |
| `templates/archiver/partials/create-form.html.j2` | [~L487](https://github.com/percona/SEP/blob/main/templates/archiver/partials/create-form.html.j2#L487) | `fetchSchemas(selectedService)` | Populate source schema dropdown |
| `templates/archiver/partials/create-form.html.j2` | [~L527](https://github.com/percona/SEP/blob/main/templates/archiver/partials/create-form.html.j2#L527) – [~L556](https://github.com/percona/SEP/blob/main/templates/archiver/partials/create-form.html.j2#L556) | `fetchTables(selectedSchema)` | `populateDestTables(selectedService, selectedSchema, selectedSourceTable)` - Populate source and destination table dropdowns |
| `templates/archiver/partials/edit-form.html.j2` | [~L584](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L584) | `fetchSchemas(selectedService)` | Same as create, plus pre-populate from existing task |
| `templates/archiver/partials/edit-form.html.j2` | [~L620](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L620) - [~L658](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L658) | `fetchTables()` | Source and destination table lists |
| `templates/archiver/partials/edit-form.html.j2` | [~L1075](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L1075) - [~L1080](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L1080) | `fetchSchemas(selectedServiceId)` / `fetchTables(foundSchema.id)` | `initSource()` |
| `templates/checksums/partials/create-form.html.j2` | [~L373](https://github.com/percona/SEP/blob/main/templates/checksums/partials/create-form.html.j2#L373) | `fetchSchemas(serviceId)` | Schema dropdown |
| `templates/checksums/partials/create-form.html.j2` | [~L399](https://github.com/percona/SEP/blob/main/templates/checksums/partials/create-form.html.j2#L399) | `fetchTables(schemaId)` | Table dropdown |
| `templates/checksums/partials/edit-form.html.j2` | [~L459](https://github.com/percona/SEP/blob/main/templates/checksums/partials/edit-form.html.j2#L459) | `fetchSchemas(serviceId)` | Schema dropdown |
| `templates/checksums/partials/edit-form.html.j2` | [~L509](https://github.com/percona/SEP/blob/main/templates/checksums/partials/edit-form.html.j2#L509) | `fetchTables(schemaId)` | Table dropdown |
| `templates/checksums/partials/edit-form.html.j2` | [~L645](https://github.com/percona/SEP/blob/main/templates/checksums/partials/edit-form.html.j2#L645) - [~L672](https://github.com/percona/SEP/blob/main/templates/checksums/partials/edit-form.html.j2#L672) | `fetchSchemas(selectedServiceId)` / `fetchTables(matchedSchemaKey)` | `initSource()` |
| `templates/backups/restore/partials/create-form.html.j2` | [~L576](https://github.com/percona/SEP/blob/main/templates/backups/restore/partials/create-form.html.j2#L576) - [~L666](https://github.com/percona/SEP/blob/main/templates/backups/restore/partials/create-form.html.j2#L666) | `fetchSchemas(serviceId)` / `fetchSchemas(singleHost)` | Destination schema dropdown (MyLoader restore only; no table lookup) |
| `templates/backups/restore/partials/edit-form.html.j2` | [~L725](https://github.com/percona/SEP/blob/main/templates/backups/restore/partials/edit-form.html.j2#L725) - [~L795](https://github.com/percona/SEP/blob/main/templates/backups/restore/partials/edit-form.html.j2#L795) | `fetchSchemas(selectedService)` - `fetchSchemas(selectedServiceId)`| `initSource()` |

**Proposed replacement:**  
Each plugin that needs cascading selectors should expose its own typed selector endpoints under `/api/plugins/{plugin-name}/`. A shared pattern (one endpoint per plugin) eliminates the cross-sub-app proxy. 

Example:

| Current URL | Proposed plugin endpoint |
|---|---|
| `GET /inventory-api/services/{id}/schemas` | `GET /api/plugins/{plugin-name}/schemas?service_id={id}&search=...` |
| `GET /inventory-api/schemas/{id}/tables` | `GET /api/plugins/{plugin-name}/tables?schema_id={id}&search=...` |

Where `{plugin-name}` is `alters`, `archiver`, `checksums`, or `restores` depending on the consuming template. 

If a shared selector component (SEP-968 `ServiceSelector` / `SchemaSelector` / `TableSelector`) is introduced, a single shared plugin route (e.g., `/api/plugins/inventory/schemas` and `/api/plugins/inventory/tables`) is an alternative.

---

## 2. SSE Log Streaming — `/stream-logs/*`

### Backend proxy — `app/sep/routes/stream_logs.py` (exposed at `/stream-logs`)

| Route | Method | Backend call | Description |
|---|---|---|---|
| `/stream-logs/{task_history_id}` | `GET` - SSE | Tasks API `GET /history/{id}/logs/` (streaming) then `POST /history/{id}/sync/` | Streams log lines; emits `finish` and `sep-error` SSE events |
| `/stream-logs/{task_history_id}/execution-events` | `GET` - SSE | Tasks API `GET /history/{id}/events` (polling loop) | Streams execution events for *running* tasks; emits `finish` on completion |

### Frontend call sites — `static/js/logs.js`

| Line | Mechanism | URL pattern | Trigger | Description |
|---|---|---|---|---|
| [~L498](https://github.com/percona/SEP/blob/main/static/js/logs.js#L498) | `new EventSource(...)` | `/stream-logs/${taskId}?${offsetQueryString}` | `.view-logs-button` [~L84](https://github.com/percona/SEP/blob/main/templates/tasks/partials/completed-tasks.html.j2#L84) - [~L51](https://github.com/percona/SEP/blob/main/templates/tasks/partials/running-tasks.html.j2#L51) | Opens SSE log stream for a task |
| [~L408](https://github.com/percona/SEP/blob/main/static/js/logs.js#L408) | `new EventSource(...)` | `/stream-logs/${encodeURIComponent(taskId)}/execution-events` | `fetchExecutionEventsIfNeeded()` when task status is `running` | Streams execution events in real time |

**Proposed replacement:**

| Current URL | Proposed plugin endpoint |
|---|---|
| `GET /stream-logs/{id}` (SSE) | `GET /api/plugins/task-manager/stream-logs/{id}` |
| `GET /stream-logs/{id}/execution-events` (SSE) | `GET /api/plugins/task-manager/stream-logs/{id}/execution-events` |

---

## 3. File Listing and Download — `/files/*`

### Backend proxy — `app/sep/routes/download_files.py` (exposed at `/files`)

| Route | Method | Backend call | Description |
|---|---|---|---|
| `/files/{task_history_id}` | GET (REST) | Tasks API `GET /history/{id}/files/` | Returns `dict[filename, FileMetadata]` |
| `/files/{task_history_id}/download` | GET (streaming) | Tasks API `GET /history/{id}/file/` (stream) | Streams file content; sets `Content-Disposition` header |

### Frontend call sites — `static/js/logs.js`

| Line | Mechanism | URL pattern | Trigger | Description |
|---|---|---|---|---|
| [~L621](https://github.com/percona/SEP/blob/main/static/js/logs.js#L621) | `fetch(...)` | `/files/${encodeURIComponent(taskId)}` | Inside `finish` SSE event handler | Lists files after task completes; populates file download modal |
| [~L44–L46](https://github.com/percona/SEP/blob/main/static/js/logs.js#L44) | helper `filesApiUrl()` | `/files/${encodeURIComponent(taskId)}` |  |  URL helpe |
| [~L88-L90](https://github.com/percona/SEP/blob/main/static/js/logs.js#L88) | helper `fileDownloadUrl()` | `/files/${encodeURIComponent(taskId)}/download?path=...` |  | URL helper |
| [~L218–L225](https://github.com/percona/SEP/blob/main/static/js/logs.js#L218) | `<a>` download trigger | `/files/${encodeURIComponent(taskId)}/download?path=...` | `.download-file-button` click handler | Triggers browser file download |

**Proposed replacement:**

| Current URL | Proposed plugin endpoint |
|---|---|
| `GET /files/{id}` | `GET /api/plugins/task-manager/files/{id}` |
| `GET /files/{id}/download?path=...` | `GET /api/plugins/task-manager/files/{id}/download?path=...` |

---
## 4. Execution Events

### Backend proxy — `app/sep/routes/execution_events.py` (exposed at `/execution-events`)

| Route | Method | Backend call | Description |
|---|---|---|---|
| `/execution-events/{task_history_id}` | GET (REST) | Tasks API `GET /history/{id}/events` | Returns full event list for *completed* tasks as JSON array |

### Frontend call sites — `static/js/logs.js`

| Line | Mechanism | URL pattern | Trigger | Description |
|---|---|---|---|---|
| [~L451](https://github.com/percona/SEP/blob/main/static/js/logs.js#L451) | `fetch(...)` | `/execution-events/${encodeURIComponent(taskId)}` | `fetchExecutionEventsIfNeeded()` when task status is NOT `running` | Fetches the full event list once for a completed task |

**Proposed replacement:**

| Current URL | Proposed plugin endpoint |
|---|---|
| `GET /execution-events/{id}` | `GET /api/plugins/task-manager/execution-events/{id}` |

---

## 5. Periodic Task CRUD — `/periodic/*`

### Backend proxy — `app/sep/routes/periodic_tasks.py` (exposed at `/periodic`)

| Route | Method | Backend call | Description |
|---|---|---|---|
| `/periodic/` | `POST` | Tasks API `POST /{task_name}/periodic/` | Creates periodic task |
| `/periodic/{periodic_task_id}/delete` | `DELETE` | Tasks API `DELETE /periodic/{id}` | Deletes periodic task |
| `/periodic/{periodic_task_id}/update` | `GET` + `PUT` | Tasks API `GET /periodic/{id}` + `PUT /periodic/{id}` | Updates periodic task (full read-modify-write) |

### Frontend call sites (server-rendered via `url_for()` in Jinja2)

The periodic task routes are consumed as standard HTML form `action` attributes. They are **not** called via `fetch` or `XMLHttpRequest`; instead the browser submits the form directly. The URL is resolved server-side by Jinja2's `url_for()`.

| File | Line | Jinja2 expression | HTTP method | Description |
|---|---|---|---|---|
| `templates/tasks/partials/scheduled-tasks.html.j2` | [~L19](https://github.com/percona/SEP/blob/main/templates/tasks/partials/scheduled-tasks.html.j2#L19) | `url_for('periodic_task_create')` | `POST` | New periodic task form action |
| `templates/tasks/partials/scheduled-tasks.html.j2` | [~L25](https://github.com/percona/SEP/blob/main/templates/tasks/partials/scheduled-tasks.html.j2#L25) | `url_for('periodic_task_update', periodic_task_id=periodic_task.id)` | `PUT` | Edit periodic task form action |
| `templates/tasks/partials/scheduled-tasks.html.j2` | [~L82](https://github.com/percona/SEP/blob/main/templates/tasks/partials/scheduled-tasks.html.j2#L82) | `url_for('periodic_task_update', periodic_task_id=periodic_task.id)` | `PUT` | Enable/disable toggle form action |
| `templates/tasks/partials/scheduled-tasks.html.j2` | [~L105](https://github.com/percona/SEP/blob/main/templates/tasks/partials/scheduled-tasks.html.j2#L105) | `url_for('periodic_task_delete', periodic_task_id=periodic_task.id)` | `DELETE` | Delete form action |
| `templates/homepage/scheduled-tasks.html.j2` | [~L20](https://github.com/percona/SEP/blob/main/templates/homepage/scheduled-tasks.html.j2#L20) | `url_for('periodic_task_create')` | `POST` | New periodic task form action (homepage widget) |

**Proposed replacement:**  
Under the gateway pattern, the React frontend would replace these forms with typed API calls:

| Current URL (server-rendered) | Proposed plugin endpoint |
|---|---|
| `POST /periodic/` | `POST /api/plugins/task-manager/periodic/` |
| `PUT /periodic/{id}/update` | `PUT /api/plugins/task-manager/periodic/{id}` |
| `DELETE /periodic/{id}/delete` | `DELETE /api/plugins/task-manager/periodic/{id}` |

---

## 6. Task Stop — `/stop-task/*`

### Backend proxy — `app/sep/routes/stop_task.py` (exposed at `/stop-task`)

| Route | Method | Backend call | Description |
|---|---|---|---|
| `/stop-task/{task_history_id}` | `POST` | Tasks API `POST /history/{id}/stop/` | Stops or cancels a task execution; redirects to Referer |

### Frontend call sites (server-rendered via `url_for()` in Jinja2)

These are HTML form submissions, not AJAX.

| File | Line | Jinja2 expression | HTTP method | Description |
|---|---|---|---|---|
| `templates/tasks/partials/running-tasks.html.j2` | [~L62](https://github.com/percona/SEP/blob/main/templates/tasks/partials/running-tasks.html.j2#L62) | `url_for("stop_task_execution", task_history_id=task.id)` | `POST` | Stop button for running tasks |
| `templates/tasks/partials/pending-tasks.html.j2` | [~L46](https://github.com/percona/SEP/blob/main/templates/tasks/partials/pending-tasks.html.j2#L46) | `url_for('stop_task_execution', task_history_id=task['id'])` | `POST` | Cancel button for pending tasks |

**Proposed replacement:**

| Current URL (server-rendered) | Proposed plugin endpoint |
|---|---|
| `POST /stop-task/{id}` | `POST /api/plugins/task-manager/stop-task/{id}` |

---
## 7. Artifact Download — `/artifacts/*`

### Backend — `app/sep/routes/artifacts.py` (exposed at `/artifacts`)

| Route | Method | Backend call | Description |
|---|---|---|---|
| `/artifacts/download/{token}` | GET | Local filesystem | Serves a local file identified by a signed, time-limited token; used by snippets and dipper payloads |

**Note:** This route does **not** proxy to a sub-app. It reads from local directories: `snippets_settings.SNIPPETS_DIR` and `DIPPER_PAYLOADS_DIR`. The token is validated via `crypto_timestamp_serializer` before serving.


**Proposed replacement:** 

| Current URL | Proposed plugin endpoint |
|---|---|
| `GET /artifacts/download/{token}` | `GET /api/plugins/snippets/artifacts/download/{token}` |

---

## 8. Alert Troubleshooting — Dynamic `baseUri`

### Frontend call sites — `static/js/troubleshooting-detail.js`

| Line | Mechanism | URL pattern | HTTP method | Description |
|---|---|---|---|---|
| [~L93](https://github.com/percona/SEP/blob/main/static/js/troubleshooting-detail.js#L93) | `fetch(baseUri + '/output/' + encodeURIComponent(taskId), { credentials: 'include' })` | `{baseUri}/output/${encodeURIComponent(taskId)}` | `GET` | Polls task output (stdout/stderr + status) during snippet execution |
| [~L152](https://github.com/percona/SEP/blob/main/static/js/troubleshooting-detail.js#L152) | `fetch(form.action, { method: 'POST', body: formData, credentials: 'include' })` | `form.action` | `POST` | Submits snippet execution; form action is set by the server in the template |

**Proposed replacement:**  
Under the gateway pattern, the replacement would be:

| Current URL pattern | Proposed plugin endpoint |
|---|---|
| `GET {baseUri}/output/{taskId}` | `GET /api/plugins/troubleshooting/output/{taskId}` |
| `POST {form.action}` | `POST /api/plugins/troubleshooting/run/{snippetId}`  |

---

## 9. Alerts CRUD — `/alerts/*`

### Frontend call sites — `static/js/alerts.js`

These routes are **already plugin-level** routes (alerts plugin), not sub-app proxies. They are documented here for completeness as required by the ticket.

| Line | Mechanism | URL | HTTP method | Description |
|---|---|---|---|---|
| [~L159](https://github.com/percona/SEP/blob/main/static/js/alerts.js#L159) | `fetch('/alerts/push', { method: 'POST', body: formData })` | `/alerts/push` | `POST` | Pushes selected alert templates to PMM; `multipart/form-data` with `selected_templates[]` and CSRF token |
| [~L362](https://github.com/percona/SEP/blob/main/static/js/alerts.js#L362) | `fetch('/alerts/pagerduty', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: formData })` | `/alerts/pagerduty` | `POST` | Creates or updates PagerDuty integration; `multipart/form-data` with `integration_key` |
| [~L396](https://github.com/percona/SEP/blob/main/static/js/alerts.js#L396) | `fetch('/alerts/pagerduty/delete', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: formData })` | `/alerts/pagerduty/delete` | `POST` | Deletes PagerDuty integration |
| [~L467](https://github.com/percona/SEP/blob/main/static/js/alerts.js#L467) | `fetch('/alerts/backups/' + backupId)` | `/alerts/backups/${backupId}` | `GET` | Fetches backup detail (templates, rules, contact points, folders, notification policy) |
| [~L577](https://github.com/percona/SEP/blob/main/static/js/alerts.js#L577) | `fetch('/alerts/restore', { method: 'POST', body: formData, headers: { 'X-CSRF-Token': csrfToken } })` | `/alerts/restore` | `POST` | Restores alerts from a backup; `multipart/form-data` with `backup_id` |

**Proposed replacement:**

| Current URL | Proposed plugin endpoint |
|---|---|
| `POST /alerts/push` | `POST /api/plugins/alerts/push` |
| `POST /alerts/pagerduty` | `POST /api/plugins/alerts/pagerduty` |
| `POST /alerts/pagerduty/delete` | `DELETE /api/plugins/alerts/pagerduty` |
| `GET /alerts/backups/{id}` | `GET /api/plugins/alerts/backups/{id}` |
| `POST /alerts/restore` | `POST /api/plugins/alerts/restore` |

---

## 10. Additional Direct Route — `/alters/table/{id}/details`

| File | Line | URL | HTTP method | Description |
|---|---|---|---|---|
| `templates/alters/partials/create-form.html.j2` | [~L815](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L815) | ``/alters/table/${tableId}/details?syntax_highlight_style=monokai`` | GET | Fetches `CREATE TABLE` SQL and key information for a specific table (alters plugin) |
| `templates/alters/partials/edit-form.html.j2` | [~L872](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L872) | ``/alters/table/${tableId}/details?syntax_highlight_style=monokai`` | GET | Same as above, in edit form |

**Proposed replacement:** 

| Current URL | Proposed plugin endpoint |
|---|---|
| `GET /alters/table/{id}/details` | `GET /api/plugins/alters/table/{id}/details?syntax_highlight_style=monokai` |
