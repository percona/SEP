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

"""Define tests for the delivery-executor factory and endpoint splitting."""

from typing import Any

import pytest
from aioresponses import aioresponses
from fastapi import status
from pytest_mock import MockerFixture

from app.core.config import settings
from app.core.exceptions import HTTPConflictException
from app.core.requests import RemoteAPI
from app.core.requests.registry import ClientRegistry
from app.sep.bundle_upload.factory import get_delivery_executor, split_endpoint
from app.sep.bundle_upload.plan import DeliveryPlan, DeliveryPlanError, StepRecord
from app.sep.bundle_upload.seam import BundleSource

_ORIGIN = "https://intake.example.com"
_TICKET_URL = f"{_ORIGIN}/ticket_details?number=CS0001"
_UPLOAD_URL = f"{_ORIGIN}/attachment/upload"
#: The one resolution step plus the terminal upload of the reuse test's plan.
_EXPECTED_REQUEST_COUNT = 2


def _plan(endpoint: str, *, max_bundle_size_mb: int = 30) -> DeliveryPlan:
    """Build a one-resolution-step plan pointed at ``endpoint``.

    :param endpoint: The configured receiver endpoint.
    :param max_bundle_size_mb: The size cap the executor enforces before it
        issues any request.
    :return: The validated plan.
    """
    payload = {
        "endpoint": endpoint,
        "max_bundle_size_mb": max_bundle_size_mb,
        "resolution_steps": [
            {
                "name": "lookup",
                "method": "GET",
                "path": "ticket_details",
                "query": {"number": {"source": "input", "field": "case_ref"}},
                "outputs": {"sys_id": "/result/sys_id"},
            }
        ],
        "upload": {"path": "attachment/upload"},
    }
    return DeliveryPlan(**payload)


def _bundle(size: int | None = None) -> BundleSource:
    """Build a small in-memory bundle, optionally overstating its size.

    :param size: The size to report, for a bundle the plan's cap must reject;
        the real byte count by default.
    :return: The bundle source handed to ``upload_bundle``.
    """
    content = b"bundle-bytes"
    return BundleSource(
        filename="bundle.tar.gz",
        content=content,
        size=len(content) if size is None else size,
    )


async def _send(
    plan: DeliveryPlan,
    captured: list[RemoteAPI],
    *,
    case_ref: str | None = "CS0001",
    size: int | None = None,
) -> None:
    """Run one send through the factory, recording the transport it was given.

    :param plan: The plan to deliver with.
    :param captured: The list the send's transport is appended to, so a caller
        can assert on it after a failure unwound the context.
    :param case_ref: The case reference, ``None`` to withhold the send input the
        plan cites.
    :param size: The bundle size to report, for a send the plan's cap rejects.
    """
    async with get_delivery_executor(plan) as executor:
        captured.append(executor._api)
        await executor.upload_bundle(
            source_ref="atw-incident/1",
            bundle=_bundle(size),
            case_ref=case_ref,
            manifest={},
        )


def _registry_endpoints() -> list[str]:
    """Return the endpoints of every client the process-global registry holds.

    :return: One trailing-slash-stripped endpoint per cached client.
    """
    clients = settings._CLIENT_REGISTRY._clients.values()
    return [str(client.endpoint).rstrip("/") for client in clients]


class TestSplitEndpoint:
    """Cover splitting a configured endpoint into origin, path, and query."""

    def test_origin_only_endpoint_yields_a_root_path(self) -> None:
        """Return the bare origin with a root path and no query pairs."""
        assert split_endpoint("https://intake.example.com") == (
            "https://intake.example.com",
            "/",
            {},
        )

    def test_path_prefix_is_split_off_the_origin(self) -> None:
        """Separate a path prefix from the origin the transport is built on."""
        assert split_endpoint("https://intake.example.com/api/now") == (
            "https://intake.example.com",
            "/api/now",
            {},
        )

    def test_query_pairs_are_returned_separately(self) -> None:
        """Return the endpoint's query pairs for the plan to carry."""
        origin, path, query = split_endpoint(
            "https://intake.example.com/api?sysparm_view=full"
        )

        assert (origin, path) == ("https://intake.example.com", "/api")
        assert query == {"sysparm_view": "full"}

    def test_repeated_query_keys_collapse_to_the_last(self) -> None:
        """Keep the last occurrence when a key repeats in the query string."""
        _origin, _path, query = split_endpoint("https://x.example.com/a?k=1&k=2")

        assert query == {"k": "2"}


