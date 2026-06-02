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

from pydantic import BaseModel


class ReportGenerateWrite(BaseModel):
    """Define shared JSON body parameters for report generation API routes.

    Request body for ``POST /api/plugins/report/generate/pdf`` and
    ``POST /api/plugins/report/upload`` only. ``GET /api/plugins/report/generate``
    uses explicit query parameters (``since``, ``until``, ``full``, ``refresh``,
    ``sections``) and does not use this model. Legacy Jinja JSON remains at
    ``GET /report/generate/json``.

    :param since: Relative start of the report period (e.g. ``now-7d``).
    :type since: str
    :param until: Relative end of the report period (e.g. ``now``).
    :type until: str
    :param full: Include all check results and full backup history.
    :type full: bool
    :param refresh: Force a refresh of advisor checks before fetching results.
    :type refresh: bool
    """

    since: str = "now-7d"
    until: str = "now"
    full: bool = True
    refresh: bool = False
