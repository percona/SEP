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

"""Define tests for the app.sep.plugins.report.routes module."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status

from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.main import sep_app
from app.sep.plugins.report.deps import (
    get_pmm_api,
    get_report_index_context,
    require_pmm_api,
)
from app.sep.plugins.report.models import ReportData, ReportMetadata

_REPORT_INDEX_CONTEXT = {
    "user": "test-user",
    "pmm_configured": True,
    "sections": [
        ("advisors", "Advisors"),
        ("alerts", "Alerts"),
        ("backups", "Backups"),
        ("storage", "Disk Usage"),
        ("uptime", "Service Uptime"),
        ("inventory", "Included Services"),
    ],
}

_REPORT_INDEX_CONTEXT_NO_PMM = {
    "user": "test-user",
    "pmm_configured": False,
    "sections": _REPORT_INDEX_CONTEXT["sections"],
}


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
def _mock_report_index_context():
    """Override the report index context with populated data."""
    sep_app.dependency_overrides[get_report_index_context] = lambda: (
        _REPORT_INDEX_CONTEXT
    )
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_report_index_context_no_pmm():
    """Override the report index context with PMM not configured."""
    sep_app.dependency_overrides[get_report_index_context] = lambda: (
        _REPORT_INDEX_CONTEXT_NO_PMM
    )
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_pmm_api():
    """Return a mock PMMRemoteAPI wired into dependency overrides."""
    mock = AsyncMock(spec=PMMRemoteAPI)
    sep_app.dependency_overrides[get_pmm_api] = lambda: mock
    sep_app.dependency_overrides[require_pmm_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_pmm_unavailable():
    """Override PMM API dependency to return None (not configured)."""
    sep_app.dependency_overrides[get_pmm_api] = lambda: None
    yield
    sep_app.dependency_overrides = {}


class TestReportIndex:
    """Test GET /report/ (landing page)."""

    @pytest.mark.usefixtures("_mock_report_index_context")
    def test_returns_200_with_html(self, test_client):
        """Assert the index page returns 200 with HTML content."""
        response = test_client.get("/report/")
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "text/html; charset=utf-8"

    @pytest.mark.usefixtures("_mock_report_index_context")
    def test_contains_section_names(self, test_client):
        """Assert the page includes the report section labels."""
        response = test_client.get("/report/")
        for _key, label in _REPORT_INDEX_CONTEXT["sections"]:
            assert label in response.text

    @pytest.mark.usefixtures("_mock_report_index_context_no_pmm")
    def test_renders_when_pmm_not_configured(self, test_client):
        """Assert the page still renders when PMM is not configured."""
        response = test_client.get("/report/")
        assert response.status_code == status.HTTP_200_OK


class TestReportGenerate:
    """Test POST /report/generate (HTML report generation)."""

    _GENERATE_URL = "/report/generate"

    @pytest.mark.usefixtures("_mock_report_index_context")
    def test_returns_200_with_html_report(self, test_client, mock_pmm_api):
        """Assert a generated report renders as HTML."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            response = test_client.post(self._GENERATE_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        mock_gen.assert_awaited_once()

    @pytest.mark.usefixtures("_mock_report_index_context")
    def test_passes_default_parameters(self, test_client, mock_pmm_api):
        """Assert default since/until/full/refresh values are forwarded."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.post(self._GENERATE_URL)

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-7d"
        assert kwargs["until"] == "now"
        assert kwargs["full"] is False
        assert kwargs["refresh"] is False

    @pytest.mark.usefixtures("_mock_report_index_context")
    def test_passes_custom_parameters(self, test_client, mock_pmm_api):
        """Assert custom form parameters are forwarded to generate_report."""
        report = _make_report(full=True, refresh=True)
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.post(
                self._GENERATE_URL,
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

    @pytest.mark.usefixtures("_mock_report_index_context")
    def test_report_title_in_response(self, test_client, mock_pmm_api):
        """Assert the report title appears in the rendered HTML."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = test_client.post(self._GENERATE_URL)

        assert "Weekly Health Report" in response.text

    def test_returns_503_when_pmm_unavailable(self, test_client):
        """Assert 503 is returned when PMM is not configured."""
        sep_app.dependency_overrides[get_report_index_context] = lambda: (
            _REPORT_INDEX_CONTEXT
        )
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        try:
            response = test_client.post(self._GENERATE_URL)
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        finally:
            sep_app.dependency_overrides = {}

    @pytest.mark.usefixtures("_mock_report_index_context")
    def test_returns_500_on_generation_error(self, test_client, mock_pmm_api):
        """Assert 500 is returned when report generation raises an exception."""
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            side_effect=RuntimeError("collection failed"),
        ):
            response = test_client.post(self._GENERATE_URL)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestReportGenerateJSON:
    """Test GET /report/generate/json (JSON report generation)."""

    _JSON_URL = "/report/generate/json"

    def test_returns_200_with_json(self, test_client, mock_pmm_api):
        """Assert the JSON endpoint returns 200 with application/json."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = test_client.get(self._JSON_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "application/json"

    def test_response_contains_report_data(self, test_client, mock_pmm_api):
        """Assert the JSON body includes expected top-level keys."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
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
        assert data["full"] is False
        assert data["refresh"] is False

    def test_passes_default_parameters(self, test_client, mock_pmm_api):
        """Assert default query parameters are forwarded."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.get(self._JSON_URL)

        _, kwargs = mock_gen.call_args
        assert kwargs["since"] == "now-7d"
        assert kwargs["until"] == "now"
        assert kwargs["full"] is False
        assert kwargs["refresh"] is False
        assert kwargs["sections"] is None

    def test_passes_custom_parameters(self, test_client, mock_pmm_api):
        """Assert custom query parameters are forwarded to generate_report."""
        report = _make_report(full=True, refresh=True)
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
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

    def test_filters_valid_sections(self, test_client, mock_pmm_api):
        """Assert only valid section names are forwarded."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.get(
                self._JSON_URL,
                params={"sections": ["advisors", "bogus", "storage"]},
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["sections"] == ["advisors", "storage"]

    def test_ignores_all_invalid_sections(self, test_client, mock_pmm_api):
        """Assert sections list becomes empty when all names are invalid."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_gen:
            test_client.get(
                self._JSON_URL,
                params={"sections": ["bogus", "invalid"]},
            )

        _, kwargs = mock_gen.call_args
        assert kwargs["sections"] == []

    def test_metadata_in_json_response(self, test_client, mock_pmm_api):
        """Assert report metadata is present in the JSON response."""
        report = _make_report()
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = test_client.get(self._JSON_URL)

        meta = response.json()["metadata"]
        assert meta["title"] == "Weekly Health Report"
        assert meta["report_week"] == "2026 - Week 14"

    def test_full_flag_reflected_in_json(self, test_client, mock_pmm_api):
        """Assert the full flag value appears in the JSON body."""
        report = _make_report(full=True)
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            return_value=report,
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
            sep_app.dependency_overrides = {}

    def test_returns_500_on_generation_error(self, test_client, mock_pmm_api):
        """Assert 500 is returned when report generation raises an exception."""
        with patch(
            "app.sep.plugins.report.routes.generate_report",
            new_callable=AsyncMock,
            side_effect=RuntimeError("collection failed"),
        ):
            response = test_client.get(self._JSON_URL)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
