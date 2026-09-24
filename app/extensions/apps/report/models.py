# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define Pydantic models for PMM health report data and API request/response models."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.utils.fields import ARBITRARY_ARGS_SCHEMA, ArbitraryMapping


class CheckSeverity(StrEnum):
    """Severity levels for advisor check results."""

    SEVERITY_EMERGENCY = "SEVERITY_EMERGENCY"
    SEVERITY_ALERT = "SEVERITY_ALERT"
    SEVERITY_CRITICAL = "SEVERITY_CRITICAL"
    SEVERITY_ERROR = "SEVERITY_ERROR"
    SEVERITY_WARNING = "SEVERITY_WARNING"
    SEVERITY_NOTICE = "SEVERITY_NOTICE"
    SEVERITY_INFO = "SEVERITY_INFO"
    SEVERITY_DEBUG = "SEVERITY_DEBUG"


class BackupStatus(StrEnum):
    """Status values for a backup entry."""

    PASS = "pass"  # noqa: S105 # nosec B105
    FAIL = "fail"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class ServiceStatus(StrEnum):
    """Agent connectivity status for an inventory service."""

    OK = "OK"
    NOT_OK = "Not OK"


class AdvisorCheck(BaseModel):
    """A single advisor check definition (enabled only).

    :param name: The unique check name.
    :type name: str
    :param description: Human-readable description of what the check tests.
    :type description: str
    :param summary: Short one-line summary of the check.
    :type summary: str
    :param family: The advisor family key this check belongs to, if any.
    :type family: str | None
    """

    name: str
    description: str
    summary: str
    family: str | None = None


class FailedCheck(BaseModel):
    """A single failed advisor check result.

    :param name: The check name that failed.
    :type name: str
    :param description: Human-readable description of what the check tests.
    :type description: str
    :param summary: Short one-line summary of the check.
    :type summary: str
    :param severity: Severity level of the failure.
    :type severity: CheckSeverity
    :param node_name: Name of the node affected, if applicable.
    :type node_name: str | None
    :param node_id: PMM node ID of the affected node, if applicable.
    :type node_id: str | None
    :param service_name: Name of the service affected, if applicable.
    :type service_name: str | None
    :param service_id: PMM service ID of the affected service, if applicable.
    :type service_id: str | None
    :param read_more_url: URL linking to documentation for this check.
    :type read_more_url: str
    """

    name: str
    description: str
    summary: str
    severity: CheckSeverity
    node_name: str | None = None
    node_id: str | None = None
    service_name: str | None = None
    service_id: str | None = None
    read_more_url: str = ""


class AdvisorFamily(BaseModel):
    """A group of advisor checks that share the same family.

    :param family_key: Internal family key (e.g. ``"FAMILY_MYSQL"``).
    :type family_key: str
    :param display_name: Human-readable name shown in the report (e.g. ``"MySQL"``).
    :type display_name: str
    :param checks: All enabled checks belonging to this family.
    :type checks: list[AdvisorCheck]
    :param failed: Mapping of check name to its list of failed results.
    :type failed: dict[str, list[FailedCheck]]
    """

    family_key: str
    display_name: str
    checks: list[AdvisorCheck] = Field(default_factory=list)
    failed: dict[str, list[FailedCheck]] = Field(default_factory=dict)


class AdvisorSection(BaseModel):
    """Aggregated advisor data for the report.

    ``total_failed`` counts failed advisor results (rows), not distinct check names.
    """

    total_checks: int = 0
    total_failed: int = 0
    refresh_issues: list[str] = Field(default_factory=list)
    families: list[AdvisorFamily] = Field(default_factory=list)


class AlertEntry(BaseModel):
    """A single alert annotation extracted from Grafana."""

    model_config = ConfigDict(extra="allow")

    id: int = 0
    time: int = 0
    alertname: str = ""
    node_name: str = ""
    node_id: str = ""
    service: str = ""
    service_id: str = ""
    service_type: str = ""
    severity: str = ""


