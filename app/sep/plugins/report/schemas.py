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

from typing import Any

from pydantic import BaseModel, Field

from app.sep.plugins.report.models import ReportData


class ReportSnapshotWrite(BaseModel):
    """Define report snapshot body for PDF/upload jobs.

    :param report: Generated report snapshot reused for PDF/upload work.
    :type report: ReportData
    """

    report: ReportData


class ReportJobResponse(BaseModel):
    """Expose async report job state.

    :param job_id: Celery task identifier.
    :type job_id: str
    :param status: Lowercase Celery task state.
    :type status: str
    :param pdf_ready: Whether the PDF result exists and is downloadable.
    :type pdf_ready: bool
    :param result: Successful job result payload, if available.
    :type result: dict[str, Any] | None
    :param error: Failed job error text, if available.
    :type error: str | None
    """

    job_id: str
    status: str
    pdf_ready: bool = False
    result: dict[str, Any] | None = Field(default=None, json_schema_extra={"additionalProperties": True})
    error: str | None = None
