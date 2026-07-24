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

"""Define tests for the ATW diagnostics-send configuration gate."""

import pytest
from pytest_mock import MockerFixture

from app.core.exceptions import HTTPServiceUnavailableException
from app.sep.apps.atw.deps import (
    diagnostics_send_disabled_reasons,
    require_diagnostics_send_configured,
)
from app.sep.bundle_upload.plan import DeliveryPlan
from app.sep.config import sep_settings


class TestDiagnosticsSendDisabledReasons:
    """Cover the reasons the send action is withheld from the UI."""

    def test_unconfigured_delivery_yields_one_reason(
        self, mocker: MockerFixture
    ) -> None:
        """Report the single reason a send cannot run without a receiver."""
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", None)

        assert diagnostics_send_disabled_reasons() == [
            "Diagnostics delivery is not configured"
        ]

    def test_configured_delivery_yields_no_reasons(
        self, mocker: MockerFixture, delivery_plan: DeliveryPlan
    ) -> None:
        """Report nothing to withhold once a receiver is configured."""
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", delivery_plan)

        assert diagnostics_send_disabled_reasons() == []


class TestRequireDiagnosticsSendConfigured:
    """Cover the 503 gate the send endpoint declares."""

    @pytest.mark.asyncio
    async def test_raises_503_carrying_the_reasons(self, mocker: MockerFixture) -> None:
        """Refuse the send with a 503 naming why it is unavailable."""
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", None)

        with pytest.raises(HTTPServiceUnavailableException) as exc_info:
            await require_diagnostics_send_configured()

        assert "Diagnostics delivery is not configured" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_passes_when_configured(
        self, mocker: MockerFixture, delivery_plan: DeliveryPlan
    ) -> None:
        """Let the send through once a receiver is configured."""
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", delivery_plan)

        assert await require_diagnostics_send_configured() is None
