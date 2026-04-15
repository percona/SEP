# Changelog

All notable changes to the Services Enablement Platform (SEP) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- SEP-503: PagerDuty alert triggered on inventory sync item failure
- SEP-904: Alert Troubleshooting plugin with index page showing alerts grouped by service type
- SEP-905: Alert Troubleshooting detail page with AJAX snippet execution and inline terminal output

### Changed

- SEP-816: Reduce write amplification for `TaskHistory.execution_request` by using `JSONB` on Postgres, deferring the column by default, and clearing the sync lock via targeted `UPDATE` instead of a full ORM save
- SEP-817: Move task logs out of `execution_request.tracking.task_logs` into a dedicated append-only `taskhistory_log` table; legacy records continue to render via a dual-read fallback until their eventual cleanup
- SEP-937: PMM connection settings moved to top-level `PMM` config section (old `SEP.PMM` path still works with deprecation warning)

### Breaking Changes

- SEP-937: The `SEP__PMM_FRONTEND` environment variable has been removed. Use `PMM__FRONTEND` (top-level) or `SEP__PMM__FRONTEND` (nested under SEP.PMM) instead.

### Configuration Changes

- SEP-929: Added `UVICORN_EXTRA_RELOAD_DIRS`, `UVICORN_EXTRA_RELOAD_INCLUDES`, and `UVICORN_EXTRA_RELOAD_EXCLUDES` settings to extend uvicorn reload paths via `settings.yaml`

## [v0.11.0] - 2026-04-02

### Added

- SEP-777: Alert template YAML schema and loader (PMM Alerting plugin)
- SEP-778: PMM API client alerting endpoints
- SEP-779: Alert templates list page with service filter tabs
- SEP-780: Push to PMM functionality for alert templates
- SEP-781: PagerDuty contact point management widget
- SEP-782: Periodic alert rules backup
- SEP-783: Alert rules restore from backup
- SEP-602: Include RDS instances in inventory sync with `DEFAULT_EXECUTOR_HOST` setting
- SEP-800: IO/CPU/load/memory utilization alert snippets
- SEP-801: TimeDriftPMMAgents alert snippet
- SEP-867: `strict_executor_matching` setting to fail sync when no matching executor host
- SEP-804: `OPTIONAL_DEFAULT_TRUE` SnippetSudoOption for pre-checked sudo checkbox
- SEP-807: Signed URLs for artifact downloads instead of forwarding tokens to Nomad
- SEP-424: Next execution column in periodic tasks table
- SEP-802: Internal container registry support in installer and deployment

### Changed

- SEP-891: Core CSS dark mode fixes
- SEP-892: Theme-aware syntax highlighting for dark mode
- SEP-893: Dark mode for Simple Datatables
- SEP-894: Dark mode for flash messages, confirm modal, and saved-task containers
- SEP-895: Fix page-specific hardcoded colors for dark mode
- SEP-813: Execution target dropdowns show inventory node names alongside service names
- SEP-533: Improved cron mode UI for task scheduling
- SEP-794: Dipper form defaults dynamically populated from selected service and PMM context
- SEP-798: Updated Snippets Manager main page title
- SEP-749: PBM credentials path is now configurable
- SEP-400: All MongoDB restore options (batch size, workers, download buffers) now available in the UI
- SEP-698: Binlog PITR restore supports extra arguments via `BINLOG_RESTORE_EXTRA_ARGS`
- SEP-693: Binary log file filtering for all backup source types
- SEP-696: XB restore cleans up `.zst` files after decompression
- SEP-699: Tightened permissions on backup logs and output files
- SEP-870: Installer script respects `NO_COLOR` convention
- SEP-792: Secrets masked in logs and dev shell using Pydantic `SecretStr`

### Fixed

- SEP-868: Plugin pages fail to load for services with 130K+ schemas/tables — inventory data now loaded with pagination
- SEP-811: Frequent "CSRF signatures do not match" errors — tokens now persist across requests with correct cookie attributes
- SEP-822: Mydumper + Upload fails for file permissions when XB backup was executed first
- SEP-821: Backup S3 information not available on Edit page
- SEP-889: Navbar actions dropdown items partially unclickable
- SEP-888: Login page does not display error messages for invalid credentials
- SEP-885: Sub-app lifespan never runs in standalone mode due to `__name__` guard
- SEP-806: Global JSON deserializer eagerly converts Task.data dicts to TaskExecutionRequest
- SEP-803: Snippet/Dipper preview content leaks outside highlight container
- SEP-795: Download button stuck on 'Preparing download' after download starts
- SEP-563: Mydumper backup log not shown in full in SEP
- SEP-855: pt-stalk execution fails due to unsupported system-only option
- SEP-854: Parameter help parsing error in `mysql_version.sh`
- SEP-853: Parameter help parsing error in `mysql_query_tuning.sh`
- SEP-841: Permission issue in `mysql_log_extractor.sh` when reading MySQL error log

