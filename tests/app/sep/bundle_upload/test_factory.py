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

import pytest

from app.sep.bundle_upload.factory import get_delivery_executor, split_endpoint
from app.sep.bundle_upload.plan import DeliveryPlan, StepRecord


def _plan(endpoint: str) -> DeliveryPlan:
    """Build a one-resolution-step plan pointed at ``endpoint``.

    :param endpoint: The configured receiver endpoint.
    :return: The validated plan.
    """
    payload = {
        "endpoint": endpoint,
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
        """Separate a path prefix from the origin the transport is pooled on."""
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

        executor = await get_delivery_executor(plan)

        assert executor._plan.resolution_steps[0].path == "ticket_details"
        assert executor._plan.upload.path == "attachment/upload"

    @pytest.mark.asyncio
    async def test_path_prefix_is_rebased_into_every_step(self) -> None:
        """Prefix each resolution step and the upload with the endpoint's path."""
        plan = _plan("https://intake.example.com/api/now")

        executor = await get_delivery_executor(plan)

        assert executor._plan.resolution_steps[0].path == "/api/now/ticket_details"
        assert executor._plan.upload.path == "/api/now/attachment/upload"

    @pytest.mark.asyncio
    async def test_endpoint_query_is_merged_into_every_step(self) -> None:
        """Carry the endpoint's query pairs onto each step without dropping its own."""
        plan = _plan("https://intake.example.com/api?sysparm_view=full")

        executor = await get_delivery_executor(plan)

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

        await get_delivery_executor(plan)

        assert plan.model_dump(mode="json") == before
        assert plan.resolution_steps[0].path == "ticket_details"

    @pytest.mark.asyncio
    async def test_the_step_observer_reaches_the_executor(self) -> None:
        """Pass the observer through so the caller records per-step progress."""

        def observer(_record: StepRecord) -> None:
            """Stand in for the send log's step recorder."""

        executor = await get_delivery_executor(
            _plan("https://intake.example.com"), step_observer=observer
        )

        assert executor._step_observer is observer
