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

Mounted at ``/api/plugins/report/`` via ``plugins_router`` in
``app/sep/api/router.py``.
"""

from datetime import datetime, UTC
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
from app.sep.plugins.report.models import ReportData, ReportMetadata

API_BASE = "/api/plugins/report"


def _make_report(**overrides) -> ReportData:
    """Build a minimal ``ReportData`` with sensible defaults."""
    defaults = {
        "metadata": ReportMetadata(
            title="Weekly Health Report",
            generated_at=datetime(2026, 3, 31, 12, 0, 0, tzinfo=UTC),
            report_week="2026 - Week 14",
            report_interval="now-7d to now",
        ),
    }
    defaults.update(overrides)
    return ReportData(**defaults)


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
    """Test GET /api/plugins/report/config."""

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
    """Test GET /api/plugins/report/generate/json."""

    _JSON_URL = f"{API_BASE}/generate/json"

    def test_returns_200_with_json(self, test_client, mock_pmm_api):
        """Assert the JSON endpoint returns 200 with application/json."""
        with patch(
            "app.sep.plugins.report.api_routes.generate_report",
            new_callable=AsyncMock,
            return_value=_make_report(),
        ):
            response = test_client.get(self._JSON_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "application/json"
        assert response.json()["metadata"]["title"] == "Weekly Health Report"

    def test_passes_default_parameters(self, test_client, mock_pmm_api):
        """Assert default query parameters are forwarded."""
        with patch(
            "app.sep.plugins.report.api_routes.generate_report",
            new_callable=AsyncMock,
            return_value=_make_report(),
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
            "app.sep.plugins.report.api_routes.generate_report",
            new_callable=AsyncMock,
            return_value=_make_report(full=True, refresh=True),
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
            "app.sep.plugins.report.api_routes.generate_report",
            new_callable=AsyncMock,
            return_value=_make_report(),
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
            "app.sep.plugins.report.api_routes.generate_report",
            new_callable=AsyncMock,
            return_value=_make_report(),
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

    def test_returns_503_when_pmm_unavailable(self, test_client):
        """Assert 503 is returned when PMM is not configured."""
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        try:
            response = test_client.get(self._JSON_URL)
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        finally:
            sep_app.dependency_overrides.pop(get_pmm_api, None)

    def test_requires_authentication(self, unauthenticated_client):
        """Unauthenticated requests return 401."""
        response = unauthenticated_client.get(self._JSON_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestReportGeneratePdfApi:
    """Test POST /api/plugins/report/generate/pdf."""

    _PDF_URL = f"{API_BASE}/generate/pdf"

    def test_returns_200_with_pdf(self, test_client, mock_pmm_api):
        """Assert a generated report is returned as a PDF download."""
        pdf_bytes = b"%PDF-1.4 fake content"
        with (
            patch(
                "app.sep.plugins.report.api_routes.generate_report",
                new_callable=AsyncMock,
                return_value=_make_report(),
            ),
            patch(
                "app.sep.plugins.report.api_routes.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=pdf_bytes,
            ),
        ):
            response = test_client.post(self._PDF_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == pdf_bytes
        disposition = response.headers["content-disposition"]
        assert "Health_and_Security_Report_2026-03-31.pdf" in disposition
        assert disposition.startswith("attachment")

    def test_passes_custom_parameters(self, test_client, mock_pmm_api):
        """Assert custom form parameters are forwarded to generate_report."""
        with (
            patch(
                "app.sep.plugins.report.api_routes.generate_report",
                new_callable=AsyncMock,
                return_value=_make_report(),
            ) as mock_gen,
            patch(
                "app.sep.plugins.report.api_routes.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
        ):
            test_client.post(
                self._PDF_URL,
                data={
                    "since": "now-30d",
                    "until": "now-1d",
                    "full": "true",
                    "refresh": "true",
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
            response = test_client.post(self._PDF_URL)
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        finally:
            sep_app.dependency_overrides.pop(get_pmm_api, None)

    def test_requires_authentication(self, unauthenticated_client):
        """Unauthenticated requests return 401."""
        response = unauthenticated_client.post(self._PDF_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestReportUploadApi:
    """Test POST /api/plugins/report/upload."""

    _UPLOAD_URL = f"{API_BASE}/upload"

    @pytest.fixture
    def _mock_upload_configured(self):
        """Override the upload dependency to allow requests."""
        sep_app.dependency_overrides[require_upload_configured] = lambda: None
        yield
        sep_app.dependency_overrides.pop(require_upload_configured, None)

    @pytest.mark.usefixtures("_mock_upload_configured")
    def test_returns_200_with_json(self, test_client, mock_pmm_api):
        """Assert a successful upload returns 200 with the upload result."""
        upload_result = {"sys_id": "abc123", "status": "uploaded"}
        with (
            patch(
                "app.sep.plugins.report.api_routes.generate_report",
                new_callable=AsyncMock,
                return_value=_make_report(),
            ),
            patch(
                "app.sep.plugins.report.api_routes.generate_pdf_report",
                new_callable=AsyncMock,
                return_value=b"%PDF-1.4",
            ),
            patch(
                "app.sep.plugins.report.api_routes.upload_pdf_report",
                new_callable=AsyncMock,
                return_value=upload_result,
            ),
        ):
            response = test_client.post(self._UPLOAD_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == upload_result

    def test_returns_503_when_upload_not_configured(self, test_client, mock_pmm_api):
        """Assert 503 when upload is not configured (default settings)."""
        response = test_client.post(self._UPLOAD_URL)
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_requires_authentication(self, unauthenticated_client):
        """Unauthenticated requests return 401."""
        response = unauthenticated_client.post(self._UPLOAD_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