### Security

- SEP-931: Upgrade `Pygments` to 2.20.0 — CVE-2026-4539
- SEP-930: Bump `aiohttp` to 3.13.4
- SEP-906: Bump `Pygments` package for security
- SEP-731: Upgrade `Celery` to 5.6.0+ — credential leakage fix (AIKIDO-2025-10881)

### Configuration Changes

- SEP-602: New `DEFAULT_EXECUTOR_HOST` setting in MySQLSyncer configuration for RDS inventory sync
- SEP-867: New `strict_executor_matching` setting to fail sync when no matching executor host is found
- SEP-749: PBM credentials file path is now configurable via settings
- SEP-802: New `CONTAINER_REGISTRY` environment variable for using internal container registries in the installer

## [v0.10.3] - 2026-02-25

### Added

- SEP-662: CSRF token persistence for SPA — tokens now persist across POST requests and expire with the session
- SEP-636: Backend security hardening for the SPA proof of concept

### Fixed

- SEP-790: Xtrabackup S3 upload fails for incremental backups — `BACKUP_DIR_REGEX` was missing the "I" key for incremental backup directories
- SEP-789: MyDumper and Binlog backup metrics use wrong names — `Enum.__format__` produced malformed metric names, breaking PMM alerting

### Security

- SEP-752: Update `presidio-analyzer` and `presidio-anonymizer` to 2.2.361, resolving pinned `cryptography` vulnerability

## [v0.10.2] - 2026-02-17

### Fixed

- SEP-762: MyDumper backup fails on first execution — textfile collector attempted to stat the backup directory before it existed
- SEP-763: Xtrabackup post-run encryption fails — backup directory passed as string instead of `Path` object to GPG encryption routine

## [v0.10.1] - 2026-02-13

### Fixed

- SEP-758: Backup task cannot be executed because Nomad payload size exceeded
- SEP-759: Backup MyDumper fails execution
- SEP-760: Backup MyDumper form shows the less-locking checkbox but Edit does not

## [v0.10.0] - 2026-02-11

### Added

- SEP-651: Data collection core engine (Dipper plugin)
- SEP-652: Dipper plugin UI with host/service selection
- SEP-648: MySQL collector scripts
- SEP-649: MongoDB collector scripts
- SEP-650: PostgreSQL collector scripts
- SEP-653: PMM collector for MySQL
- SEP-692: AWS CLI support in binary log payloads
- SEP-694: Customizable S3 upload extra arguments via `AWSCLI_S3_UPLOAD_EXTRA_ARGS`
- SEP-397: Enable all PBM backup configuration options in the UI
- SEP-633: Use PMM custom labels (`sep_sync: disabled`) to ignore inventory entities during sync
- SEP-695: Add `msp_backup_running` metric for backup monitoring
- SEP-656: Type-ahead for schema and table selection in Archive form

### Changed

- SEP-718: Persistent table sort preferences saved across sessions
- SEP-550: Execution history tables default to most recent first (sorted by "Started At")
- SEP-736: Replace backup form label tooltips with info icons
- SEP-739: Disable `allow_extra_args` in all snippets to prevent unexpected behavior
- SEP-740: pt-stalk uses `--run-time` for bounded execution compatible with Nomad scheduling
- SEP-735: Remove output destination option from snippets

### Fixed

- SEP-747: MyDumper `--less-locking` regression — deprecated flag added even when disabled, breaking newer MyDumper versions
- SEP-744: Cannot save task definition changes — Edit button stayed grayed out after creation
- SEP-685: Valkey services break inventory sync — unsupported service types are now skipped
- SEP-690: Backup version comparison broken on Python 3.12+
- SEP-719: Incorrect `--defaults-file` handling in several MySQL snippets
- SEP-742: Snippet help messages causing execution errors
- SEP-741: Non-string snippet parameter defaults not working
- SEP-713: Various pt-summary snippet issues
- SEP-691: AWS CLI compatibility with `--include-from`
- SEP-715: `mysql_config_files.sh` parameter handling

### Security

- SEP-703: Update `urllib3` to 2.6.3
- SEP-701: Update `aiohttp` to 3.13.3
- SEP-728: Update `python-multipart` to 0.0.22

[Unreleased]: https://github.com/percona/SEP/compare/v0.11.0...HEAD
[v0.11.0]: https://github.com/percona/SEP/compare/v0.10.3...v0.11.0
[v0.10.3]: https://github.com/percona/SEP/compare/v0.10.2...v0.10.3
[v0.10.2]: https://github.com/percona/SEP/compare/v0.10.1...v0.10.2
[v0.10.1]: https://github.com/percona/SEP/compare/v0.10.0...v0.10.1
[v0.10.0]: https://github.com/percona/SEP/compare/v0.9.6...v0.10.0
