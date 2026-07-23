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

"""Define the alerts plugin's DB model, Pydantic helpers, and API request/response models."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import Column, JSON
from sqlmodel import Field as SQLField

from app.core.db.models import BaseSQLModel
from app.core.utils.fields import (
    ARBITRARY_ARGS_SCHEMA,
    NonEmptyStr,
    StrippedNonEmptyStr,
)
from app.sep.models import AlertServiceType as ServiceType


class AlertBackup(BaseSQLModel, table=True):
    """Store a point-in-time snapshot of PMM alert configuration.

    :param data: The full alert configuration data including templates,
        rules, contact points, notification policies, and folders.
    :type data: dict[str, Any]
    :param metadata_: Summary counts for the backed-up configuration,
        stored as the ``metadata`` column in the database.
    :type metadata_: dict[str, Any]
    """

    __tablename__ = "alert_backup"

    data: dict[str, Any] = SQLField(sa_column=Column(JSON, nullable=False))
    metadata_: dict[str, Any] = SQLField(
        sa_column=Column("metadata", JSON, nullable=False)
    )


class AlertSeverity(StrEnum):
    """Enumerate the supported severity levels for alert templates.

    :cvar INFO: Informational severity.
    :vartype INFO: str
    :cvar WARNING: Warning severity.
    :vartype WARNING: str
    :cvar CRITICAL: Critical severity.
    :vartype CRITICAL: str
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertTemplate(BaseModel):
    """Represent a static, file-backed alert template definition.

    :param name: The display name of the alert.
    :type name: str
    :param service_type: The service category this alert applies to.
    :type service_type: ServiceType
    :param expression: The PromQL expression used to evaluate the alert condition.
        Whitespace is stripped and the value must be non-empty.
    :type expression: StrippedNonEmptyStr
    :param default_threshold: The default numeric threshold displayed and configured
        in the UI. This is independent of ``expression`` — the bundled PromQL expression
        may embed its own comparison value. ``default_threshold`` is UI metadata that
        the alert management UI uses to pre-populate the threshold input.
    :type default_threshold: float
    :param severity: The severity level of the alert.
    :type severity: AlertSeverity
    :param description: A human-readable description of what the alert detects.
    :type description: str
    :param summary: A short summary template for alert notifications.
    :type summary: str
    """

    name: str
    service_type: ServiceType
    expression: StrippedNonEmptyStr
    default_threshold: float
    severity: AlertSeverity
    description: str
    summary: str


DEFAULT_FOR_DURATION = "300s"


def to_pmm_template_yaml(template: AlertTemplate) -> str:
    """Convert a SEP alert template to PMM template YAML format.

    :param template: The SEP alert template to convert.
    :type template: AlertTemplate
    :return: A YAML string in the PMM template format.
    :rtype: str
    """
    pmm_template = {
        "templates": [
            {
                "name": template.name,
                "version": 1,
                "summary": template.summary,
                "expr": template.expression,
                "for": DEFAULT_FOR_DURATION,
                "severity": template.severity.value,
                "labels": {},
                "annotations": {
                    "summary": template.summary,
                    "description": template.description,
                },
            }
        ]
    }
    return yaml.dump(pmm_template, default_flow_style=False)


class PushRequest(BaseModel):
    """Describe the request body for ``POST /api/apps/alerts/push``.

    :param selected_templates: Names of templates to push to PMM. Must be a
        non-empty list of non-empty strings.
    """

    selected_templates: list[NonEmptyStr] = Field(min_length=1)


class PushItemResult(BaseModel):
    """Represent a per-template result row returned by the push endpoint.

    :param name: The template name the result applies to.
    :param status: One of ``"success"``, ``"skipped"``, ``"error"``.
    :param message: A human-readable description of the outcome.
    """

    name: str
    status: Literal["success", "skipped", "error"]
    message: str


class PushResponse(BaseModel):
    """Wrap the per-template results returned by the push endpoint.

    :param results: One :class:`PushItemResult` per template in the request.
    """

    results: list[PushItemResult]


class RestoreRequest(BaseModel):
    """Describe the request body for ``POST /api/apps/alerts/restore``.

    :param backup_id: Primary key of the :class:`~app.sep.apps.alerts.models.AlertBackup`
        row to restore from. Must be a positive integer.
    """

    backup_id: int = Field(gt=0)


class RestoreResponse(BaseModel):
    """Wrap the summary returned by the restore endpoint.

    :param status: ``"success"`` on a complete restore.
    :param details: Per-section restore counts as returned by
        :func:`~app.sep.apps.alerts.restore.restore_from_backup`.
    """

    status: Literal["success"]
    details: dict[str, Any] = Field(json_schema_extra=ARBITRARY_ARGS_SCHEMA)


