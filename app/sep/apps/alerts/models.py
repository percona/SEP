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

"""Define the alerts plugin's DB model and Pydantic helpers."""

from enum import StrEnum
from typing import Any

import yaml
from pydantic import BaseModel
from sqlalchemy import Column, JSON
from sqlmodel import Field as SQLField

from app.core.db.models import BaseSQLModel
from app.core.utils.fields import StrippedNonEmptyStr
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
        the alert management UI (SEP-779) uses to pre-populate the threshold input.
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