class TestGetDeliveryExecutor:
    """Cover building an executor from a configured plan."""

    @pytest.mark.asyncio
    async def test_origin_only_endpoint_leaves_step_paths_untouched(self) -> None:
        """Leave paths alone when the endpoint carries no prefix or query."""
        plan = _plan("https://intake.example.com")

        async with get_delivery_executor(plan) as executor:
            assert executor._plan.resolution_steps[0].path == "ticket_details"
            assert executor._plan.upload.path == "attachment/upload"

    @pytest.mark.asyncio
    async def test_path_prefix_is_rebased_into_every_step(self) -> None:
        """Prefix each resolution step and the upload with the endpoint's path."""
        plan = _plan("https://intake.example.com/api/now")

        async with get_delivery_executor(plan) as executor:
            assert executor._plan.resolution_steps[0].path == "/api/now/ticket_details"
            assert executor._plan.upload.path == "/api/now/attachment/upload"

    @pytest.mark.asyncio
    async def test_endpoint_query_is_merged_into_every_step(self) -> None:
        """Carry the endpoint's query pairs onto each step without dropping its own."""
        plan = _plan("https://intake.example.com/api?sysparm_view=full")

        async with get_delivery_executor(plan) as executor:
            step = executor._plan.resolution_steps[0]
            assert set(step.query) == {"number", "sysparm_view"}
            assert set(executor._plan.upload.query) == {"sysparm_view"}

    @pytest.mark.asyncio
    async def test_the_configured_plan_is_left_unmodified(self) -> None:
        """Leave the caller's plan and its nested steps untouched by the rebase.

        The plan handed in is the process-global ``DIAGNOSTICS_DELIVERY``; a shallow
        copy would share nested step objects and corrupt it for every later send.
        """
        plan = _plan("https://intake.example.com/api/now")
        before = plan.model_dump(mode="json")

        async with get_delivery_executor(plan):
            pass

        assert plan.model_dump(mode="json") == before
        assert plan.resolution_steps[0].path == "ticket_details"

    @pytest.mark.asyncio
    async def test_the_step_observer_reaches_the_executor(self) -> None:
        """Pass the observer through so the caller records per-step progress."""

        def observer(_record: StepRecord) -> None:
            """Stand in for the send log's step recorder."""

        async with get_delivery_executor(
            _plan("https://intake.example.com"), step_observer=observer
        ) as executor:
            assert executor._step_observer is observer

    @pytest.mark.asyncio
    async def test_the_transport_carries_the_origin_alone(self) -> None:
        """Point the client at the origin, leaving path and query to the plan."""
        plan = _plan("https://intake.example.com/api/now?sysparm_view=full")

        async with get_delivery_executor(plan) as executor:
            assert str(executor._api.endpoint).rstrip("/") == _ORIGIN


class TestDeliveryTransportLifetime:
    """Cover the per-send scope of the transport the factory builds."""

    @pytest.mark.asyncio
    async def test_the_transport_is_not_pooled_in_the_client_registry(
        self, mocker: MockerFixture
    ) -> None:
        """Build the client directly, leaving the process-global registry alone.

        The receiver endpoint is operator-changeable at run time, so a client
        pooled on its origin is orphaned the moment the origin changes.
        """
        pooled = mocker.spy(ClientRegistry, "get")

        async with get_delivery_executor(_plan("https://old.example.com")):
            pass
        async with get_delivery_executor(_plan("https://new.example.com")):
            pass

        pooled.assert_not_called()
        pooled_endpoints = _registry_endpoints()
        assert "https://old.example.com" not in pooled_endpoints
        assert "https://new.example.com" not in pooled_endpoints

    @pytest.mark.asyncio
    async def test_the_transport_is_open_inside_and_closed_after(self) -> None:
        """Serve requests for the duration of the send, then close the session."""
        async with get_delivery_executor(_plan(_ORIGIN)) as executor:
            api = executor._api
            assert api._session is not None
            assert not api._session.closed

        assert api._session is None

    @pytest.mark.asyncio
    async def test_the_transport_is_closed_when_the_receiver_rejects_the_upload(
        self,
    ) -> None:
        """Close the session when the terminal upload answers an error status."""
        captured: list[RemoteAPI] = []

        with aioresponses() as mock:
            mock.get(_TICKET_URL, payload={"result": {"sys_id": "SYS1"}})
            mock.post(_UPLOAD_URL, status=status.HTTP_409_CONFLICT, payload={})

            with pytest.raises(HTTPConflictException):
                await _send(_plan(_ORIGIN), captured)

        assert captured[0]._session is None

    @pytest.mark.asyncio
    async def test_the_transport_is_closed_when_the_plan_cannot_be_carried_out(
        self,
    ) -> None:
        """Close the session when the plan cites a send input the caller withheld."""
        captured: list[RemoteAPI] = []

        with pytest.raises(DeliveryPlanError, match="case_ref"):
            await _send(_plan(_ORIGIN), captured, case_ref=None)

        assert captured[0]._session is None

    @pytest.mark.asyncio
    async def test_the_transport_is_closed_when_the_bundle_is_over_the_cap(
        self,
    ) -> None:
        """Close the session for a bundle rejected before any request is issued."""
        captured: list[RemoteAPI] = []
        plan = _plan(_ORIGIN, max_bundle_size_mb=1)

        with pytest.raises(DeliveryPlanError, match="above the configured"):
            await _send(plan, captured, size=2 * 1024 * 1024)

        assert captured[0]._session is None


class TestIntraSendConnectionReuse:
    """Cover one transport serving every request of a single send."""

    @pytest.mark.asyncio
    async def test_one_session_serves_the_resolution_steps_and_the_upload(
        self, mocker: MockerFixture
    ) -> None:
        """Issue every request of one ``upload_bundle`` over the same session."""
        opened = mocker.spy(RemoteAPI, "__aenter__")
        sessions: list[Any] = []

        with aioresponses() as mock:
            mock.get(_TICKET_URL, payload={"result": {"sys_id": "SYS1"}})
            mock.post(_UPLOAD_URL, payload={"result": {"sys_id": "att-9"}})

            async with get_delivery_executor(_plan(_ORIGIN)) as executor:
                sessions.append(executor._api._session)
                await executor.upload_bundle(
                    source_ref="atw-incident/1",
                    bundle=_bundle(),
                    case_ref="CS0001",
                    manifest={"bundle": "diag"},
                )
                sessions.append(executor._api._session)

        assert opened.call_count == 1
        assert sessions[0] is sessions[1]
        assert len(mock.requests) == _EXPECTED_REQUEST_COUNT
