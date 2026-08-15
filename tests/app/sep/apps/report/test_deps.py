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
