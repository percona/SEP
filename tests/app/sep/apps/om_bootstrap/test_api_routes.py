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

"""Test the run lifecycle: create, dispatch a step, read progress.

Scoped to this app's own logic -- planning, host/step lookups, conflict
detection -- not SEP's cross-cutting admin-role gate
(``require_minimum_role_for_unsafe_methods``), which resolves its own
credential outside FastAPI's dependency-override seam and needs the full
``sep_app`` plus a real Bearer credential to exercise honestly; that is a
framework-level concern with its own test surface, not something this app's
tests should re-prove. ``@require_minimum_role(UserRole.ADMIN)`` on the
mutating routes is asserted by inspection instead
(``TestAdminGateIsRegistered``).
"""

from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import minimum_role_for
from app.core.auth.models import UserRole
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.om_bootstrap.api_routes import dispatch_run_step, trigger_run
from app.sep.apps.om_bootstrap.app import app as om_bootstrap_app
from app.sep.apps.om_bootstrap.crud import BootstrapRunManager
from app.sep.apps.om_bootstrap.models import BootstrapRun, BootstrapRunStatus
from app.sep.apps.om_bootstrap.persistence import dump_host_states
from app.sep.apps.om_bootstrap.strategy import (
    HostBootstrapState,
    InstallMethod,
    OperatingSystem,
    StepRecord,
    StepStatus,
)
from app.sep.deps import get_current_user, get_session, IsApiAuthenticated

_BASE = "/api/apps/om_bootstrap"
FAKE_TASK_HISTORY_ID = 7


def _fake_tasks_api() -> MagicMock:
    """Build a stand-in Tasks API client whose ``.auth()`` is a real context manager.

    ``_tasks_api_client`` is patched to return this rather than left to
    auto-mock: a bare ``AsyncMock``'s attributes default to ``MagicMock``,
    whose ``.auth(token)`` call is fine, but the production code's
    ``with tasks_api.auth(...):`` needs that return value to actually support
    the context-manager protocol, which a default ``MagicMock`` return value
    does not do meaningfully (it "works" but silently no-ops in a way that
    masked a real bug the first time this test was written).
    """
    client = MagicMock()
    client.auth.return_value = nullcontext()
    return client


