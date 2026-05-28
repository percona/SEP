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

"""Define the JSON API request and response models for the report plugin."""

from pydantic import BaseModel, ConfigDict


class ReportGenerateRequest(BaseModel):
    """Define the shared parameters for report generation JSON API routes.

    Used as query parameters on ``GET /generate/json`` and as the request body on
    ``POST /generate/pdf`` and ``POST /upload``. The ``sections`` field applies
    only to ``GET /generate/json``; PDF and upload routes ignore it and collect all
    sections.

    :param since: Relative start of the report period (e.g. ``now-7d``).
    :type since: str
    :param until: Relative end of the report period (e.g. ``now``).
    :type until: str
    :param full: Include all check results and full backup history.
    :type full: bool
    :param refresh: Force a refresh of advisor checks before fetching results.
    :type refresh: bool
    :param sections: Optional list of section names to include.
    :type sections: list[str] | None
    """

    since: str = "now-7d"
    until: str = "now"
    full: bool = True
    refresh: bool = False
    sections: list[str] | None = None


class ReportUploadResponse(BaseModel):
    """Represent the ServiceNow upload response from ``POST /upload``.

    The upstream upload endpoint returns a dynamic JSON object; this model
    preserves all fields for OpenAPI typing and frontend consumption.
    """

    model_config = ConfigDict(extra="allow")
