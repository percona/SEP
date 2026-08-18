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

"""HTTP integration tests for the report plugin JSON API routes.

Mounted at ``/api/apps/report/`` via ``apps_router`` in
``app/sep/api/router.py``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from app.sep.apps.report.deps import (
    get_pmm_api,
    require_pmm_api,
)
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.main import sep_app
from tests.app.sep.apps.report.conftest import make_report

API_BASE = "/api/apps/report"
_API = "app.sep.apps.report.api_routes"


@pytest.fixture
def mock_pmm_api():
    """Return a mock PMMRemoteAPI wired into dependency overrides."""
    mock = AsyncMock(spec=PMMRemoteAPI)
    sep_app.dependency_overrides[get_pmm_api] = lambda: mock
    sep_app.dependency_overrides[require_pmm_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides.pop(get_pmm_api, None)
    sep_app.dependency_overrides.pop(require_pmm_api, None)


class TestReportConfigApi:
    """Test GET /api/apps/report/config."""

    def test_returns_upload_disabled_reasons(self, test_client):
        """Default settings have upload disabled, so a reason is returned."""
        response = test_client.get(f"{API_BASE}/config")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "upload_disabled_reasons" in body
        assert isinstance(body["upload_disabled_reasons"], list)
        assert body["upload_disabled_reasons"] == ["Upload is disabled"]

    def test_requires_authentication(self, unauthenticated_client):
        """Unauthenticated requests return 401."""
        response = unauthenticated_client.get(f"{API_BASE}/config")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestReportGenerateJsonApi:
    """Test GET /api/apps/report/generate/json."""

    _JSON_URL = f"{API_BASE}/generate/json"

    def test_returns_200_with_json(self, test_client, mock_pmm_api):
        """Assert the JSON endpoint returns 200 with application/json."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(),
        ):
            response = test_client.get(self._JSON_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "application/json"
        assert response.json()["metadata"]["title"] == "Weekly Health Report"

    def test_response_contains_report_data(self, test_client, mock_pmm_api):
        """Assert the JSON body includes expected top-level keys."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(),
        ):
            response = test_client.get(self._JSON_URL)

        data = response.json()
        assert "metadata" in data
        assert "advisors" in data
        assert "alerts" in data
        assert "backups" in data
        assert "storage" in data
        assert "uptime" in data
        assert "inventory" in data
        assert data["full"] is True
        assert data["refresh"] is False

    def test_passes_default_parameters(self, test_client, mock_pmm_api):
        """Assert default query parameters are forwarded."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(),
        ) as mock_gen:
            test_client.get(self._JSON_URL)

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-7d"
        assert kwargs["until"] == "now"
        assert kwargs["full"] is True
        assert kwargs["refresh"] is False
        assert kwargs["sections"] is None

    def test_passes_custom_parameters(self, test_client, mock_pmm_api):
        """Assert custom query parameters are forwarded to generate_report."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(full=True, refresh=True),
        ) as mock_gen:
            test_client.get(
                self._JSON_URL,
                params={
                    "since": "now-14d",
                    "until": "now-2d",
                    "full": "true",
                    "refresh": "true",
                },
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-14d"
        assert kwargs["until"] == "now-2d"
        assert kwargs["full"] is True
        assert kwargs["refresh"] is True

    def test_repeated_sections_params_are_bound(self, test_client, mock_pmm_api):
        """Repeated bracket-less ``sections=`` params bind to the list.

        Mirrors the wire format the frontend emits with
        ``paramsSerializer: { indexes: null }`` (``sections=advisors&sections=alerts``).
        Regression guard for the silently-inert section filter.
        """
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(),
        ) as mock_gen:
            test_client.get(
                self._JSON_URL,
                params=[("sections", "advisors"), ("sections", "alerts")],
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["sections"] == ["advisors", "alerts"]

    def test_filters_valid_sections(self, test_client, mock_pmm_api):
        """Assert only valid section names are forwarded."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(),
        ) as mock_gen:
            test_client.get(
                self._JSON_URL,
                params=[
                    ("sections", "advisors"),
                    ("sections", "bogus"),
                    ("sections", "storage"),
                ],
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["sections"] == ["advisors", "storage"]

    def test_ignores_all_invalid_sections(self, test_client, mock_pmm_api):
        """Assert all-invalid section names fall back to full report (``None``)."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(),
        ) as mock_gen:
            test_client.get(
                self._JSON_URL,
                params=[("sections", "bogus"), ("sections", "invalid")],
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["sections"] is None

    def test_metadata_in_json_response(self, test_client, mock_pmm_api):
        """Assert report metadata is present in the JSON response."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(),
        ):
            response = test_client.get(self._JSON_URL)

        meta = response.json()["metadata"]
        assert meta["title"] == "Weekly Health Report"
        assert meta["report_week"] == "2026 - Week 14"

    def test_full_flag_reflected_in_json(self, test_client, mock_pmm_api):
        """Assert the full flag value appears in the JSON body."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(full=True),
        ):
            response = test_client.get(
                self._JSON_URL,
                params={"full": "true"},
            )

        assert response.json()["full"] is True

    def test_returns_503_when_pmm_unavailable(self, test_client):
        """Assert 503 is returned when PMM is not configured."""
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        try:
            response = test_client.get(self._JSON_URL)
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        finally:
            sep_app.dependency_overrides.pop(get_pmm_api, None)

    def test_returns_500_on_generation_error(self, test_client, mock_pmm_api):
        """Assert 500 is returned when report generation raises an exception."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            side_effect=RuntimeError("collection failed"),
        ):
            response = test_client.get(self._JSON_URL)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_requires_authentication(self, unauthenticated_client):
        """Unauthenticated requests return 401."""
        response = unauthenticated_client.get(self._JSON_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestReportJobApi:
    """Test snapshot-based PDF/upload job API endpoints."""

    _PDF_JOBS_URL = f"{API_BASE}/pdf-jobs"
    _UPLOAD_JOBS_URL = f"{API_BASE}/upload-jobs"

    @staticmethod
    def _async_result(
        *,
        status_: str = "PENDING",
        successful: bool = False,
        failed: bool = False,
        result: dict | Exception | None = None,
    ):
        async_result = MagicMock()
        async_result.status = status_
        async_result.successful.return_value = successful
        async_result.failed.return_value = failed
        async_result.result = result
        return async_result

    def test_pdf_job_uses_snapshot_without_generate_report(self, test_client):
        """PDF job start sends report JSON snapshot, no PMM recollection."""
        report_json = make_report().model_dump(mode="json")
        with (
            patch(f"{_API}.render_report_pdf_job.delay") as mock_delay,
            patch(
                f"{_API}.celery.AsyncResult",
                return_value=self._async_result(),
            ),
            patch(f"{_API}.generate_report", new_callable=AsyncMock) as mock_generate,
        ):
            mock_delay.return_value.id = "job-1"
            response = test_client.post(
                self._PDF_JOBS_URL, json={"report": report_json}
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["job_id"] == "job-1"
        mock_delay.assert_called_once_with(report_json)
        mock_generate.assert_not_awaited()

    def test_download_ready_pdf(self, test_client):
        """GET /pdf-jobs/{id}/pdf streams the staged artifact from shared disk."""
        with (
            patch(
                f"{_API}.celery.AsyncResult",
                return_value=self._async_result(
                    status_="SUCCESS",
                    successful=True,
                    result={"filename": "report.pdf"},
                ),
            ),
            patch(f"{_API}.read_artifact", return_value=b"%PDF-1.4 fake"),
        ):
            response = test_client.get(f"{self._PDF_JOBS_URL}/job-1/pdf")

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == b"%PDF-1.4 fake"
        assert 'filename="report.pdf"' in response.headers["content-disposition"]

    def test_download_returns_409_when_pdf_not_ready(self, test_client):
        """GET /pdf-jobs/{id}/pdf returns conflict until the job succeeds."""
        with patch(
            f"{_API}.celery.AsyncResult",
            return_value=self._async_result(status_="PENDING"),
        ):
            response = test_client.get(f"{self._PDF_JOBS_URL}/job-1/pdf")

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_download_returns_410_when_artifact_expired(self, test_client):
        """GET /pdf-jobs/{id}/pdf returns gone when the staged PDF was reaped."""
        with (
            patch(
                f"{_API}.celery.AsyncResult",
                return_value=self._async_result(
                    status_="SUCCESS",
                    successful=True,
                    result={"filename": "report.pdf"},
                ),
            ),
            patch(f"{_API}.read_artifact", return_value=None),
        ):
            response = test_client.get(f"{self._PDF_JOBS_URL}/job-1/pdf")

        assert response.status_code == status.HTTP_410_GONE

    def test_download_returns_500_when_job_failed(self, test_client):
        """GET /pdf-jobs/{id}/pdf returns 500 when the Celery job failed."""
        with patch(
            f"{_API}.celery.AsyncResult",
            return_value=self._async_result(
                status_="FAILURE",
                failed=True,
                result=RuntimeError("render crashed"),
            ),
        ):
            response = test_client.get(f"{self._PDF_JOBS_URL}/job-1/pdf")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_failed_job_status_returns_sanitized_error(self, test_client):
        """Job status hides raw exception details from clients."""
        with patch(
            f"{_API}.celery.AsyncResult",
            return_value=self._async_result(
                status_="FAILURE",
                failed=True,
                result=RuntimeError("https://user:secret@pmm.example failed"),
            ),
        ):
            response = test_client.get(f"{self._PDF_JOBS_URL}/job-1")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["error"] == "Report job failed"
        assert "secret" not in str(body)

    def test_failed_validation_job_returns_structured_errors(self, test_client):
        """Validation failures keep structured error details without raw exception text."""
        errors = [{"loc": ["metadata"], "msg": "Field required", "type": "missing"}]
        with patch(
            f"{_API}.celery.AsyncResult",
            return_value=self._async_result(
                status_="FAILURE",
                failed=True,
                result={"error": "Invalid report snapshot", "errors": errors},
            ),
        ):
            response = test_client.get(f"{self._PDF_JOBS_URL}/job-1")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["error"] == "Invalid report snapshot"
        assert body["result"] == {"errors": errors}

    def test_upload_job_uses_snapshot_without_generate_report(self, test_client):
        """Upload job start sends report JSON snapshot, no PMM recollection."""
        report_json = make_report().model_dump(mode="json")
        with (
            patch(
                f"{_API}.health_report_settings",
                SimpleNamespace(is_upload_configured=True),
            ),
            patch(f"{_API}.upload_report_snapshot_job.delay") as mock_delay,
            patch(
                f"{_API}.celery.AsyncResult",
                return_value=self._async_result(),
            ),
            patch(f"{_API}.generate_report", new_callable=AsyncMock) as mock_generate,
        ):
            mock_delay.return_value.id = "job-2"
            response = test_client.post(
                self._UPLOAD_JOBS_URL,
                json={"report": report_json},
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["job_id"] == "job-2"
        mock_delay.assert_called_once_with(report_json)
        mock_generate.assert_not_awaited()

    def test_upload_job_requires_config(self, test_client):
        """Upload job returns 503 when ServiceNow upload is disabled."""
        response = test_client.post(
            self._UPLOAD_JOBS_URL,
            json={"report": make_report().model_dump(mode="json")},
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_pdf_job_requires_authentication(self, unauthenticated_client):
        """Unauthenticated PDF job creation returns 401."""
        response = unauthenticated_client.post(self._PDF_JOBS_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestReportApiBearerAuthGate:
    """Mutations require ``Authorization: Bearer``; reads accept cookie auth."""

    def test_generate_json_with_cookie_only_returns_200(
        self, test_client, mock_pmm_api
    ):
        """GET /generate/json accepts cookie-only auth."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=make_report(),
        ):
            response = test_client.get(f"{API_BASE}/generate/json")

        assert response.status_code == status.HTTP_200_OK

    def test_pdf_with_cookie_only_returns_401(
        self, api_admin_client_no_bearer, mock_pmm_api
    ):
        """POST /pdf-jobs without Bearer is rejected by plugins_router gate."""
        response = api_admin_client_no_bearer.post(f"{API_BASE}/pdf-jobs")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_upload_with_cookie_only_returns_401(
        self, api_admin_client_no_bearer, mock_pmm_api
    ):
        """POST /upload-jobs without Bearer is rejected by plugins_router gate."""
        response = api_admin_client_no_bearer.post(f"{API_BASE}/upload-jobs")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