class BackupSummary(BaseModel):
    """Represent a compact backup row used by the list endpoint.

    :param id: Primary key of the backup row.
    :param created_at: UTC timestamp the backup was written.
    :param metadata: Summary counts persisted alongside the backup snapshot.
    """

    id: int
    created_at: datetime
    metadata: dict[str, Any] = Field(json_schema_extra=ARBITRARY_ARGS_SCHEMA)


class BackupDetailTemplate(BaseModel):
    """Represent a template entry inside a backup snapshot.

    :param name: The template name.
    :param summary: The template summary blurb.
    """

    name: str
    summary: str


class BackupDetailRule(BaseModel):
    """Represent a rule entry inside a backup snapshot.

    :param title: The rule title.
    """

    title: str


class BackupDetailContactPoint(BaseModel):
    """Represent a contact-point entry inside a backup snapshot.

    :param name: The contact point name.
    :param type: The contact point type (e.g. ``"pagerduty"``).
    """

    name: str
    type: str


class BackupDetailFolder(BaseModel):
    """Represent a folder entry inside a backup snapshot.

    :param title: The folder title.
    """

    title: str


class BackupDetail(BaseModel):
    """Describe the full detail response for a single backup.

    :param id: Primary key of the backup row.
    :param created_at: UTC timestamp the backup was written.
    :param templates: Templates captured in the backup.
    :param rules: Rules captured in the backup.
    :param contact_points: Contact points captured in the backup.
    :param folders: Folders captured in the backup.
    :param notification_policy_receiver: Top-level receiver from the captured
        notification policy, or ``None`` when no policy was captured.
    """

    id: int
    created_at: datetime
    templates: list[BackupDetailTemplate]
    rules: list[BackupDetailRule]
    contact_points: list[BackupDetailContactPoint]
    folders: list[BackupDetailFolder]
    notification_policy_receiver: str | None


class PagerDutyRequest(BaseModel):
    """Describe the request body for ``POST /api/apps/alerts/pagerduty``.

    :param integration_key: The PagerDuty integration key. Must be non-empty
        after stripping whitespace.
    """

    integration_key: NonEmptyStr


class PagerDutyResponse(BaseModel):
    """Describe the response body for the PagerDuty save / delete endpoints.

    :param status: ``"created"``, ``"updated"`` (save) or ``"deleted"`` (delete).
    """

    status: Literal["created", "updated", "deleted"]


class IndexTemplate(BaseModel):
    """Represent a single alert template row on the index page.

    :param name: The display name of the alert template.
    :param service_type: The service category this template applies to.
    :param expression: The PromQL expression backing the alert.
    :param default_threshold: The default numeric threshold for the UI.
    :param severity: The severity level (``"info"``, ``"warning"``, ``"critical"``).
    :param description: A human-readable description of the alert.
    :param summary: A short summary template for notifications.
    :param in_pmm: ``True`` when a template of this name is already present in PMM.
    """

    name: str
    service_type: str
    expression: str
    default_threshold: float
    severity: str
    description: str
    summary: str
    in_pmm: bool


class IndexTemplateGroup(BaseModel):
    """Group index templates by service type.

    :param service_type: The service type identifier (e.g. ``"mysql"``).
    :param label: The human-readable service type label (e.g. ``"MySQL"``).
    :param templates: The templates belonging to this service type.
    """

    service_type: str
    label: str
    templates: list[IndexTemplate]


class IndexPagerDutyStatus(BaseModel):
    """Describe the PagerDuty contact-point status on the index page.

    :param configured: ``True`` when a SEP PagerDuty contact point exists in PMM.
    :param uid: The contact point UID when configured, otherwise ``None``.
    """

    configured: bool
    uid: str | None = None


class IndexBackupSummary(BaseModel):
    """Represent a compact backup row for the index "recent backups" widget.

    Leaner than :class:`BackupSummary` (no ``metadata``): the list page only
    renders the id and timestamp, so the index payload omits the summary counts.

    :param id: Primary key of the backup row.
    :param created_at: UTC timestamp the backup was written.
    """

    id: int
    created_at: datetime


class IndexResponse(BaseModel):
    """Describe the response body for ``GET /api/apps/alerts/``.

    Aggregate everything the React list page needs in a single call: the alert
    templates grouped by service type, whether PMM is reachable, the PagerDuty
    contact-point status, and the most recent backups.

    :param groups: Alert templates grouped by service type. Only service types
        with at least one template are included.
    :param pmm_connected: ``True`` when PMM is configured and reachable.
    :param pagerduty: The PagerDuty status, or ``None`` when PMM is unreachable.
    :param recent_backups: The most recent alert backups, newest first.
    """

    groups: list[IndexTemplateGroup]
    pmm_connected: bool
    pagerduty: IndexPagerDutyStatus | None
    recent_backups: list[IndexBackupSummary]
