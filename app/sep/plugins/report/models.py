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

"""Pydantic models for PMM health report data."""

from __future__ import annotations

from collections import OrderedDict
from enum import StrEnum
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from datetime import datetime, timedelta


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

    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class ServiceStatus(StrEnum):
    """Agent connectivity status for an inventory service."""

    OK = "OK"
    NOT_OK = "Not OK"


class AdvisorCheck(BaseModel):
    """A single advisor check definition (enabled only)."""

    name: str
    description: str
    summary: str
    family: str | None = None


class FailedCheck(BaseModel):
    """A single failed advisor check result."""

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
    """A group of advisor checks that share the same family."""

    family_key: str
    display_name: str
    checks: list[AdvisorCheck] = Field(default_factory=list)
    failed: dict[str, list[FailedCheck]] = Field(default_factory=dict)


class AdvisorSection(BaseModel):
    """Aggregated advisor data for the report."""

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
    """Aggregated alert data for the report."""

    total_alerts: int = 0
    alerts_per_service: dict[str, int] = Field(default_factory=dict)
    alerts_per_rule: dict[str, int] = Field(default_factory=dict)
    alerts_per_host: dict[str, int] = Field(default_factory=dict)
    alerts_daily: OrderedDict[str, int] = Field(default_factory=OrderedDict)
    alerts_daily_per_host: OrderedDict[str, dict[str, int]] = Field(
        default_factory=OrderedDict
    )
    alert_history: list[AlertEntry] = Field(default_factory=list)


class BackupEntry(BaseModel):
    """A single backup record."""

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
    period: dict[str, Any] = Field(default_factory=dict)


class BackupSection(BaseModel):
    """Aggregated backup data for the report."""

    total_backups: int = 0
    backups_by_host: dict[str, int] = Field(default_factory=dict)
    backups_by_status: dict[str, int] = Field(default_factory=dict)
    backups_by_type: dict[str, int] = Field(default_factory=dict)
    failed_backups: list[BackupEntry] = Field(default_factory=list)
    all_backups: list[BackupEntry] = Field(default_factory=list)


class DiskUsageEntry(BaseModel):
    """Disk usage for a single mountpoint on a node."""

    node_name: str
    mountpoint: str
    capacity_bytes: int = 0
    used_start_bytes: float = 0
    used_end_bytes: float = 0
    used_peak_bytes: float = 0
    usage_percentage: int = 0


class StorageSection(BaseModel):
    """Aggregated storage data for the report."""

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
    """Metadata about a generated report."""

    title: str = ""
    generated_at: datetime
    report_week: str = ""
    report_interval: str = ""
    organization: str = ""


REPORT_SECTIONS = (
    "advisors",
    "alerts",
    "backups",
    "storage",
    "uptime",
    "inventory",
)


class ReportData(BaseModel):
    """Complete report payload ready for rendering."""

    full: bool = False
    refresh: bool = False
    metadata: ReportMetadata
    monitored: MonitoredSummary = Field(default_factory=MonitoredSummary)
    advisors: AdvisorSection = Field(default_factory=AdvisorSection)
    alerts: AlertSection = Field(default_factory=AlertSection)
    backups: BackupSection = Field(default_factory=BackupSection)
    storage: StorageSection = Field(default_factory=StorageSection)
    uptime: UptimeSection = Field(default_factory=UptimeSection)
    inventory: InventorySection = Field(default_factory=InventorySection)
