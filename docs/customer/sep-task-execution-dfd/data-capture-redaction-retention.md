# SEP Task Execution Data Capture, Redaction, Access, and Retention

This document describes what SEP captures during task execution, how SEP handles sensitive data in captured output, who can access that output, and what retention behavior exists in the current implementation.

## Scope

This document covers data produced by predefined SEP task executions, including app-driven tasks, snippets, and Nomad-backed jobs. It focuses on stdout/stderr task logs, task execution metadata, and downloadable task output files.

SEP task execution is not a free-form shell. Users select approved snippets or app-defined operations, and the server builds the execution request from stored task definitions, validated form data, and inventory context. Even with predefined execution, command parameters and task output can contain sensitive information.

## Audit Logging

SEP records a task history entry for every task execution request. The task history entry is the primary audit record for the execution and includes:

- The executing user identity in `taskhistory.executed_by`.
- `SYSTEM` or the internal service principal for system-initiated or scheduled flows.
- Creation, start, and finish timestamps through `created_at`, `started_at`, and `finished_at`.
- Execution status, such as pending, running, success, failed, lost, or stale.
- The execution request JSON, including the task name, target, execution metadata, payload, ETA, and executor tracking information.
- Command context, including the fixed task or app command metadata used to dispatch the job.
- Execution lifecycle information derived from Nomad task state and exposed through the execution events API.
- Captured stdout and stderr chunks in the task log store.

For Nomad-backed executions, SEP captures stdout and stderr from the allocation log streams and persists the fetched content as task history log chunks. Logs are split by execution step and stream type (`stdout` or `stderr`). While a task is running, SEP can stream logs from Nomad; after completion, SEP serves persisted log chunks from the Tasks database.

Application and infrastructure logs are separate from task execution logs. They may include request context such as request ID, correlation ID, and authenticated user, but they are not the system of record for task stdout/stderr.

## PII Filtering

SEP has an optional anonymization filter for task logs and task output files. The filter is implemented with Microsoft Presidio:

- Presidio Analyzer detects configured entities.
- A spaCy NLP model is used for natural-language detection. The default configured model is `en_core_web_sm`.
- Presidio Anonymizer replaces detected entities with Presidio replacement tokens.
- SEP controls which entity categories are enabled through an integer `anonymize_mask` on tasks and task history records.
- If a task does not set an explicit mask, SEP can use the configured default entities from `TASKS.ANONYMIZER.DEFAULT_ENTITIES`.

The current default settings file configures `TASKS.ANONYMIZER.DEFAULT_ENTITIES` to the following high-confidence set when a task or execution does not override the mask:

- `CREDIT_CARD`
- `EMAIL_ADDRESS`
- `IBAN_CODE`
- `IP_ADDRESS`
- `PHONE_NUMBER`
- `US_SSN`
- `US_ITIN`

These are checksum-validated or strong-regex recognizers suited to database-tool logs (DSN strings, DDL, row counts, offsets, LSNs, and GTIDs). The following supported entities are intentionally excluded from the shipped default because they corrupt operational detail or collide with numeric tool output:

- `PERSON`, `LOCATION`, and `NRP` (spaCy NER) misread hostnames, `schema.table` names, column names, and tool names as people or places.
- `US_BANK_NUMBER`, `US_PASSPORT`, `US_DRIVER_LICENSE`, and `MEDICAL_LICENSE` are loose numeric patterns that collide with row counts, byte offsets, LSNs, and GTIDs.

The `development:` profile overrides `DEFAULT_ENTITIES` to an empty list so local task-log and pulled-file reads perform no anonymization. Existing or explicitly configured tasks can still set `anonymize_mask` to `0`, which disables anonymization for that task. Any of the fourteen SEP-supported entities below can be restored through `settings.yaml` or a runtime settings override without a code change.

SEP-supported PII entity categories are:

- `CREDIT_CARD`
- `EMAIL_ADDRESS`
- `IBAN_CODE`
- `IP_ADDRESS`
- `NRP`
- `LOCATION`
- `PERSON`
- `PHONE_NUMBER`
- `MEDICAL_LICENSE`
- `US_BANK_NUMBER`
- `US_DRIVER_LICENSE`
- `US_ITIN`
- `US_PASSPORT`
- `US_SSN`

For Nomad log capture, anonymization is applied to the task output text SEP reads from the `run-script` or `step1` execution steps before it is persisted to the task log chunk store. For downloadable text output files, SEP attempts to decode file bytes as text and applies the same anonymization before streaming the file to the requester. If file content cannot be decoded as text, SEP streams the raw bytes.

### Limitations

The anonymization filter is best-effort detection, not a formal data loss prevention guarantee.

- Presidio uses a mix of pattern recognizers, checksums, context, and NLP depending on the entity. It is not a full custom ML classifier for every possible sensitive value.
- Detection quality depends on the configured language model, the enabled entity categories, and the surrounding text.
- Values outside the configured entity list are not intentionally detected.
- Binary files, encoded payloads, compressed data, screenshots, archives, and values split across chunks may not be redacted.
- Some technical identifiers can be over-redacted or under-redacted depending on context.
- The filter is applied only at log-capture time (for the Nomad `run-script` and `step1` execution steps) and at file-download time. It does not retroactively redact data already stored without anonymization. Prestart, poststart, and other Nomad step types are not anonymized.

## Secrets in Output

If a password, API key, token, private key, or other secret appears in stdout or stderr, SEP does not provide a dedicated secret-scanning engine for all secret formats. Redaction is automatic only when the value is detected by the enabled Presidio entity categories. Many secret formats, including arbitrary API keys, bearer tokens, connection strings, JWTs, SSH keys, cloud credentials, and vendor-specific tokens, are not guaranteed to match those PII categories.