class AlertSection(BaseModel):
    """Aggregated alert data for the report.

    :param total_alerts: Total number of alert annotations in the period.
    :type total_alerts: int
    :param alerts_per_service: Alert count keyed by service name.
    :type alerts_per_service: dict[str, int]
    :param alerts_per_rule: Alert count keyed by alert rule name.
    :type alerts_per_rule: dict[str, int]
    :param alerts_per_host: Alert count keyed by node name.
    :type alerts_per_host: dict[str, int]
    :param alerts_daily: Alert count keyed by date string (``YYYY-MM-DD``).
    :type alerts_daily: dict[str, int]
    :param alerts_daily_per_host: Daily alert count per host, keyed by date then host.
    :type alerts_daily_per_host: dict[str, dict[str, int]]
    :param alert_history: Full list of individual alert entries.
    :type alert_history: list[AlertEntry]
    """

    total_alerts: int = 0
    alerts_per_service: dict[str, int] = Field(default_factory=dict)
    alerts_per_rule: dict[str, int] = Field(default_factory=dict)
    alerts_per_host: dict[str, int] = Field(default_factory=dict)
    alerts_daily: dict[str, int] = Field(default_factory=dict)
    alerts_daily_per_host: dict[str, dict[str, int]] = Field(default_factory=dict)
    alert_history: list[AlertEntry] = Field(default_factory=list)


class BackupEntry(BaseModel):
    """A single backup record.

    :param id: Unique identifier for this backup entry.
    :type id: str
    :param alias: Human-readable alias for the backup schedule.
    :type alias: str
    :param name: Node name where the backup was taken.
    :type name: str
    :param type: Backup type (e.g. ``"physical"``, ``"logical"``).
    :type type: str
    :param status: Result status of the backup.
    :type status: BackupStatus
    :param size: Raw backup size value from the metric label, or ``"0"`` if unknown.
    :type size: str
    :param estimated_data: ``True`` when the time period or size data is estimated.
    :type estimated_data: bool
    :param enabled: Whether the backup schedule is currently enabled, if available.
    :type enabled: bool | None
    :param encryption: Encryption state label reported by PMM.
    :type encryption: str
    :param period: Dictionary with ``start``, ``end``, and ``duration`` of the backup.
    :type period: dict[str, Any]
    """

    model_config = ConfigDict(extra="allow")

    id: str
    alias: str = ""
    name: str = ""
    type: str = ""
    status: BackupStatus = BackupStatus.UNKNOWN
    size: str = "0"
    estimated_data: bool = True
    enabled: bool | None = None
    encryption: str = "Unknown"
    period: dict[str, Any] = Field(
        default_factory=dict, json_schema_extra=ARBITRARY_ARGS_SCHEMA
    )


class BackupSection(BaseModel):
    """Aggregated backup data for the report.

    :param total_backups: Total number of backup entries collected.
    :type total_backups: int
    :param backups_by_host: Backup count keyed by node name.
    :type backups_by_host: dict[str, int]
    :param backups_by_status: Backup count keyed by status string.
    :type backups_by_status: dict[str, int]
    :param backups_by_type: Backup count keyed by backup type.
    :type backups_by_type: dict[str, int]
    :param failed_backups: Subset of backups with a ``fail`` status.
    :type failed_backups: list[BackupEntry]
    :param all_backups: Complete list of all backup entries.
    :type all_backups: list[BackupEntry]
    """

    total_backups: int = 0
    backups_by_host: dict[str, int] = Field(default_factory=dict)
    backups_by_status: dict[str, int] = Field(default_factory=dict)
    backups_by_type: dict[str, int] = Field(default_factory=dict)
    failed_backups: list[BackupEntry] = Field(default_factory=list)
    all_backups: list[BackupEntry] = Field(default_factory=list)


class DiskUsageEntry(BaseModel):
    """Disk usage for a single mountpoint on a node.

    :param node_name: Human-readable node hostname.
    :type node_name: str
    :param mountpoint: Filesystem mountpoint path (e.g. ``"/"``, ``"/data"``).
    :type mountpoint: str
    :param capacity_bytes: Total filesystem capacity in bytes.
    :type capacity_bytes: int
    :param used_start_bytes: Used bytes at the start of the report period.
    :type used_start_bytes: float
    :param used_end_bytes: Used bytes at the end of the report period.
    :type used_end_bytes: float
    :param used_peak_bytes: Peak used bytes observed during the report period.
    :type used_peak_bytes: float
    :param usage_percentage: End-of-period usage as a percentage of total capacity.
    :type usage_percentage: int
    """

    node_name: str
    mountpoint: str
    capacity_bytes: int = 0
    used_start_bytes: float = 0
    used_end_bytes: float = 0
    used_peak_bytes: float = 0
    usage_percentage: int = 0


