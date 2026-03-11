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

"""Define Pydantic models and conversion helpers for alert templates."""

from enum import StrEnum
from typing import Annotated

import yaml
from pydantic import BaseModel, StringConstraints


class ServiceType(StrEnum):
    """Enumerate the supported service types for alert templates.

    :cvar GENERIC: Generic service type.
    :vartype GENERIC: str
    :cvar MYSQL: MySQL service type.
    :vartype MYSQL: str
    :cvar MONGODB: MongoDB service type.
    :vartype MONGODB: str
    :cvar POSTGRESQL: PostgreSQL service type.
    :vartype POSTGRESQL: str
    """

    GENERIC = "generic"
    MYSQL = "mysql"
    MONGODB = "mongodb"
    POSTGRESQL = "postgresql"

    @property
    def label(self) -> str:
        """Return the display label with correct product-name capitalization.

        :return: The human-readable service type name.
        :rtype: str
        """
        return _SERVICE_TYPE_LABELS[self.value]


_SERVICE_TYPE_LABELS = {
    "generic": "Generic",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "postgresql": "PostgreSQL",
}


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
    :type expression: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    :param default_threshold: The default numeric threshold displayed and configured
        in the UI. This is independent of `expression` — the bundled PromQL expression
        may embed its own comparison value. `default_threshold` is UI metadata that
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
    expression: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    default_threshold: float
    severity: AlertSeverity
    description: str
    summary: str


_DEFAULT_FOR_DURATION = "5m"


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
                "for": _DEFAULT_FOR_DURATION,
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
