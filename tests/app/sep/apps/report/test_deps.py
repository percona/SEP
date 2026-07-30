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

"""Define tests for the app.sep.apps.report.deps module."""

from unittest.mock import AsyncMock

import pytest

import app.sep.deps as sep_deps
from app.core.exceptions import HTTPServiceUnavailableException
from app.sep.apps.report import deps as report_deps
from app.sep.apps.report.deps import (
    get_report_index_context,
    require_pmm_api,
)
from app.sep.clients.pmm import PMMRemoteAPI

EXPECTED_SECTIONS = [
    ("advisors", "Advisors"),
    ("alerts", "Alerts"),
    ("backups", "Backups"),
    ("storage", "Disk Usage"),
    ("uptime", "Service Uptime"),
    ("inventory", "Included Services"),
]


class TestRequirePmmApi:
    """Test the ``require_pmm_api`` dependency."""

    @pytest.mark.asyncio
    async def test_returns_client_when_available(self):
        """Assert the PMM API client is returned when it is not ``None``."""
        mock_client = AsyncMock(spec=PMMRemoteAPI)
        result = await require_pmm_api(mock_client)
        assert result is mock_client

    @pytest.mark.asyncio
    async def test_raises_service_unavailable_when_none(self):
        """Assert ``HTTPServiceUnavailableException`` is raised when PMM is ``None``."""
        with pytest.raises(HTTPServiceUnavailableException) as exc:
            await require_pmm_api(None)
        assert exc.value.detail == "PMM is not configured"


class TestPmmDepReExports:
    """Assert the report PMM deps are re-exports of the ``app.sep.deps`` originals."""

    @pytest.mark.parametrize(
        "name",
        ["get_pmm_api", "require_pmm_api", "PMMAPIDep", "RequiredPMMAPIDep"],
    )
    def test_symbol_is_same_object_as_sep_deps(self, name):
        """Assert each re-exported symbol is identical to its ``app.sep.deps`` original.

        Identity is load-bearing: ``dependency_overrides`` and ``mocker.patch`` bind by
        object identity, so a local re-definition would silently break production overrides
        while leaving the suite green.

        :param name: The re-exported symbol name to compare.
        """
        assert getattr(report_deps, name) is getattr(sep_deps, name)


class TestGetReportIndexContext:
    """Test the ``get_report_index_context`` dependency."""

    @pytest.mark.asyncio
    async def test_context_includes_pmm_configured_true_when_api_present(self):
        """Assert ``pmm_configured`` is ``True`` when PMM API is available."""
        base_context: dict = {"user": "test-user", "plugins": []}
        mock_api = AsyncMock(spec=PMMRemoteAPI)

        result = await get_report_index_context(base_context, mock_api)

        assert result["pmm_configured"] is True

    @pytest.mark.asyncio
    async def test_context_includes_pmm_configured_false_when_api_none(self):
        """Assert ``pmm_configured`` is ``False`` when PMM API is ``None``."""
        base_context: dict = {"user": "test-user", "plugins": []}

        result = await get_report_index_context(base_context, None)

        assert result["pmm_configured"] is False

    @pytest.mark.asyncio
    async def test_context_includes_sections_list(self):
        """Assert the context contains the expected sections list."""
        base_context: dict = {}
        mock_api = AsyncMock(spec=PMMRemoteAPI)

        result = await get_report_index_context(base_context, mock_api)

        assert result["sections"] == EXPECTED_SECTIONS

    @pytest.mark.asyncio
    async def test_context_preserves_base_context_keys(self):
        """Assert existing keys from the base context are preserved."""
        base_context: dict = {"user": "test-user", "csrf_token": "abc123"}
        mock_api = AsyncMock(spec=PMMRemoteAPI)

        result = await get_report_index_context(base_context, mock_api)

        assert result["user"] == "test-user"
        assert result["csrf_token"] == "abc123"
        assert "pmm_configured" in result
        assert "sections" in result

    @pytest.mark.asyncio
    async def test_context_returns_same_dict_reference(self):
        """Assert the returned context is the same dict object that was passed in."""
        base_context: dict = {"key": "value"}

        result = await get_report_index_context(base_context, None)

        assert result is base_context
