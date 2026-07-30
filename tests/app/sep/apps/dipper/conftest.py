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

"""Define fixtures for dipper plugin tests."""

from unittest.mock import AsyncMock

import pytest

from app.sep.apps.dipper.deps import get_pmm_api
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.main import sep_app
from tests.app.sep.conftest import (  # noqa: F401
    mock_inventory_api_dep,
    mock_task_api_dep,
    test_client,
)


@pytest.fixture
def mock_pmm_api_dep() -> AsyncMock:
    """Override the Dipper ``get_pmm_api`` dependency with a mock PMM client.

    Tests set ``.get_nodes`` / ``.get_services`` return values (or side effects)
    per case. To exercise the unconfigured path, override ``get_pmm_api`` to
    return ``None`` directly instead of using this fixture.
    """
    mock = AsyncMock(spec=PMMRemoteAPI)
    sentinel = object()
    previous = sep_app.dependency_overrides.get(get_pmm_api, sentinel)
    sep_app.dependency_overrides[get_pmm_api] = lambda: mock
    yield mock
    if previous is sentinel:
        sep_app.dependency_overrides.pop(get_pmm_api, None)
    else:
        sep_app.dependency_overrides[get_pmm_api] = previous
