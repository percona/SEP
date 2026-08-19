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

Mounted at ``/api/apps/report/`` via ``apps_router`` in
``app/sep/api/router.py``. ``api_router`` applies session/Bearer auth;
``apps_router`` applies ``RequireBearerForUnsafeMethods`` on POST/PUT/PATCH/DELETE.

Route layout:

* ``GET  /config``             — return upload configuration status
* ``GET  /generate/json``      — generate report and return as JSON
* ``POST /pdf-jobs``           — enqueue PDF generation from report JSON snapshot
* ``GET  /pdf-jobs/{id}``      — return PDF job status
* ``GET  /pdf-jobs/{id}/pdf``  — download ready PDF result
* ``POST /upload-jobs``        — enqueue ServiceNow upload from report JSON snapshot
* ``GET  /upload-jobs/{id}``   — return upload job status
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse, Response

from app.celery import celery
from app.core.exceptions import (
    HTTPConflictException,
    HTTPGoneException,
    HTTPInternalServerErrorException,
    HTTPServiceUnavailableException,
)
from app.sep.apps.report.artifact_store import artifact_exists, read_artifact
from app.sep.apps.report.celery import (
    render_report_pdf_job,
    upload_report_snapshot_job,
)
from app.sep.apps.report.config import health_report_settings
from app.sep.apps.report.deps import RequiredPMMAPIDep
from app.sep.apps.report.job_service import filter_report_sections
from app.sep.apps.report.models import ReportJobResponse, ReportSnapshotWrite
from app.sep.apps.report.service import generate_report

router = APIRouter()
logger = logging.getLogger(__name__)


def _job_response(job_id: str, *, pdf: bool = False) -> ReportJobResponse:
    """Build API response for a Celery-backed report job.

    :param job_id: Celery task identifier.
    :type job_id: str
    :param pdf: Whether to include PDF result readiness.
    :type pdf: bool
    :return: Job status response.
    :rtype: ReportJobResponse
    """
    result = celery.AsyncResult(job_id)
    job_result = result.result if result.successful() else None
    pdf_ready = bool(pdf and result.successful() and artifact_exists(job_id))
    response = ReportJobResponse(
        job_id=job_id,
        status=result.status.lower(),
        pdf_ready=pdf_ready,
    )
    if result.successful():
        response.result = job_result
    elif result.failed():
        logger.warning("Report job %s failed", job_id)
        if isinstance(result.result, dict) and result.result.get("error"):
            response.error = str(result.result["error"])
            errors = result.result.get("errors")
            if isinstance(errors, list):
                response.result = {"errors": errors}
        else:
            response.error = "Report job failed"
    return response


@router.get("/config")
async def report_config() -> JSONResponse:
    """Return upload configuration status.

    :return: JSON response with ``upload_disabled_reasons``.
    :rtype: JSONResponse
    """
    return JSONResponse(
        content={
            "upload_disabled_reasons": health_report_settings.upload_disabled_reasons
        }
    )


@router.get("/generate/json")
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
        sections=filter_report_sections(sections),
    )
    return JSONResponse(content=report.model_dump(mode="json"))


@router.post("/pdf-jobs")
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


@router.get("/pdf-jobs/{job_id}")
async def report_pdf_job_api(job_id: str) -> ReportJobResponse:
    """Return PDF job status.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: PDF job status response.
    :rtype: ReportJobResponse
    """
    return _job_response(job_id, pdf=True)


@router.get("/pdf-jobs/{job_id}/pdf")
async def report_download_pdf_api(job_id: str) -> Response:
    """Download a ready PDF result for a report job.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: PDF file response.
    :rtype: Response
    :raises HTTPInternalServerErrorException: If the Celery job failed.
    :raises HTTPConflictException: If the PDF result is not ready yet.
    :raises HTTPGoneException: If the staged PDF artifact has expired.
    """
    result = celery.AsyncResult(job_id)
    if result.failed():
        raise HTTPInternalServerErrorException(detail="PDF generation failed")
    if not result.successful() or not isinstance(result.result, dict):
        raise HTTPConflictException(detail="PDF is not ready")
    pdf_bytes = read_artifact(job_id)
    if pdf_bytes is None:
        raise HTTPGoneException(
            detail="PDF artifact has expired; please regenerate the report"
        )
    filename = "Health_and_Security_Report.pdf"
    if isinstance(result.result.get("filename"), str) and result.result["filename"]:
        filename = result.result["filename"]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/upload-jobs")
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
    if not health_report_settings.is_upload_configured:
        raise HTTPServiceUnavailableException(detail="Report upload is not configured")
    result = upload_report_snapshot_job.delay(body.report.model_dump(mode="json"))
    return _job_response(result.id)


@router.get("/upload-jobs/{job_id}")
async def report_upload_job_api(job_id: str) -> ReportJobResponse:
    """Return ServiceNow upload job status.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: Upload job status response.
    :rtype: ReportJobResponse
    """
    return _job_response(job_id)
