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

"""Helpers for report artifact jobs."""

from pathlib import Path

from app import BASE_DIR
from app.sep.plugins.report.models import ReportData

REPORT_ARTIFACT_DIR = BASE_DIR / "data" / "health-reports"


def report_pdf_path(job_id: str) -> Path:
    """Return PDF artifact path for a Celery report job.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: Filesystem path for the rendered PDF artifact.
    :rtype: Path
    """
    return REPORT_ARTIFACT_DIR / f"{job_id}.pdf"


def report_pdf_filename(report: ReportData) -> str:
    """Return user-facing report PDF filename.

    :param report: Report data used to derive the generated date.
    :type report: ReportData
    :return: Download filename for the rendered PDF.
    :rtype: str
    """
    return f"Health_and_Security_Report_{report.metadata.generated_at:%Y-%m-%d}.pdf"