class StorageSection(BaseModel):
    """Aggregated storage data for the report.

    :param entries: List of per-mountpoint disk usage entries, sorted by usage descending.
    :type entries: list[DiskUsageEntry]
    """

    entries: list[DiskUsageEntry] = Field(default_factory=list)


class UptimeEntry(BaseModel):
    """Uptime for a single monitored service."""

    service_name: str
    uptime: timedelta
    since: str = ""


class UptimeSection(BaseModel):
    """Aggregated uptime data for the report."""

    entries: list[UptimeEntry] = Field(default_factory=list)


class InventoryServiceEntry(BaseModel):
    """A monitored service with its agent connectivity status."""

    service_name: str
    service_type: str
    node_name: str = ""
    status: ServiceStatus = ServiceStatus.OK


class InventorySection(BaseModel):
    """Aggregated inventory data for the report."""

    entries: list[InventoryServiceEntry] = Field(default_factory=list)


class MonitoredSummary(BaseModel):
    """Summary of monitored nodes and services by type."""

    total_nodes: int = 0
    total_services: int = 0
    services_by_type: dict[str, int] = Field(default_factory=dict)


class ReportMetadata(BaseModel):
    """Metadata about a generated report.

    :param title: Report title string.
    :type title: str
    :param generated_at: Timestamp when the report was generated.
    :type generated_at: datetime
    :param report_week: ISO week label, e.g. ``"Report 2026 Week 15"``.
    :type report_week: str
    :param report_interval: Human-readable date range string for the report period.
    :type report_interval: str
    """

    title: str = ""
    generated_at: datetime
    report_week: str = ""
    report_interval: str = ""


REPORT_SECTIONS = (
    "advisors",
    "alerts",
    "backups",
    "storage",
    "uptime",
    "inventory",
)

REPORT_SECTION_LABELS: list[tuple[str, str]] = [
    ("advisors", "Advisors"),
    ("alerts", "Alerts"),
    ("backups", "Backups"),
    ("storage", "Disk Usage"),
    ("uptime", "Service Uptime"),
    ("inventory", "Included Services"),
]


class ReportData(BaseModel):
    """Complete report payload ready for rendering.

    :param full: When ``True``, all check results and full backup history are included.
    :type full: bool
    :param refresh: When ``True``, advisor checks were refreshed before data collection.
    :type refresh: bool
    :param metadata: Report title, generation timestamp, and period labels.
    :type metadata: ReportMetadata
    :param monitored: Summary counts of monitored nodes and services.
    :type monitored: MonitoredSummary
    :param advisors: Advisor check results grouped by family.
    :type advisors: AdvisorSection
    :param alerts: Alert annotation history and aggregations.
    :type alerts: AlertSection
    :param backups: Backup status entries and aggregations.
    :type backups: BackupSection
    :param storage: Disk usage entries per node mountpoint.
    :type storage: StorageSection
    :param uptime: Service uptime entries for the report period.
    :type uptime: UptimeSection
    :param inventory: Monitored service inventory with connectivity status.
    :type inventory: InventorySection
    """

    full: bool = True
    refresh: bool = False
    metadata: ReportMetadata
    monitored: MonitoredSummary = Field(default_factory=MonitoredSummary)
    advisors: AdvisorSection = Field(default_factory=AdvisorSection)
    alerts: AlertSection = Field(default_factory=AlertSection)
    backups: BackupSection = Field(default_factory=BackupSection)
    storage: StorageSection = Field(default_factory=StorageSection)
    uptime: UptimeSection = Field(default_factory=UptimeSection)
    inventory: InventorySection = Field(default_factory=InventorySection)


class ReportSnapshotWrite(BaseModel):
    """Define report snapshot body for PDF/upload jobs.

    :param report: Generated report snapshot reused for PDF/upload work.
    """

    report: ReportData


class ReportJobResponse(BaseModel):
    """Expose async report job state.

    :param job_id: Celery task identifier.
    :param status: Lowercase Celery task state.
    :param pdf_ready: Whether the PDF result exists and is downloadable.
    :param result: Successful job result payload, if available.
    :param error: Failed job error text, if available.
    """

    job_id: str
    status: str
    pdf_ready: bool = False
    result: ArbitraryMapping | None = None
    error: str | None = None
