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

import aiohttp
import pytest
from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import minimum_role_for
from app.core.auth.models import UserRole
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.om_bootstrap.api_routes import (
    dispatch_rollback_step,
    dispatch_run_run_step,
    dispatch_run_step,
    finish_run,
    trigger_run,
)
from app.sep.apps.om_bootstrap.crud import BootstrapRunManager
from app.sep.apps.om_bootstrap.models import BootstrapRun, BootstrapRunStatus
from app.sep.apps.om_bootstrap.persistence import dump_host_states
from app.sep.apps.om_bootstrap.strategy import (
    HostBootstrapState,
    StepRecord,
    StepStatus,
)
from tests.app.sep.apps.om_bootstrap.conftest import api_client, BASE
from tests.app.sep.apps.om_bootstrap.factories import BootstrapRunFactory

FAKE_TASK_HISTORY_ID = 7


def _fake_tasks_api() -> MagicMock:
    """Build a stand-in Tasks API client whose ``.auth()`` is a real context manager.

    Injected through ``get_tasks_client``'s dependency override rather than left
    to auto-mock: a bare ``AsyncMock``'s attributes default to ``MagicMock``,
    whose ``.auth(token)`` call is fine, but the production code's
    ``with tasks_api.auth(...):`` needs that return value to actually support
    the context-manager protocol, which a default ``MagicMock`` return value
    does not do meaningfully (it "works" but silently no-ops in a way that
    masked a real bug the first time this test was written).
    """
    client = MagicMock()
    client.auth.return_value = nullcontext()
    return client


