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

"""Define the JSON API router for the report plugin.

Mounted at ``/api/plugins/report/`` via ``plugins_router`` in
``app/sep/api/router.py``. ``api_router`` applies session/Bearer auth;
``plugins_router`` applies ``RequireBearerForUnsafeMethods`` on POST/PUT/PATCH/DELETE.

Route layout:

* ``GET  /config``             — return upload configuration status
* ``GET  /generate/json``      — generate report and return as JSON
* ``POST /pdf-jobs``           — enqueue PDF generation from report JSON snapshot
* ``GET  /pdf-jobs/{id}``      — return PDF job status
* ``GET  /pdf-jobs/{id}/pdf``  — download ready PDF artifact
* ``POST /upload-jobs``        — enqueue ServiceNow upload from report JSON snapshot
* ``GET  /upload-jobs/{id}``   — return upload job status
"""

from typing import Annotated

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, JSONResponse

from app.celery import celery
from app.core.exceptions import (
    HTTPConflictException,
    HTTPInternalServerErrorException,
    HTTPServiceUnavailableException,
)
from app.sep.celery import render_report_pdf_job, upload_report_snapshot_job
from app.sep.config import sep_settings
from app.sep.deps import IsApiAuthenticated
from app.sep.plugins.report.deps import RequiredPMMAPIDep
from app.sep.plugins.report.job_service import report_pdf_path
from app.sep.plugins.report.models import REPORT_SECTIONS
from app.sep.plugins.report.schemas import ReportJobResponse, ReportSnapshotWrite
from app.sep.plugins.report.service import generate_report

router = APIRouter()


def _filter_sections(sections: list[str] | None) -> list[str] | None:
    """Return only section names that exist in ``REPORT_SECTIONS``.

    :param sections: Optional list of requested section names.
    :type sections: list[str] | None
    :return: Filtered section names, ``None`` when no valid filter remains.
    :rtype: list[str] | None
    """
    if sections:
        filtered = [s for s in sections if s in REPORT_SECTIONS]
        return filtered or None
    return sections


def _job_response(job_id: str, *, pdf: bool = False) -> ReportJobResponse:
    """Build API response for a Celery-backed report job.

    :param job_id: Celery task identifier.
    :type job_id: str
    :param pdf: Whether to include PDF artifact readiness.
    :type pdf: bool
    :return: Job status response.
    :rtype: ReportJobResponse
    """
    result = celery.AsyncResult(job_id)
    response = ReportJobResponse(
        job_id=job_id,
        status=result.status.lower(),
        pdf_ready=pdf and report_pdf_path(job_id).is_file(),
    )
    if result.successful():
        response.result = result.result
    elif result.failed():
        response.error = str(result.result)
    return response


@router.get("/config", dependencies=[IsApiAuthenticated])
async def report_config() -> JSONResponse:
    """Return upload configuration status.

    :return: JSON response with ``upload_disabled_reasons``.
    :rtype: JSONResponse
    """
    return JSONResponse(
        content={
            "upload_disabled_reasons": sep_settings.HEALTH_REPORT.upload_disabled_reasons
        }
    )


@router.get("/generate/json", dependencies=[IsApiAuthenticated])
async def report_generate_json_api(
    pmm_api: RequiredPMMAPIDep,
    since: Annotated[str, Query()] = "now-7d",
    until: Annotated[str, Query()] = "now",
    *,
    full: Annotated[bool, Query()] = True,
    refresh: Annotated[bool, Query()] = False,
    sections: Annotated[list[str] | None, Query()] = None,
) -> JSONResponse:
    """Generate a report and return as JSON.

    :param pmm_api: PMM API client dependency.
    :type pmm_api: PMMRemoteAPI
    :param since: Relative start of the report period.
    :type since: str
    :param until: Relative end of the report period.
    :type until: str
    :param full: Include all check results and full backup history.
    :type full: bool
    :param refresh: Force advisor refresh before fetching results.
    :type refresh: bool
    :param sections: Optional list of sections to include.
    :type sections: list[str] | None
    :return: JSON response with full report data.
    :rtype: JSONResponse
    """
    report = await generate_report(
        pmm_api,
        since=since,
        until=until,
        full=full,
        refresh=refresh,
        sections=_filter_sections(sections),
    )
    return JSONResponse(content=report.model_dump(mode="json"))


@router.post("/pdf-jobs", dependencies=[IsApiAuthenticated])
async def report_start_pdf_job_api(
    body: Annotated[ReportSnapshotWrite, Body()],
) -> ReportJobResponse:
    """Enqueue PDF rendering from a report JSON snapshot.

    :param body: Request body containing the report snapshot.
    :type body: ReportSnapshotWrite
    :return: PDF job status response.
    :rtype: ReportJobResponse
    """
    result = render_report_pdf_job.delay(body.report.model_dump(mode="json"))
    return _job_response(result.id, pdf=True)


@router.get("/pdf-jobs/{job_id}", dependencies=[IsApiAuthenticated])
async def report_pdf_job_api(job_id: str) -> ReportJobResponse:
    """Return PDF job status.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: PDF job status response.
    :rtype: ReportJobResponse
    """
    return _job_response(job_id, pdf=True)


@router.get("/pdf-jobs/{job_id}/pdf", dependencies=[IsApiAuthenticated])
async def report_download_pdf_api(job_id: str) -> FileResponse:
    """Download a ready PDF artifact for a report job.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: PDF file response.
    :rtype: FileResponse
    :raises HTTPInternalServerErrorException: If the Celery job failed.
    :raises HTTPConflictException: If the PDF artifact is not ready yet.
    """
    result = celery.AsyncResult(job_id)
    if result.failed():
        raise HTTPInternalServerErrorException(detail="PDF generation failed")
    path = report_pdf_path(job_id)
    if not result.successful() or not path.is_file():
        raise HTTPConflictException(detail="PDF is not ready")
    filename = "Health_and_Security_Report.pdf"
    if isinstance(result.result, dict) and result.result.get("filename"):
        filename = result.result["filename"]
    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.post("/upload-jobs", dependencies=[IsApiAuthenticated])
async def report_start_upload_job_api(
    body: Annotated[ReportSnapshotWrite, Body()],
) -> ReportJobResponse:
    """Enqueue ServiceNow upload from a report JSON snapshot.

    :param body: Request body containing the report snapshot.
    :type body: ReportSnapshotWrite
    :return: Upload job status response.
    :rtype: ReportJobResponse
    :raises HTTPServiceUnavailableException: If ServiceNow upload is not configured.
    """
    if not sep_settings.HEALTH_REPORT.is_upload_configured:
        raise HTTPServiceUnavailableException(detail="Report upload is not configured")
    result = upload_report_snapshot_job.delay(body.report.model_dump(mode="json"))
    return _job_response(result.id)


@router.get("/upload-jobs/{job_id}", dependencies=[IsApiAuthenticated])
async def report_upload_job_api(job_id: str) -> ReportJobResponse:
    """Return ServiceNow upload job status.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: Upload job status response.
    :rtype: ReportJobResponse
    """
    return _job_response(job_id)
