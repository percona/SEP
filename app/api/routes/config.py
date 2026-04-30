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

"""Define the API routes for runtime configuration discovery."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import IsAuthenticatedDep
from app.core.alerts.config import alert_settings

router = APIRouter()


class AlertConfigResponse(BaseModel):
    """Represent the response of ``GET /api/config/alerts``.

    :param available: Whether at least one alert provider is configured.
    :type available: bool
    """

    available: bool


@router.get("/alerts", dependencies=[IsAuthenticatedDep])
async def get_alert_config() -> AlertConfigResponse:
    """Report whether at least one alert provider is configured.

    Mirrors the server-side ``bool(alert_settings.PROVIDERS)`` check used by
    the Jinja2 task forms so the React frontend can drive the same
    enabled/disabled behavior of the *Alert on failure* field. The endpoint
    is gated behind authentication so an anonymous probe cannot leak
    whether alerting is wired up on this deployment.

    :return: The alert provider availability flag.
    :rtype: AlertConfigResponse
    """
    return AlertConfigResponse(available=bool(alert_settings.PROVIDERS))
