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

"""Define Pydantic response models for the Alert Troubleshooting JSON API."""

from pydantic import BaseModel

from app.sep.apps.alert_troubleshooting.deps import AlertInfo
from app.sep.models import AlertServiceType
from app.sep.snippets.models.responses import SnippetResponse


class AlertSummary(BaseModel):
    """Represent a minimal alert for the listing endpoint.

    :param name: The alert identifier.
    :type name: str
    :param label: The human-readable display label.
    :type label: str
    """

    name: str
    label: str


class AlertGroup(BaseModel):
    """Group alerts sharing a service type.

    :param service_type: The service type enum value.
    :type service_type: AlertServiceType
    :param label: Human-readable label for the service type.
    :type label: str
    :param alerts: Alerts belonging to this group.
    :type alerts: list[AlertSummary]
    """

    service_type: AlertServiceType
    label: str
    alerts: list[AlertSummary]


class AlertDetailResponse(BaseModel):
    """Wrap the response for the alert detail endpoint.

    :param alert: The alert metadata.
    :type alert: AlertInfo
    :param snippets: Snippets associated with this alert.
    :type snippets: list[SnippetResponse]
    """

    alert: AlertInfo
    snippets: list[SnippetResponse]