Therefore, secret redaction in task output should be treated as best effort. Task authors should avoid printing secrets, should pass sensitive values through secure execution mechanisms where available, and should scrub command output at the source when a tool may echo credentials.

## Output Storage

SEP stores task execution records in the Tasks database. In production deployments, this is PostgreSQL. Development defaults may use SQLite.

Captured stdout and stderr are stored in the `taskhistory_log` table as append-only chunks associated with a `taskhistory` row. Each chunk records:

- The task history ID.
- The execution step that produced the output.
- The stream type (`stdout` or `stderr`).
- Start and end offsets.
- The chunk content.

SEP stores log chunk content append-only in a binary database column. Each chunk is either raw UTF-8 bytes or deflate-compressed UTF-8 bytes, depending on size and compressibility. This is compression, not encryption.

SEP also maintains `taskhistory_log_state` rows for per-stream staging buffers and offsets while logs are being collected. Legacy task history rows may still contain older compressed log blobs under the execution tracking data; SEP can read those during migration compatibility paths.

Task output files are different from stdout/stderr logs. When a task declares an output files path, SEP lists or streams those files from the Nomad allocation filesystem through the Nomad client filesystem API. SEP does not copy those files into the task log chunk table as part of the normal file download path.

### Encryption at Rest

SEP application code does not encrypt task output before writing it to the Tasks database. At-rest protection for task logs depends on the storage system and deployment configuration, such as PostgreSQL volume encryption, host disk encryption, backup encryption, and access controls around database backups.

Similarly, output files that remain in Nomad allocation storage are protected by the Nomad host and filesystem controls configured for the environment. SEP may anonymize text files while streaming them to a requester, but that does not encrypt or rewrite the source file in Nomad allocation storage.

## Access to Output

Task history and task logs are exposed through authenticated Tasks API endpoints.

In the current implementation:

- Any authenticated OAuth user can list task history.
- Any authenticated OAuth user can retrieve task history by ID.
- Any authenticated OAuth user can stream stdout/stderr logs for a task history ID.
- Any authenticated OAuth user can list or stream configured output files for a finished task history ID.
- The configured `SEP_INTERNAL_TOKEN` service principal can also authenticate to these APIs for internal service-to-service calls.
- General task history and log APIs do not apply a per-user `executed_by` row filter.

SEP does distinguish admin users for some operations, such as snippet approval and certain administrative routes, but task log viewing is not currently restricted to admin users only.

Customer access depends on deployment and identity configuration. The current SEP application has no built-in customer-tenant identity model. If customer users are provisioned in Casdoor as authenticated SEP users, they can see all task history and logs that any other authenticated user can see — there is no per-customer or per-tenant row filter. The standard deployment pattern is that customers are not provisioned in SEP, and the SEP UI is reachable only by Percona personnel.

Access is controlled by:

- Casdoor OAuth/JWT authentication for human users. The React SPA carries a Casdoor-issued access token as an `Authorization: Bearer` header; the refresh token is held by the browser as an `HttpOnly` cookie scoped to `/api/oauth`. Legacy Jinja2 routes (during the API-First migration window) carry a signed session cookie; those routes also require a CSRF token.
- Optional internal bearer-token authentication through `SEP_INTERNAL_TOKEN` for service-to-service calls.
- Transport security, including HTTPS at the Nginx ingress and configured service-to-service TLS/mTLS for SEP↔Tasks/Inventory and Tasks↔Nomad.
- Deployment-level controls around network access, database access, Nomad API access, and infrastructure log access.

The current application does not implement customer-specific log tenancy or role-based filtering for task stdout/stderr logs.

## Retention and Deletion

SEP currently does not define a time-based retention policy for completed task history or captured stdout/stderr logs in application code. Completed task history rows and associated `taskhistory_log` chunks remain in the Tasks database until they are explicitly deleted or the underlying database, backup, or environment retention policy removes them.

When a `TaskHistory` row is deleted, related `taskhistory_log` and `taskhistory_log_state` rows are configured with cascading foreign keys and are deleted with that task history row.

Deletion paths in the current implementation are limited:

- A pending task history can be deleted when a user stops it before it starts running.
- An expired pending Celery dispatch can delete its `TaskHistory` row.
- There is no general scheduled purge job for completed task histories based on age.
- There is no application-level end-of-retention workflow that anonymizes, tombstones, exports, or proves deletion of completed task output.

Nomad allocation files follow Nomad/client host retention and garbage-collection behavior, not a SEP task-log retention setting. Infrastructure logs and database backups follow their own deployment-specific retention policies.

For customer commitments, the retention period must therefore be defined operationally for the deployment. A complete retention procedure should specify:

- The maximum age for task history and task log records.
- The database purge job or manual runbook used to delete expired `TaskHistory` rows.
- Verification that cascading log rows were deleted.
- Backup retention and backup expiration behavior, because deleted logs may remain in backups until those backups expire.
- Nomad allocation garbage collection and host filesystem cleanup behavior for output files.
- Infrastructure log retention in the deployment log pipeline.

## Summary

SEP captures who ran each task, when it ran, what predefined task context was executed, lifecycle state, and stdout/stderr output. Captured stdout/stderr is stored in the Tasks database, normally PostgreSQL in production. PII anonymization is configurable and Presidio-based, but it is best-effort and is not a comprehensive secrets detector. Access to task logs is currently available to authenticated SEP users rather than restricted by per-user or customer-specific row-level filters. Completed output retention is not time-bound in SEP application code and must be handled by deployment retention policy, explicit purge procedures, database backup retention, and Nomad host cleanup.