class TestAdminGateIsRegistered:
    """Assert the mutating routes actually registered the ADMIN minimum.

    See the module docstring for why this is inspection rather than an
    end-to-end 403 -- ``minimum_role_for`` is the exact function the real gate
    consults, so this is asserting the same fact the gate would enforce, just
    without needing the full auth stack to observe it.
    """

    def test_trigger_run_requires_admin(self) -> None:
        """Creating a run is root-adjacent enough to be scoped to admins."""
        assert minimum_role_for_endpoint(trigger_run) == UserRole.ADMIN

    def test_dispatch_run_step_requires_admin(self) -> None:
        """Dispatching a step is literal root execution -- same admin-only gate."""
        assert minimum_role_for_endpoint(dispatch_run_step) == UserRole.ADMIN

    def test_dispatch_run_run_step_requires_admin(self) -> None:
        """A run-level dispatch (rs.initiate, user creation) is equally privileged."""
        assert minimum_role_for_endpoint(dispatch_run_run_step) == UserRole.ADMIN

    def test_dispatch_rollback_step_requires_admin(self) -> None:
        """Tearing down a host is as privileged as building it up."""
        assert minimum_role_for_endpoint(dispatch_rollback_step) == UserRole.ADMIN

    def test_finish_run_requires_admin(self) -> None:
        """Declaring a run failed/rolled back is the stepper's own privileged call."""
        assert minimum_role_for_endpoint(finish_run) == UserRole.ADMIN


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
        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs",
            json={
                "hosts": ["node00", "node01", "node02"],
                "install_method": "packages",
                "os": "ubuntu",
                "mongodb_version": "8.0",
                "replica_set_name": "rs-test",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert {host["host"] for host in body["hosts"]} == {
            "node00",
            "node01",
            "node02",
        }
        for host in body["hosts"]:
            assert host["steps"]
            assert all(step["status"] == "pending" for step in host["steps"])

    def test_rejects_an_empty_host_list(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A run over no hosts is a request error, not a run that does nothing."""
        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs",
            json={
                "hosts": [],
                "install_method": "packages",
                "os": "ubuntu",
                "mongodb_version": "8.0",
                "replica_set_name": "rs-test",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_a_repeated_host(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A duplicated host would plan two states no dispatch route could ever tell apart."""
        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs",
            json={
                "hosts": ["node00", "node00"],
                "install_method": "packages",
                "os": "ubuntu",
                "mongodb_version": "8.0",
                "replica_set_name": "rs-test",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_an_install_method_with_no_registered_strategy(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """DOCKER/PODMAN are declared on the enum for later -- not implemented yet."""
        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs",
            json={
                "hosts": ["node00"],
                "install_method": "docker",
                "os": "ubuntu",
                "mongodb_version": "8.0",
                "replica_set_name": "rs-test",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestTriggerRunValidation:
    """Assert POST /runs rejects hosts, versions and names outside the accepted shapes."""

    @staticmethod
    def _payload(**overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "hosts": ["node00"],
            "install_method": "packages",
            "os": "ubuntu",
            "mongodb_version": "8.0",
            "replica_set_name": "rs-test",
        }
        payload.update(overrides)
        return payload

    @pytest.mark.parametrize("host_count", [2, 4])
    def test_rejects_a_host_count_other_than_one_or_three(
        self, regular_user: CasdoorUser, session: AsyncSession, host_count: int
    ) -> None:
        """Only one-member and three-member replica sets are in scope."""
        hosts = [f"node0{index}" for index in range(host_count)]

        response = api_client(regular_user, session).post(
            f"{BASE}/runs", json=self._payload(hosts=hosts)
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize(
        "host", ["node00;reboot", "../etc", "-node", "node 00", "", "a" * 254]
    )
    def test_rejects_a_host_that_is_not_a_node_name(
        self, regular_user: CasdoorUser, session: AsyncSession, host: str
    ) -> None:
        """A host becomes a script filename and a dispatch target, so it is validated."""
        response = api_client(regular_user, session).post(
            f"{BASE}/runs", json=self._payload(hosts=[host])
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.parametrize("version", ["8", "8.0;id", "latest", "8.0.4.1", ""])
    def test_rejects_a_malformed_mongodb_version(
        self, regular_user: CasdoorUser, session: AsyncSession, version: str
    ) -> None:
        """The version selects a repository channel and must be major.minor[.patch]."""
        response = api_client(regular_user, session).post(
            f"{BASE}/runs", json=self._payload(mongodb_version=version)
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.parametrize("name", ["rs\nnet: {}", "rs test", "", "r" * 65])
    def test_rejects_a_malformed_replica_set_name(
        self, regular_user: CasdoorUser, session: AsyncSession, name: str
    ) -> None:
        """The name is written into mongod.conf, so YAML-breaking input is refused."""
        response = api_client(regular_user, session).post(
            f"{BASE}/runs", json=self._payload(replica_set_name=name)
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_accepts_a_full_patch_version(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """major.minor.patch is as valid as major.minor."""
        response = api_client(regular_user, session).post(
            f"{BASE}/runs", json=self._payload(mongodb_version="7.0.14")
        )

        assert response.status_code == status.HTTP_201_CREATED


class TestListBootstrapRuns:
    """Assert GET /runs discovers runs by status, newest first."""

    async def _seed_run(
        self, session: AsyncSession, run_status: BootstrapRunStatus
    ) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
                status=run_status,
            ),
        )

    @pytest.mark.asyncio
    async def test_filters_by_status(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A caller re-discovering in-flight runs sees only the running ones."""
        running = await self._seed_run(session, BootstrapRunStatus.RUNNING)
        await self._seed_run(session, BootstrapRunStatus.SUCCEEDED)

        response = api_client(regular_user, session, _fake_tasks_api()).get(
            f"{BASE}/runs?status=running"
        )

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

        response = api_client(regular_user, session, _fake_tasks_api()).get(
            f"{BASE}/runs"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert {run["id"] for run in body} == {str(first.id), str(second.id)}


class TestGetBootstrapRun:
    """Assert GET /runs/{id} reconciles and reports 404 for an unknown run."""

    async def _seed_run(self, session: AsyncSession) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
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
        response = api_client(regular_user, session, _fake_tasks_api()).get(
            f"{BASE}/runs/{uuid4()}"
        )

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
                "app.sep.apps.om_bootstrap.api_routes.reconcile_run", _fake_reconcile
            ),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).get(
                f"{BASE}/runs/{run.id}"
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["hosts"][0]["steps"][0]["status"] == "succeeded"


class TestDispatchRunStep:
    """Assert POST .../steps/{name}:dispatch validates host/step and dispatches."""

    async def _seed_run(self, session: AsyncSession) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
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
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
                AsyncMock(return_value=FAKE_TASK_HISTORY_ID),
            ),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        step = next(s for s in body["hosts"][0]["steps"] if s["name"] == "pre_check")
        assert step["status"] == "running"
        assert step["task_history_id"] == FAKE_TASK_HISTORY_ID

    @pytest.mark.asyncio
    async def test_records_a_dispatch_that_the_tasks_api_rejects(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A dispatch the Tasks API itself rejects becomes a FAILED step, not a 5xx.

        Without this, a step the Tasks API never even accepts (an unknown or
        unreachable executor target, most concretely) stays PENDING forever:
        nothing ever transitions it, so the stepper's own retry-then-rollback
        policy never engages, and every tick looks identical to the very
        first attempt.
        """
        run = await self._seed_run(session)

        with (
            patch(
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
                AsyncMock(
                    side_effect=HTTPException(
                        status_code=400, detail="Target 'node00' is not available"
                    )
                ),
            ),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        step = next(s for s in body["hosts"][0]["steps"] if s["name"] == "pre_check")
        assert step["status"] == "failed"
        assert step["attempt_count"] == 1
        assert "not available" in step["detail"]
        assert step["task_history_id"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            aiohttp.ClientConnectionError("Cannot connect to host tasks:8443"),
            TimeoutError(),
            PermissionError("scratch directory is not writable"),
        ],
    )
    async def test_records_a_dispatch_that_never_reaches_the_tasks_api(
        self, regular_user: CasdoorUser, session: AsyncSession, error: Exception
    ) -> None:
        """A transport failure or a failed script write is a FAILED attempt, not a 5xx."""
        run = await self._seed_run(session)

        with patch(
            "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
            AsyncMock(side_effect=error),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        step = next(
            s for s in response.json()["hosts"][0]["steps"] if s["name"] == "pre_check"
        )
        assert step["status"] == "failed"
        assert step["attempt_count"] == 1
        assert step["detail"].startswith("Failed to dispatch: ")
        assert step["task_history_id"] is None

    @pytest.mark.asyncio
    async def test_records_a_dispatch_the_tasks_api_accepts_without_an_id(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """The same treatment applies when dispatch_step's own contract is violated."""
        run = await self._seed_run(session)

        with (
            patch(
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
                AsyncMock(
                    side_effect=RuntimeError(
                        "Tasks API did not return a task history id"
                    )
                ),
            ),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        step = next(
            s for s in response.json()["hosts"][0]["steps"] if s["name"] == "pre_check"
        )
        assert step["status"] == "failed"
        assert step["attempt_count"] == 1

    @pytest.mark.asyncio
    async def test_404s_for_an_unknown_host(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A host that isn't part of the run cannot have a step dispatched on it."""
        run = await self._seed_run(session)

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}/hosts/no-such-host/steps/pre_check:dispatch"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_404s_for_an_unplanned_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A step name outside the host's own planned list is rejected, not silently run."""
        run = await self._seed_run(session)

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}/hosts/node00/steps/rs_initiate:dispatch"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_409s_for_a_step_already_running(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """Dispatching a step that's already in flight is a conflict, not a double-dispatch."""
        run = await self._seed_run(session)

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}/hosts/node00/steps/configure_repository:dispatch"
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.asyncio
    @pytest.mark.parametrize("step_status", [StepStatus.SUCCEEDED, StepStatus.SKIPPED])
    async def test_409s_for_a_step_already_done(
        self, regular_user: CasdoorUser, session: AsyncSession, step_status: StepStatus
    ) -> None:
        """A succeeded or skipped step is never re-run on the host."""
        run = await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
                hosts=dump_host_states(
                    [
                        HostBootstrapState(
                            host="node00",
                            steps=[StepRecord(name="pre_check", status=step_status)],
                        )
                    ]
                ),
            ),
        )
        dispatch_step_mock = AsyncMock(return_value=FAKE_TASK_HISTORY_ID)

        with patch(
            "app.sep.apps.om_bootstrap.api_routes.dispatch_step", dispatch_step_mock
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        assert response.status_code == status.HTTP_409_CONFLICT
        dispatch_step_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retries_a_failed_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A failed step is dispatchable again -- that is how the stepper retries."""
        prior_attempts = 1
        run = await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
                hosts=dump_host_states(
                    [
                        HostBootstrapState(
                            host="node00",
                            steps=[
                                StepRecord(
                                    name="pre_check",
                                    status=StepStatus.FAILED,
                                    attempt_count=prior_attempts,
                                )
                            ],
                        )
                    ]
                ),
            ),
        )

        with patch(
            "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
            AsyncMock(return_value=FAKE_TASK_HISTORY_ID),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        step = response.json()["hosts"][0]["steps"][0]
        assert step["status"] == "running"
        assert step["attempt_count"] == prior_attempts + 1

    @pytest.mark.asyncio
    async def test_increments_attempt_count_on_each_dispatch(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A dispatched step's attempt_count grows -- PMM's stepper reads it to cap retries."""
        run = await self._seed_run(session)

        with (
            patch(
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
                AsyncMock(return_value=FAKE_TASK_HISTORY_ID),
            ),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        step = next(
            s for s in response.json()["hosts"][0]["steps"] if s["name"] == "pre_check"
        )
        assert step["attempt_count"] == 1

    @pytest.mark.asyncio
    async def test_forwards_body_params_to_build_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A caller-supplied secret (e.g. keyFile content) reaches the built action."""
        run = await self._seed_run(session)
        build_step = MagicMock(return_value=MagicMock(command=["true"], timeout_s=1))

        with (
            patch(
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
                AsyncMock(return_value=FAKE_TASK_HISTORY_ID),
            ),
            patch(
                "app.sep.apps.om_bootstrap.api_routes.strategy_for",
                return_value=MagicMock(build_step=build_step),
            ),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch",
                json={"params": {"key_file_content": "secret-bytes"}},
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        build_step.assert_called_once()
        assert build_step.call_args.args[-1] == {"key_file_content": "secret-bytes"}

    @pytest.mark.asyncio
    async def test_400s_when_the_strategy_rejects_the_params(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A strategy's ValueError for bad params is the caller's mistake, not a 500."""
        run = await self._seed_run(session)
        build_step = MagicMock(side_effect=ValueError("missing required param"))

        with patch(
            "app.sep.apps.om_bootstrap.api_routes.strategy_for",
            return_value=MagicMock(build_step=build_step),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/steps/pre_check:dispatch"
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestDispatchRunRunStep:
    """Assert POST .../run-steps/{name}:dispatch targets the seed host."""

    async def _seed_run(self, session: AsyncSession) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
                hosts=dump_host_states(
                    [
                        HostBootstrapState(
                            host="node00",
                            steps=[
                                StepRecord(name="verify", status=StepStatus.SUCCEEDED)
                            ],
                        ),
                        HostBootstrapState(
                            host="node01",
                            steps=[
                                StepRecord(name="verify", status=StepStatus.SUCCEEDED)
                            ],
                        ),
                    ]
                ),
                run_steps=[
                    {"name": "rs_initiate", "status": "pending", "attempt_count": 0}
                ],
            ),
        )

    @pytest.mark.asyncio
    async def test_dispatches_to_the_first_host(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """rs.initiate runs on hosts[0] -- the seed member, not any other host."""
        run = await self._seed_run(session)
        dispatch_step_mock = AsyncMock(return_value=FAKE_TASK_HISTORY_ID)

        with (
            patch(
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step", dispatch_step_mock
            ),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/run-steps/rs_initiate:dispatch"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert dispatch_step_mock.call_args.args[3] == "node00"
        run_step = response.json()["run_steps"][0]
        assert run_step["status"] == "running"

    @pytest.mark.asyncio
    async def test_404s_for_an_unplanned_run_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A run-level name outside the run's own planned list is rejected."""
        run = await self._seed_run(session)

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}/run-steps/create_pmm_monitoring_user:dispatch"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_409s_for_a_run_step_already_running(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A run-level step already dispatching cannot be dispatched again."""
        run = await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
                hosts=dump_host_states(
                    [
                        HostBootstrapState(
                            host="node00", steps=[StepRecord(name="verify")]
                        )
                    ]
                ),
                run_steps=[
                    {
                        "name": "rs_initiate",
                        "status": "running",
                        "attempt_count": 1,
                        "task_history_id": 1,
                    }
                ],
            ),
        )

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}/run-steps/rs_initiate:dispatch"
        )

        assert response.status_code == status.HTTP_409_CONFLICT


class TestDispatchRollbackStep:
    """Assert POST .../rollback/{name}:dispatch validates and dispatches teardown."""

    async def _seed_run(self, session: AsyncSession) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
                hosts=dump_host_states(
                    [
                        HostBootstrapState(
                            host="node00",
                            steps=[
                                StepRecord(
                                    name="install_package", status=StepStatus.FAILED
                                )
                            ],
                            rollback_steps=[StepRecord(name="stop_service")],
                        )
                    ]
                ),
            ),
        )

    @pytest.mark.asyncio
    async def test_dispatches_a_pending_rollback_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A pending rollback step is dispatched and marked running."""
        run = await self._seed_run(session)

        with (
            patch(
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
                AsyncMock(return_value=FAKE_TASK_HISTORY_ID),
            ),
        ):
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}/hosts/node00/rollback/stop_service:dispatch"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        rollback_step = response.json()["hosts"][0]["rollback_steps"][0]
        assert rollback_step["status"] == "running"

    @pytest.mark.asyncio
    async def test_404s_for_an_unplanned_rollback_step(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A forward step name is not a rollback step name."""
        run = await self._seed_run(session)

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}/hosts/node00/rollback/install_package:dispatch"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestFinishRun:
    """Assert POST /runs/{id}:finish records the stepper's own terminal decision."""

    async def _seed_run(
        self,
        session: AsyncSession,
        run_status: BootstrapRunStatus = BootstrapRunStatus.RUNNING,
    ) -> BootstrapRun:
        return await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
                status=run_status,
            ),
        )

    @pytest.mark.asyncio
    async def test_marks_a_running_run_failed(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """The stepper declaring retries exhausted lands as FAILED, with its reason."""
        run = await self._seed_run(session)

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}:finish",
            json={"status": "failed", "error": "node00 exhausted retries"},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "failed"
        assert body["error"] == "node00 exhausted retries"
        assert body["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_sweeps_the_runs_step_scripts(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A finished run's scripts are removed, whatever state their steps were in."""
        run = await self._seed_run(session)

        with patch(
            "app.sep.apps.om_bootstrap.api_routes.cleanup_run_scripts"
        ) as cleanup:
            response = api_client(regular_user, session, _fake_tasks_api()).post(
                f"{BASE}/runs/{run.id}:finish", json={"status": "rolled_back"}
            )

        assert response.status_code == status.HTTP_200_OK
        cleanup.assert_called_once_with(str(run.id))

    @pytest.mark.asyncio
    async def test_rejects_succeeded_as_a_requested_status(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """SUCCEEDED is inferred by reconciliation, never requested through this route."""
        run = await self._seed_run(session)

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}:finish", json={"status": "succeeded"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_409s_for_an_already_terminal_run(
        self, regular_user: CasdoorUser, session: AsyncSession
    ) -> None:
        """A run already FAILED/ROLLED_BACK/SUCCEEDED cannot be finished twice."""
        run = await self._seed_run(session, BootstrapRunStatus.SUCCEEDED)

        response = api_client(regular_user, session, _fake_tasks_api()).post(
            f"{BASE}/runs/{run.id}:finish", json={"status": "rolled_back"}
        )

        assert response.status_code == status.HTTP_409_CONFLICT


class TestWritingRoutesLockTheRun:
    """Assert every route that writes a run back reads it under the row lock."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("get", "", None),
            ("post", "/hosts/node00/steps/pre_check:dispatch", None),
            ("post", "/hosts/node00/rollback/stop_service:dispatch", None),
            ("post", "/run-steps/rs_initiate:dispatch", None),
            ("post", ":finish", {"status": "failed"}),
        ],
    )
    async def test_reads_the_run_for_update(
        self,
        regular_user: CasdoorUser,
        session: AsyncSession,
        method: str,
        path: str,
        body: dict[str, str] | None,
    ) -> None:
        """Without the lock, two concurrent writes race and the later save wins."""
        run = await BootstrapRunManager.save(
            session,
            BootstrapRunFactory.build(
                hosts=dump_host_states(
                    [
                        HostBootstrapState(
                            host="node00",
                            steps=[StepRecord(name="pre_check")],
                            rollback_steps=[StepRecord(name="stop_service")],
                        )
                    ]
                ),
                run_steps=[
                    {"name": "rs_initiate", "status": "pending", "attempt_count": 0}
                ],
            ),
        )
        get_run = AsyncMock(return_value=run)

        with (
            patch.object(BootstrapRunManager, "get_run", get_run),
            patch(
                "app.sep.apps.om_bootstrap.api_routes.dispatch_step",
                AsyncMock(return_value=FAKE_TASK_HISTORY_ID),
            ),
            patch(
                "app.sep.apps.om_bootstrap.api_routes.reconcile_run",
                AsyncMock(return_value=False),
            ),
        ):
            client = api_client(regular_user, session, _fake_tasks_api())
            url = f"{BASE}/runs/{run.id}{path}"
            response = (
                client.get(url) if method == "get" else client.post(url, json=body)
            )

        assert response.status_code < status.HTTP_300_MULTIPLE_CHOICES
        assert get_run.await_args is not None
        assert get_run.await_args.kwargs == {"for_update": True}
