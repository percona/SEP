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

"""Define tests for the app.sep.plugins.report.api_routes module."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status

from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.main import sep_app
from app.sep.plugins.report.deps import (
    get_pmm_api,
    require_pmm_api,
    require_upload_configured,
)
from tests.app.sep.plugins.report.test_routes import _make_report

API_BASE = "/api/plugins/report"
_API = "app.sep.plugins.report.api_routes"


@pytest.fixture
def mock_pmm_api():
    """Return a mock PMMRemoteAPI wired into dependency overrides."""
    mock = AsyncMock(spec=PMMRemoteAPI)
    sep_app.dependency_overrides[get_pmm_api] = lambda: mock
    sep_app.dependency_overrides[require_pmm_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


class TestReportApiGenerate:
    """Test GET /api/plugins/report/generate (JSON report generation)."""

    _GENERATE_URL = f"{API_BASE}/generate"

    def test_returns_200_with_json(self, test_client, mock_pmm_api):
        """Assert the JSON endpoint returns 200 with application/json."""
        report = _make_report()
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = test_client.get(self._GENERATE_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "application/json"

    def test_response_contains_report_data(self, test_client, mock_pmm_api):
        """Assert the JSON body includes expected top-level keys."""
        report = _make_report()
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = test_client.get(self._GENERATE_URL)

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
        report = _make_report()
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.get(self._GENERATE_URL)

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-7d"
        assert kwargs["until"] == "now"
        assert kwargs["full"] is True
        assert kwargs["refresh"] is False
        assert kwargs["sections"] is None

    def test_passes_custom_parameters(self, test_client, mock_pmm_api):
        """Assert custom query parameters are forwarded to generate_report."""
        report = _make_report(full=True, refresh=True)
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.get(
                self._GENERATE_URL,
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

    def test_filters_valid_sections(self, test_client, mock_pmm_api):
        """Assert only valid section names are forwarded."""
        report = _make_report()
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.get(
                self._GENERATE_URL,
                params={"sections": ["advisors", "bogus", "storage"]},
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["sections"] == ["advisors", "storage"]

    def test_ignores_all_invalid_sections(self, test_client, mock_pmm_api):
        """Assert sections list becomes empty when all names are invalid."""
        report = _make_report()
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.get(
                self._GENERATE_URL,
                params={"sections": ["bogus", "invalid"]},
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["sections"] == []

    def test_metadata_in_json_response(self, test_client, mock_pmm_api):
        """Assert report metadata is present in the JSON response."""
        report = _make_report()
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = test_client.get(self._GENERATE_URL)

        meta = response.json()["metadata"]
        assert meta["title"] == "Weekly Health Report"
        assert meta["report_week"] == "2026 - Week 14"

    def test_full_flag_reflected_in_json(self, test_client, mock_pmm_api):
        """Assert the full flag value appears in the JSON body."""
        report = _make_report(full=True)
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = test_client.get(
                self._GENERATE_URL,
                params={"full": "true"},
            )

        assert response.json()["full"] is True

    def test_returns_503_when_pmm_unavailable(self, test_client):
        """Assert 503 is returned when PMM is not configured."""
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        try:
            response = test_client.get(self._GENERATE_URL)
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        finally:
            sep_app.dependency_overrides = {}

    def test_returns_500_on_generation_error(self, test_client, mock_pmm_api):
        """Assert 500 is returned when report generation raises an exception."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            side_effect=RuntimeError("collection failed"),
        ):
            response = test_client.get(self._GENERATE_URL)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestReportApiGeneratePDF:
    """Test POST /api/plugins/report/generate/pdf (PDF report generation)."""

    _PDF_URL = f"{API_BASE}/generate/pdf"

    def test_returns_200_with_pdf(self, test_client, mock_pmm_api):
        """Assert a generated report is returned as a PDF download."""
        report = _make_report()
        pdf_bytes = b"%PDF-1.4 fake content"
        with (
            patch(
                f"{_API}.generate_report",
                new_callable=AsyncMock,
                return_value=report,
            ),
            patch(
                f"{_API}.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=pdf_bytes,
            ),
        ):
            response = test_client.post(self._PDF_URL, json={})

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == pdf_bytes

    def test_content_disposition_header(self, test_client, mock_pmm_api):
        """Assert Content-Disposition header contains the expected filename."""
        report = _make_report()
        with (
            patch(
                f"{_API}.generate_report",
                new_callable=AsyncMock,
                return_value=report,
            ),
            patch(
                f"{_API}.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
        ):
            response = test_client.post(self._PDF_URL, json={})

        disposition = response.headers["content-disposition"]
        assert "Health_and_Security_Report_2026-03-31.pdf" in disposition
        assert disposition.startswith("attachment")

    def test_passes_default_parameters(self, test_client, mock_pmm_api):
        """Assert default since/until/full/refresh values are forwarded."""
        report = _make_report()
        with (
            patch(
                f"{_API}.generate_report",
                new_callable=AsyncMock,
                return_value=report,
            ) as mock_gen,
            patch(
                f"{_API}.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
        ):
            test_client.post(self._PDF_URL, json={})

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-7d"
        assert kwargs["until"] == "now"
        assert kwargs["full"] is True
        assert kwargs["refresh"] is False

    def test_passes_custom_parameters(self, test_client, mock_pmm_api):
        """Assert custom JSON body parameters are forwarded to generate_report."""
        report = _make_report(full=True, refresh=True)
        with (
            patch(
                f"{_API}.generate_report",
                new_callable=AsyncMock,
                return_value=report,
            ) as mock_gen,
            patch(
                f"{_API}.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
        ):
            test_client.post(
                self._PDF_URL,
                json={
                    "since": "now-30d",
                    "until": "now-1d",
                    "full": True,
                    "refresh": True,
                },
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-30d"
        assert kwargs["until"] == "now-1d"
        assert kwargs["full"] is True
        assert kwargs["refresh"] is True

    def test_returns_503_when_pmm_unavailable(self, test_client):
        """Assert 503 is returned when PMM is not configured."""
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        try:
            response = test_client.post(self._PDF_URL, json={})
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        finally:
            sep_app.dependency_overrides = {}

    def test_returns_500_on_generation_error(self, test_client, mock_pmm_api):
        """Assert 500 is returned when report generation raises an exception."""
        with patch(
            f"{_API}.generate_report",
            new_callable=AsyncMock,
            side_effect=RuntimeError("collection failed"),
        ):
            response = test_client.post(self._PDF_URL, json={})

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestReportApiUpload:
    """Test POST /api/plugins/report/upload (ServiceNow upload)."""

    _UPLOAD_URL = f"{API_BASE}/upload"

    @pytest.fixture(autouse=True)
    def _mock_upload_configured(self):
        """Override the upload dependency to allow requests."""
        sep_app.dependency_overrides[require_upload_configured] = lambda: None
        yield
        sep_app.dependency_overrides.pop(require_upload_configured, None)

    def test_returns_200_with_json(self, test_client, mock_pmm_api):
        """Assert a successful upload returns 200 with JSON."""
        report = _make_report()
        upload_result = {"status": "ok", "id": "12345"}
        with (
            patch(
                f"{_API}.generate_report",
                new_callable=AsyncMock,
                return_value=report,
            ),
            patch(
                f"{_API}.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
            patch(
                f"{_API}.upload_pdf_report",
                new_callable=AsyncMock,
                return_value=upload_result,
            ),
        ):
            response = test_client.post(self._UPLOAD_URL, json={})

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == upload_result

    def test_passes_default_parameters(self, test_client, mock_pmm_api):
        """Assert default JSON body parameters are forwarded."""
        report = _make_report()
        with (
            patch(
                f"{_API}.generate_report",
                new_callable=AsyncMock,
                return_value=report,
            ) as mock_gen,
            patch(
                f"{_API}.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
            patch(
                f"{_API}.upload_pdf_report",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            test_client.post(self._UPLOAD_URL, json={})

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-7d"
        assert kwargs["until"] == "now"
        assert kwargs["full"] is True
        assert kwargs["refresh"] is False

    def test_passes_custom_parameters(self, test_client, mock_pmm_api):
        """Assert custom JSON body parameters are forwarded to generate_report."""
        report = _make_report(full=True, refresh=True)
        with (
            patch(
                f"{_API}.generate_report",
                new_callable=AsyncMock,
                return_value=report,
            ) as mock_gen,
            patch(
                f"{_API}.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
            patch(
                f"{_API}.upload_pdf_report",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            test_client.post(
                self._UPLOAD_URL,
                json={
                    "since": "now-30d",
                    "until": "now-1d",
                    "full": True,
                    "refresh": True,
                },
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-30d"
        assert kwargs["until"] == "now-1d"
        assert kwargs["full"] is True
        assert kwargs["refresh"] is True

    def test_returns_503_when_pmm_unavailable(self, test_client):
        """Assert 503 is returned when PMM is not configured."""
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        try:
            response = test_client.post(self._UPLOAD_URL, json={})
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        finally:
            sep_app.dependency_overrides = {}

    def test_returns_503_when_upload_not_configured(self, test_client, mock_pmm_api):
        """Assert 503 is returned when upload settings are missing."""
        sep_app.dependency_overrides.pop(require_upload_configured, None)
        response = test_client.post(self._UPLOAD_URL, json={})
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_returns_500_on_upload_error(self, test_client, mock_pmm_api):
        """Assert 500 is returned when the upload service raises an exception."""
        report = _make_report()
        with (
            patch(
                f"{_API}.generate_report",
                new_callable=AsyncMock,
                return_value=report,
            ),
            patch(
                f"{_API}.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
            patch(
                f"{_API}.upload_pdf_report",
                new_callable=AsyncMock,
                side_effect=RuntimeError("upload failed"),
            ),
        ):
            response = test_client.post(self._UPLOAD_URL, json={})

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
