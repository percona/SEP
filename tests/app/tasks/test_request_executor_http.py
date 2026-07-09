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

"""Real-HTTP coverage of the request-scoped NOMAD executor dependency.

Exercises ``get_request_executor`` through a live ``TestClient`` request --
without overriding the executor dependency -- so FastAPI's resolution of the
``Request`` injection and the ``backend`` query parameter on a ``TaskExecutor``
route is verified at the framework level, not just in unit tests.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.main import app as combined_app
from app.tasks.main import tasks_app


@pytest.fixture
def holder_client(regular_user: CasdoorUser) -> TestClient:
    """Yield a Tasks client whose lifecycle holder serves a stub executor."""
    stub = MagicMock()
    stub.get_hosts = MagicMock(return_value={"node1": "10.0.0.1"})
    tasks_app.dependency_overrides[get_current_user] = lambda: regular_user
    tasks_app.state.nomad_lifecycle = SimpleNamespace(current=stub)
    yield TestClient(tasks_app)
    tasks_app.dependency_overrides = {}
    if hasattr(tasks_app.state, "nomad_lifecycle"):
        delattr(tasks_app.state, "nomad_lifecycle")


def test_hosts_route_resolves_real_request_executor(holder_client: TestClient) -> None:
    """``GET /hosts/`` reaches the holder's executor through the real dependency."""
    response = holder_client.get("/hosts/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"node1": "10.0.0.1"}


def test_combined_app_resolves_holder_on_mounted_tasks_state(
    regular_user: CasdoorUser,
) -> None:
    """Under the combined app, a mounted ``/api/tasks`` request finds the holder.

    Regression for the mounted-deployment bug: Starlette resolves ``request.app``
    to the mounted ``tasks_app`` for ``/api/tasks/*`` requests, so the
    ``NomadLifecycle`` holder must live on ``tasks_app.state`` (not the parent
    app's state, which the combined lifespan would otherwise receive).
    """
    stub = MagicMock()
    stub.get_hosts = MagicMock(return_value={"node1": "10.0.0.1"})
    tasks_app.dependency_overrides[get_current_user] = lambda: regular_user
    tasks_app.state.nomad_lifecycle = SimpleNamespace(current=stub)
    try:
        response = TestClient(combined_app).get("/api/tasks/hosts/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"node1": "10.0.0.1"}
    finally:
        tasks_app.dependency_overrides = {}
        if hasattr(tasks_app.state, "nomad_lifecycle"):
            delattr(tasks_app.state, "nomad_lifecycle")
