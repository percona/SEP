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

"""Define fixtures for plugins tests.

The framework contract-suite fixtures (``contract_client``,
``unauthenticated_contract_client``, ``mock_task_api``, ``mock_inventory_api``)
live here, at the plugins-tests root, so any plugin test module that subclasses
:class:`~tests.app.sep.plugins.framework.contract_suite.DerivedRouterContractTests`
inherits them by supplying only its definition — not only tests under
``framework/``. Each reads the definition under test from ``request.cls.app_def``
and mounts onto a fresh ``FastAPI`` per test, so dependency overrides never leak.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.auth.exceptions import HTTPUnauthorizedException
from app.core.exceptions import HTTPConflictException
from app.models import CasdoorUser
from app.sep.deps import check_for_conflicted_running_tasks, get_api_authenticated_user
from app.sep.main import sep_app
from app.tasks.models import TaskBackendEnum, TaskWrite
from tests.app.factories import GeneratedTaskFactory
from tests.app.sep.plugins.framework.contract_suite import (
    build_contract_client,
    mount_app,
)
from tests.app.sep.plugins.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    SEEDED_TASK_NAME,
)


@pytest.fixture
def generated_task() -> TaskWrite:
    """Return a fake generated task while creating alters."""
    mock_data = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--alter=ADD COLUMN new_column INT --execute",
            "target": "localhost",
            "_schema_name": "public",
            "_table_name": "example_table",
        },
    }
    return GeneratedTaskFactory.build(data=mock_data, backend=TaskBackendEnum.PROXY)


@pytest.fixture
def _mock_check_for_conflicted_running_tasks() -> None:
    """Mock check_for_conflicted_running_tasks."""
    previous = sep_app.dependency_overrides.copy()
    sep_app.dependency_overrides[check_for_conflicted_running_tasks] = lambda: None
    yield
    sep_app.dependency_overrides = previous


@pytest.fixture
def _mock_check_for_conflicted_running_tasks_raises() -> None:
    """Mock check_for_conflicted_running_tasks to raise HTTPConflictException."""

    def raise_conflict() -> None:
        raise HTTPConflictException("Task is already running or pending.")

    previous = sep_app.dependency_overrides.copy()
    sep_app.dependency_overrides[check_for_conflicted_running_tasks] = raise_conflict
    yield
    sep_app.dependency_overrides = previous


def _raise_unauthorized() -> None:
    raise HTTPUnauthorizedException


@pytest.fixture
def mock_task_api(request: pytest.FixtureRequest) -> MockTaskAPI:
    """Return a Tasks-API mock seeded with one task owned by the bound definition."""
    api = MockTaskAPI()
    api.seed_task(SEEDED_TASK_NAME, owner=request.cls.app_def.owner)
    return api


@pytest.fixture
def mock_inventory_api() -> MockInventoryAPI:
    """Return an Inventory-API mock seeded at the mock-id constants."""
    return MockInventoryAPI()


@pytest.fixture
def contract_client(
    request: pytest.FixtureRequest,
    regular_user: CasdoorUser,
    mock_task_api: MockTaskAPI,
    mock_inventory_api: MockInventoryAPI,
) -> TestClient:
    """Return an authenticated contract client for the bound definition."""
    return build_contract_client(
        request.cls.app_def,
        user=regular_user,
        tasks_api=mock_task_api,
        inventory_api=mock_inventory_api,
    )


@pytest.fixture
def unauthenticated_contract_client(
    request: pytest.FixtureRequest,
) -> TestClient:
    """Return a contract client whose auth dep raises, to exercise the 401 path."""
    app = mount_app(request.cls.app_def)
    app.dependency_overrides[get_api_authenticated_user] = _raise_unauthorized
    return TestClient(app, raise_server_exceptions=False)
