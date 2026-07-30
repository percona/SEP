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

"""Tests that the rendered footer reflects a live FOOTER_TEMPLATE override."""

from string import Template
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_mock import MockerFixture
from starlette.datastructures import URL

from app import __summary__, __version__
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.config import sep_settings
from app.sep.deps import get_default_context


@pytest.mark.asyncio
async def test_default_context_footer_reflects_template_override(
    regular_user: CasdoorUser, mocker: MockerFixture
) -> None:
    """An overridden FOOTER_TEMPLATE is rendered per request in the context."""
    sep_settings._set_snapshot(
        {"FOOTER_TEMPLATE": Template("$summary v$version OVERRIDE")}
    )
    mocker.patch("app.sep.deps.get_username_mapping", new=AsyncMock(return_value={}))
    mocker.patch(
        "app.sep.deps.AppStateManager.all_lifecycle_states",
        new=AsyncMock(return_value={}),
    )
    request = SimpleNamespace(state=SimpleNamespace(csrf_token="token"))

    context = await get_default_context(
        request, regular_user, URL("http://test"), AsyncMock()
    )

    assert context["footer_text"] == f"{__summary__} v{__version__} OVERRIDE"
