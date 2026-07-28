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

from app.tasks import hook_resolver
from app.tasks.alert_hooks import build_owner_alert_details, OwnerAlertDetails


def _history(builder: str | None):
    """Return a stub history whose task declares the given builder path."""
    return SimpleNamespace(task=SimpleNamespace(alert_detail_builder=builder))


class TestBuildOwnerAlertDetails:
    """Test the lazy per-task ``alert_detail_builder`` dispatch."""

    @pytest.mark.asyncio
    async def test_returns_none_for_task_without_builder(self):
        """Return ``None`` for a task declaring no builder path."""
        assert await build_owner_alert_details(_history(None)) is None

    @pytest.mark.asyncio
    async def test_delegates_to_declared_builder(self, mocker):
        """Resolve and delegate to the builder the task declares."""
        expected = OwnerAlertDetails(source_node="node-x", custom_details={"k": "v"})

        async def _fake_builder(history):
            return expected

        mocker.patch.dict(
            hook_resolver._RESOLVED, {"some.module:builder": _fake_builder}, clear=False
        )

        assert (
            await build_owner_alert_details(_history("some.module:builder")) is expected
        )

    @pytest.mark.asyncio
    async def test_swallows_unresolvable_builder(self, mocker):
        """Return ``None`` (logged) when the builder path cannot be imported."""
        mocker.patch.dict(hook_resolver._RESOLVED, {}, clear=True)

        assert (
            await build_owner_alert_details(_history("no.such.module:builder")) is None
        )

    @pytest.mark.asyncio
    async def test_swallows_builder_runtime_error(self, mocker):
        """Return ``None`` (logged) when a resolved builder raises at runtime."""

        async def _raising_builder(history):
            raise RuntimeError("boom")

        mocker.patch.dict(
            hook_resolver._RESOLVED,
            {"some.module:raising": _raising_builder},
            clear=False,
        )

        assert await build_owner_alert_details(_history("some.module:raising")) is None