def _client(user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Mount the app's API router behind the production auth guard, real session."""
    apps_router = APIRouter(prefix="/apps")
    apps_router.include_router(
        om_bootstrap_app.api_router, prefix=om_bootstrap_app.uri_path
    )
    api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
    api_router.include_router(apps_router)
    fastapi_app = FastAPI()
    fastapi_app.include_router(api_router)
    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    fastapi_app.dependency_overrides[get_session] = lambda: session
    return TestClient(fastapi_app, raise_server_exceptions=False)


class TestAdminGateIsRegistered:
    """Assert the mutating routes actually registered the ADMIN minimum.

    See the module docstring for why this is inspection rather than an
    end-to-end 403 -- ``minimum_role_for`` is the exact function the real gate
    consults, so this is asserting the same fact the gate would enforce, just
    without needing the full auth stack to observe it.
    """

    def test_trigger_run_requires_admin(self) -> None:
        """Creating a run is root-adjacent enough that Adamo scoped it to admins."""
        assert minimum_role_for_endpoint(trigger_run) == UserRole.ADMIN

    def test_dispatch_run_step_requires_admin(self) -> None:
        """Dispatching a step is literal root execution -- same admin-only gate."""
        assert minimum_role_for_endpoint(dispatch_run_step) == UserRole.ADMIN


def minimum_role_for_endpoint(endpoint: object) -> UserRole:
    """Read the role ``@require_minimum_role`` registered for ``endpoint``.

    :param endpoint: The decorated route function.
    :return: Its registered minimum role.
    """

    class _FakeRoute:
        endpoint: object = None

    route = _FakeRoute()
    route.endpoint = endpoint
    return minimum_role_for(route)


class TestTriggerRun:
    """Assert POST /runs plans every host's steps and persists them."""

    def test_creates_a_run_with_every_host_planned(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """Every requested host gets its strategy's full step list, all pending."""
        response = _client(regular_user, session).post(
            f"{_BASE}/runs",
            json={
                "hosts": ["node00", "node01"],
                "install_method": "packages",
                "os": "ubuntu",
                "mongodb_version": "8.0",
                "replica_set_name": "rs-test",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert {host["host"] for host in body["hosts"]} == {"node00", "node01"}
        for host in body["hosts"]:
            assert host["steps"]
            assert all(step["status"] == "pending" for step in host["steps"])

    def test_rejects_an_empty_host_list(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A run over no hosts is a request error, not a run that does nothing."""
        response = _client(regular_user, session).post(
            f"{_BASE}/runs",
            json={
                "hosts": [],
                "install_method": "packages",
                "os": "ubuntu",
                "mongodb_version": "8.0",
                "replica_set_name": "rs-test",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestListBootstrapRuns:
    """Assert GET /runs discovers runs by status, newest first."""

    async def _seed_run(
        self, session: AsyncSession, run_status: BootstrapRunStatus
    ) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRun(
                status=run_status,
                install_method=InstallMethod.PACKAGES,
                os=OperatingSystem.UBUNTU,
                mongodb_version="8.0",
                replica_set_name="rs-test",
            ),
        )

    @pytest.mark.asyncio
    async def test_filters_by_status(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A caller re-discovering in-flight runs sees only the running ones."""
        running = await self._seed_run(session, BootstrapRunStatus.RUNNING)
        await self._seed_run(session, BootstrapRunStatus.SUCCEEDED)

        response = _client(regular_user, session).get(f"{_BASE}/runs?status=running")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert {run["id"] for run in body} == {str(running.id)}

    @pytest.mark.asyncio
    async def test_returns_every_status_when_unfiltered(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """Omitting ``status`` lists runs regardless of where they landed."""
        first = await self._seed_run(session, BootstrapRunStatus.RUNNING)
        second = await self._seed_run(session, BootstrapRunStatus.SUCCEEDED)

        response = _client(regular_user, session).get(f"{_BASE}/runs")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert {run["id"] for run in body} == {str(first.id), str(second.id)}


class TestGetBootstrapRun:
    """Assert GET /runs/{id} reconciles and reports 404 for an unknown run."""

    async def _seed_run(self, session: AsyncSession) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRun(
                install_method=InstallMethod.PACKAGES,
                os=OperatingSystem.UBUNTU,
                mongodb_version="8.0",
                replica_set_name="rs-test",
                hosts=dump_host_states(
                    [
                        HostBootstrapState(
                            host="node00",
                            steps=[
                                StepRecord(
                                    name="pre_check",
                                    status=StepStatus.RUNNING,
                                    task_history_id=42,
                                )
                            ],
                        )
                    ]
                ),
            ),
        )

    @pytest.mark.asyncio
    async def test_returns_404_for_an_unknown_run(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A run id nobody created is a 404, not a 500 or an empty 200."""
        response = _client(regular_user, session).get(f"{_BASE}/runs/{uuid4()}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_reflects_a_reconciled_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A GET reconciles before responding, so a just-finished step shows up now."""
        run = await self._seed_run(session)

        async def _fake_reconcile(
            _tasks_api: object, reconciled_run: BootstrapRun
        ) -> bool:
            reconciled_run.hosts = dump_host_states(
                [
                    HostBootstrapState(
                        host="node00",
                        steps=[
                            StepRecord(name="pre_check", status=StepStatus.SUCCEEDED)
                        ],
                    )
                ]
            )
            return True

        with (
            patch(
                "app.sep.apps.om_bootstrap.api_routes._tasks_api_client",
                AsyncMock(return_value=_fake_tasks_api()),
            ),
            patch(
                "app.sep.apps.om_bootstrap.api_routes.reconcile_run", _fake_reconcile
            ),
        ):
            response = _client(regular_user, session).get(f"{_BASE}/runs/{run.id}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["hosts"][0]["steps"][0]["status"] == "succeeded"


class TestDispatchRunStep:
    """Assert POST .../steps/{name}:dispatch validates host/step and dispatches."""

    async def _seed_run(self, session: AsyncSession) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRun(
                install_method=InstallMethod.PACKAGES,
                os=OperatingSystem.UBUNTU,
                mongodb_version="8.0",
                replica_set_name="rs-test",
                hosts=dump_host_states(
                    [
                        HostBootstrapState(
                            host="node00",
                            steps=[
                                StepRecord(name="pre_check"),
                                StepRecord(
                                    name="configure_repository",
                                    status=StepStatus.RUNNING,
                                    task_history_id=1,
                                ),
                            ],
                        )
                    ]
                ),
            ),
        )

    @pytest.mark.asyncio
    async def test_dispatches_a_pending_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A pending step is dispatched, marked running, and carries its task id."""
        run = await self._seed_run(session)

        with (
            patch(
                "app.sep.apps.om_bootstrap.api_routes._tasks_api_client",
                AsyncMock(return_value=_fake_tasks_api()),
            ),
            patch(
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
                AsyncMock(return_value=FAKE_TASK_HISTORY_ID),
            ),
        ):
            response = _client(regular_user, session).post(
                f"{_BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        step = next(s for s in body["hosts"][0]["steps"] if s["name"] == "pre_check")
        assert step["status"] == "running"
        assert step["task_history_id"] == FAKE_TASK_HISTORY_ID

    @pytest.mark.asyncio
    async def test_404s_for_an_unknown_host(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A host that isn't part of the run cannot have a step dispatched on it."""
        run = await self._seed_run(session)

        response = _client(regular_user, session).post(
            f"{_BASE}/runs/{run.id}/hosts/no-such-host/steps/pre_check:dispatch"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_404s_for_an_unplanned_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A step name outside the host's own planned list is rejected, not silently run."""
        run = await self._seed_run(session)

        response = _client(regular_user, session).post(
            f"{_BASE}/runs/{run.id}/hosts/node00/steps/rs_initiate:dispatch"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_409s_for_a_step_already_running(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """Dispatching a step that's already in flight is a conflict, not a double-dispatch."""
        run = await self._seed_run(session)

        response = _client(regular_user, session).post(
            f"{_BASE}/runs/{run.id}/hosts/node00/steps/configure_repository:dispatch"
        )

        assert response.status_code == status.HTTP_409_CONFLICT
