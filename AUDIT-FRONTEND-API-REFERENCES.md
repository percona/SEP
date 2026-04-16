# Gateway Audit: Frontend-to-Backend API References

---

## Table of Contents

1. [Cascading Selectors — `/inventory-api/*`](#1-cascading-selectors--inventory-api)
2. [SSE Log Streaming — `/stream-logs/*`](#2-sse-log-streaming--stream-logs)
3. [Execution Events — `/execution-events/*` and `/stream-logs/*/execution-events`](#3-execution-events)
4. [File Listing and Download — `/files/*`](#4-file-listing-and-download--files)


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
| `templates/alters/partials/create-form.html.j2` | [~L618](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L618) | `fetchSchemas(serviceId)` | Populate schema dropdown on service change |
| `templates/alters/partials/create-form.html.j2` | [~L663](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L663) | `fetchTables(schemaId)` | Populate table dropdown on schema change |
| `templates/alters/partials/create-form.html.j2` | [~L728](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L728) – [~L754](https://github.com/percona/SEP/blob/main/templates/alters/partials/create-form.html.j2#L754) | `fetchSchemas(selectedService)` - `fetchTables(foundSchemaId)` | `checkTypedSchemaTable()` — manual input validation |
| `templates/alters/partials/edit-form.html.j2` | [~L655](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L655) | `fetchSchemas(serviceId)` | Same as create-form, on service change |
| `templates/alters/partials/edit-form.html.j2` | [~L707](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L707) | `fetchTables(schemaId)` | Same as create-form, on schema change |
| `templates/alters/partials/edit-form.html.j2` | [~L958](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L958) – [~L983](https://github.com/percona/SEP/blob/main/templates/alters/partials/edit-form.html.j2#L983) | `fetchSchemas(selectedServiceId)` - `fetchTables(matchedSchemaKey)` | `initSource()` — pre-populate selectors from existing task data |
| `templates/archiver/partials/create-form.html.j2` | [~L486](https://github.com/percona/SEP/blob/main/templates/archiver/partials/create-form.html.j2#L486) | `fetchSchemas(selectedService)` | Populate source schema dropdown |
| `templates/archiver/partials/create-form.html.j2` | [~L526](https://github.com/percona/SEP/blob/main/templates/archiver/partials/create-form.html.j2#L526) – [~L556](https://github.com/percona/SEP/blob/main/templates/archiver/partials/create-form.html.j2#L556) | `fetchTables(selectedSchema)` | `populateDestTables(selectedService, selectedSchema, selectedSourceTable)` - Populate source and destination table dropdowns |
| `templates/archiver/partials/edit-form.html.j2` | [~L584](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L584) | `fetchSchemas(selectedService)` | Same as create, plus pre-populate from existing task |
| `templates/archiver/partials/edit-form.html.j2` | [~L620](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L620) - [~L658](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L658) | `fetchTables()` | Source and destination table lists |
| `templates/archiver/partials/edit-form.html.j2` | [~L1075](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L1075) - [~L1080](https://github.com/percona/SEP/blob/main/templates/archiver/partials/edit-form.html.j2#L1080) | `fetchSchemas(selectedServiceId)` / `fetchTables(foundSchema.id)` | `initSource()` |
| `templates/checksums/partials/create-form.html.j2` | [~L372](https://github.com/percona/SEP/blob/main/templates/checksums/partials/create-form.html.j2#L372) | `fetchSchemas(serviceId)` | Schema dropdown |
| `templates/checksums/partials/create-form.html.j2` | [~L398](https://github.com/percona/SEP/blob/main/templates/checksums/partials/create-form.html.j2#L398) | `fetchTables(schemaId)` | Table dropdown |
| `templates/checksums/partials/edit-form.html.j2` | [~L459](https://github.com/percona/SEP/blob/main/templates/checksums/partials/edit-form.html.j2#L459) | `fetchSchemas(serviceId)` | Schema dropdown |
| `templates/checksums/partials/edit-form.html.j2` | [~L509](https://github.com/percona/SEP/blob/main/templates/checksums/partials/edit-form.html.j2#L509) | `fetchTables(schemaId)` | Table dropdown |
| `templates/checksums/partials/edit-form.html.j2` | [~L645](https://github.com/percona/SEP/blob/main/templates/checksums/partials/edit-form.html.j2#L645), [~L672](https://github.com/percona/SEP/blob/main/templates/checksums/partials/edit-form.html.j2#L672) | `fetchSchemas(selectedServiceId)` / `fetchTables(matchedSchemaKey)` | `initSource()` |
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
| `/stream-logs/{task_history_id}` | GET - SSE | Tasks API `GET /history/{id}/logs/` (streaming) then `POST /history/{id}/sync/` | Streams log lines; emits `finish` and `sep-error` SSE events |
| `/stream-logs/{task_history_id}/execution-events` | GET (SSE) | Tasks API `GET /history/{id}/events` (polling loop) | Streams execution events for *running* tasks; emits `finish` on completion |

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

## 3. Execution Events

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

## 4. File Listing and Download — `/files/*`

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
