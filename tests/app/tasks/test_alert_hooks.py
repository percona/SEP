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

"""Define tests for the app.tasks.alert_hooks resolver."""

from types import SimpleNamespace

import pytest

from app.tasks import alert_hooks
from app.tasks.alert_hooks import build_owner_alert_details, OwnerAlertDetails


def _history(owner: str):
    """Return a stub history whose task owner has the given value."""
    return SimpleNamespace(task=SimpleNamespace(owner=owner))


class TestBuildOwnerAlertDetails:
    """Test the lazy owner -> builder dispatch."""

    @pytest.mark.asyncio
    async def test_returns_none_for_owner_without_builder(self):
        """Return ``None`` for an owner with no registered builder."""
        assert await build_owner_alert_details(_history("ANY")) is None

    @pytest.mark.asyncio
    async def test_delegates_to_registered_builder(self, mocker):
        """Resolve and delegate to the builder registered for the owner."""
        expected = OwnerAlertDetails(source_node="node-x", custom_details={"k": "v"})

        async def _fake_builder(history):
            return expected

        mocker.patch.dict(
            alert_hooks.ALERT_DETAIL_BUILDERS,
            {"OWNED": "some.module:builder"},
            clear=False,
        )
        mocker.patch.dict(
            alert_hooks._RESOLVED, {"some.module:builder": _fake_builder}, clear=False
        )

        assert await build_owner_alert_details(_history("OWNED")) is expected

    @pytest.mark.asyncio
    async def test_swallows_unresolvable_builder(self, mocker):
        """Return ``None`` (logged) when the builder path cannot be imported."""
        mocker.patch.dict(
            alert_hooks.ALERT_DETAIL_BUILDERS,
            {"BROKEN": "no.such.module:builder"},
            clear=False,
        )
        mocker.patch.dict(alert_hooks._RESOLVED, {}, clear=True)

        assert await build_owner_alert_details(_history("BROKEN")) is None
