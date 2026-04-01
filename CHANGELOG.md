# Changelog

All notable changes to the Services Enablement Platform (SEP) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- SEP-904: Alert Troubleshooting plugin with index page showing alerts grouped by service type

### Configuration Changes

- SEP-929: Added `UVICORN_EXTRA_RELOAD_DIRS`, `UVICORN_EXTRA_RELOAD_INCLUDES`, and `UVICORN_EXTRA_RELOAD_EXCLUDES` settings to extend uvicorn reload paths via `settings.yaml`

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

[Unreleased]: https://github.com/percona/SEP/compare/v0.10.3...HEAD
[v0.10.3]: https://github.com/percona/SEP/compare/v0.10.2...v0.10.3
[v0.10.2]: https://github.com/percona/SEP/compare/v0.10.1...v0.10.2
[v0.10.1]: https://github.com/percona/SEP/compare/v0.10.0...v0.10.1
[v0.10.0]: https://github.com/percona/SEP/compare/v0.9.6...v0.10.0
