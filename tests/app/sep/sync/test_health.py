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

"""Define tests for the app.sep.sync.health module."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from starlette.routing import Match

from app.core.exceptions import HTTPNotFoundException
from app.core.requests import RemoteAPI
from app.inventory.main import inventory_app
from app.inventory.models import SyncHealthWrite, SyncOutcomeEnum
from app.sep.inventory import CreatedNode
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.sync.constants import INVENTORY_PATH_SEGMENTS
from app.sep.sync.exceptions import (
    ExecutorHostNotFoundError,
    SyncInstanceAlreadyInProgressError,
)
from app.sep.sync.health import _describe_sync_error, SyncHealthReporter
from tests.app.factories import CreatedNodeFactory

#: A credential-bearing DSN, so a test can assert the secret never reaches the
#: payload rather than only that the message was dropped.
LEAKY_DSN = "postgres://u:hunter2@h/db"
SECRET = "hunter2"

NODE = SyncInventoryEntityTypeEnum.NODE
MIRRORED = frozenset({NODE})


@pytest.fixture
def created_node() -> CreatedNode:
    """Return the node every recorded attempt in this module is about."""
    return CreatedNodeFactory.build()


@pytest.fixture
def inventory_api() -> AsyncMock:
    """Return the inventory client the reporter posts through."""
    return AsyncMock(spec=RemoteAPI)


@pytest.fixture
def reporter(inventory_api: AsyncMock) -> SyncHealthReporter:
    """Return a reporter that owns the node level."""
    return SyncHealthReporter(inventory_api, MIRRORED)


def _posted(inventory_api: AsyncMock) -> tuple[str, dict[str, str]]:
    """Return the path and JSON body of the single POST the reporter issued."""
    inventory_api.post.assert_awaited_once()
    call = inventory_api.post.await_args
    return call.args[0], call.kwargs["json"]


class TestRecordedOutcomes:
    """Test which attempts the reporter reports, and as what."""

    @pytest.mark.asyncio
    async def test_a_compared_attempt_reports_success(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Post a success once the block declares it held real source data."""
        async with reporter.record(NODE, created_node) as attempt:
            attempt.mark_compared()

        path, body = _posted(inventory_api)
        assert path == f"/nodes/{created_node.id}/sync-health"
        assert body["outcome"] == SyncOutcomeEnum.SUCCESS

    @pytest.mark.asyncio
    async def test_an_uncompared_attempt_reports_nothing(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Report nothing when the block returns without holding source data.

        This is the filtered-out early return, which leaves the surrounding
        ``manage_sync_item`` on its clean-exit path exactly as a real sync does.
        """
        async with reporter.record(NODE, created_node):
            pass

        inventory_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_raising_attempt_reports_failure_and_re_raises(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Post a failure, then let the exception reach ``manage_sync_item``."""
        with pytest.raises(RuntimeError, match="boom"):
            async with reporter.record(NODE, created_node):
                raise RuntimeError("boom")

        _, body = _posted(inventory_api)
        assert body["outcome"] == SyncOutcomeEnum.FAILURE
        assert body["error"]

    @pytest.mark.asyncio
    async def test_a_failure_after_comparing_is_still_a_failure(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Report the raise, not the marker, when the block fails after comparing."""

        async def compare_then_fail() -> None:
            async with reporter.record(NODE, created_node) as attempt:
                attempt.mark_compared()
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await compare_then_fail()

        _, body = _posted(inventory_api)
        assert body["outcome"] == SyncOutcomeEnum.FAILURE

    @pytest.mark.asyncio
    async def test_a_success_payload_validates_as_the_route_body(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Emit a success body the inventory route accepts.

        The reporter and the route are wired together only by this dict's
        shape, so asserting its keys here would stop one layer short of the
        model that consumes them.
        """
        async with reporter.record(NODE, created_node) as attempt:
            attempt.mark_compared()

        _, body = _posted(inventory_api)
        assert SyncHealthWrite.model_validate(body).outcome is SyncOutcomeEnum.SUCCESS

    @pytest.mark.asyncio
    async def test_a_failure_payload_validates_as_the_route_body(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Emit a failure body the inventory route accepts, error included.

        The outcome/error consistency rule lives on the same model the route
        validates through, so a description the allowlist reduced to nothing
        would be refused here rather than at runtime.
        """
        with pytest.raises(RuntimeError):
            async with reporter.record(NODE, created_node):
                raise RuntimeError("boom")

        _, body = _posted(inventory_api)
        assert SyncHealthWrite.model_validate(body).outcome is SyncOutcomeEnum.FAILURE

    @pytest.mark.asyncio
    async def test_the_payload_carries_the_time_the_block_began(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Send the attempt's own start time so inventory can order by attempt."""
        before = datetime.now(UTC)

        async with reporter.record(NODE, created_node) as attempt:
            attempt.mark_compared()

        _, body = _posted(inventory_api)
        attempted_at = datetime.fromisoformat(body["attempted_at"])
        assert before <= attempted_at <= datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_the_payload_time_is_not_truncated_to_the_second(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Keep sub-second resolution, which the inventory guards order on.

        ``utc_now`` zeroes the microsecond, which would hand two attempts within
        one second the same ordering key — and the guards admit an equal one, so
        the later arrival would win whichever attempt was actually newer.
        """
        seen = set()
        for _ in range(50):
            inventory_api.post.reset_mock()
            async with reporter.record(NODE, created_node) as attempt:
                attempt.mark_compared()
            _, body = _posted(inventory_api)
            seen.add(datetime.fromisoformat(body["attempted_at"]).microsecond)

        assert seen != {0}


class TestUnmirroredLevels:
    """Test that a level the syncer does not mirror is never written."""

    @pytest.mark.asyncio
    async def test_a_clean_attempt_reports_nothing(
        self, inventory_api: AsyncMock, created_node: CreatedNode
    ) -> None:
        """Pass a success through untouched when the level is not mirrored."""
        reporter = SyncHealthReporter(inventory_api, frozenset())

        async with reporter.record(NODE, created_node) as attempt:
            attempt.mark_compared()

        inventory_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_raising_attempt_reports_nothing_and_re_raises(
        self, inventory_api: AsyncMock, created_node: CreatedNode
    ) -> None:
        """Pass a failure through untouched when the level is not mirrored."""
        reporter = SyncHealthReporter(inventory_api, frozenset())

        with pytest.raises(RuntimeError):
            async with reporter.record(NODE, created_node):
                raise RuntimeError("boom")

        inventory_api.post.assert_not_awaited()


class TestBestEffortDelivery:
    """Test that a failed bookkeeping write never changes the sync's outcome."""

    @pytest.mark.asyncio
    async def test_a_failed_success_post_is_swallowed(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Leave a healthy sync healthy when the freshness write cannot land."""
        inventory_api.post.side_effect = HTTPNotFoundException("gone")

        with caplog.at_level("ERROR"):
            async with reporter.record(NODE, created_node) as attempt:
                attempt.mark_compared()

        assert "Failed to record sync health" in caplog.text

    @pytest.mark.asyncio
    async def test_a_failed_failure_post_lets_the_original_error_propagate(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Report the sync's own failure, not the bookkeeping write's."""
        inventory_api.post.side_effect = HTTPNotFoundException("gone")

        with pytest.raises(RuntimeError, match="boom"):
            async with reporter.record(NODE, created_node):
                raise RuntimeError("boom")


class _Payload(BaseModel):
    """Stand in for any third-party model whose errors echo the input."""

    value: int


class TestDescribeSyncError:
    """Test what an exception is allowed to contribute to a stored description."""

    def test_an_empty_stringifying_exception_still_describes(self) -> None:
        """Produce a non-empty description, which the write model requires."""
        assert _describe_sync_error(KeyError()) == "KeyError"

    def test_a_mapped_http_exception_keeps_only_its_status(self) -> None:
        """Drop the remote response body a project HTTP exception carries."""
        described = _describe_sync_error(
            HTTPNotFoundException(f"upstream: {LEAKY_DSN}")
        )

        assert described == (f"HTTPNotFoundException: HTTP {status.HTTP_404_NOT_FOUND}")

    def test_a_bare_http_exception_keeps_only_its_status(self) -> None:
        """Cover the arm ``exception_for_status`` takes when no class is mapped."""
        described = _describe_sync_error(
            HTTPException(status.HTTP_502_BAD_GATEWAY, detail="<html>…</html>")
        )

        assert described == f"HTTPException: HTTP {status.HTTP_502_BAD_GATEWAY}"

    def test_a_third_party_exception_contributes_only_its_type(self) -> None:
        """Store no text from an exception whose message SEP never authored."""
        described = _describe_sync_error(OSError(f"could not connect to {LEAKY_DSN}"))

        assert described == "OSError"

    def test_a_validation_error_contributes_only_its_type(self) -> None:
        """Keep the offending input a validation error echoes out of the column."""
        with pytest.raises(ValidationError) as caught:
            _Payload.model_validate({"value": SECRET})

        assert _describe_sync_error(caught.value) == "ValidationError"

    def test_an_allowlisted_exception_keeps_its_message(self) -> None:
        """Store the sync bookkeeping the allowlisted errors interpolate."""
        described = _describe_sync_error(SyncInstanceAlreadyInProgressError())

        assert described.startswith("SyncInstanceAlreadyInProgressError: ")
        assert "sync items" in described

    def test_an_allowlisted_exception_keeps_its_supplied_detail(self) -> None:
        """Store a run-level conflict message, which no sync item evidences.

        The allowlist opts the whole message in, so a conflict described by a
        supplied detail rather than by an item list is persisted verbatim too, and
        must therefore stay bookkeeping-only in the same way.
        """
        described = _describe_sync_error(
            SyncInstanceAlreadyInProgressError(
                detail="A run of syncer 'pmm' is being created already.",
            )
        )

        assert described == (
            "SyncInstanceAlreadyInProgressError: A run of syncer 'pmm' is being "
            "created already."
        )

    def test_an_executor_host_error_contributes_only_its_type(self) -> None:
        """Keep the executor-host map out of a column any reader can fetch.

        ``ExecutorHostNotFoundError`` is a ``SyncError`` and reaches this from
        the ``fetch_schema`` / ``fetch_table`` task-target lookup, so an
        allowlist keyed on the shared base would opt it in — its message carries
        the whole Tasks-API host table, which the write's service-principal gate
        does not protect on the read side.
        """
        described = _describe_sync_error(
            ExecutorHostNotFoundError("db-1", "10.0.0.1", {"executor-1": "10.0.0.99"})
        )

        assert described == "ExecutorHostNotFoundError"

    def test_a_subclass_of_an_allowlisted_error_contributes_only_its_type(
        self,
    ) -> None:
        """Refuse to extend the allowlist down a hierarchy it never opted in.

        A subclass is free to interpolate context its base never did, so
        membership is by exact type: adding one must be a deliberate edit here
        rather than something a new exception inherits.
        """

        class _DerivedInProgressError(SyncInstanceAlreadyInProgressError):
            def __init__(self) -> None:
                Exception.__init__(self, f"connected as {LEAKY_DSN}")

        described = _describe_sync_error(_DerivedInProgressError())

        assert described == "_DerivedInProgressError"
        assert SECRET not in described


class TestErrorTextReachesThePayload:
    """Test that the description contract holds end to end, not only in isolation."""

    @pytest.mark.asyncio
    async def test_an_upstream_body_never_reaches_the_payload(
        self,
        reporter: SyncHealthReporter,
        inventory_api: AsyncMock,
        created_node: CreatedNode,
    ) -> None:
        """Keep a credential in an upstream error body out of the stored column."""
        with pytest.raises(HTTPNotFoundException):
            async with reporter.record(NODE, created_node):
                raise HTTPNotFoundException(f"upstream said: {LEAKY_DSN}")

        _, body = _posted(inventory_api)
        assert body["error"] == (
            f"HTTPNotFoundException: HTTP {status.HTTP_404_NOT_FOUND}"
        )
        assert SECRET not in str(body)


class TestReportedPathsAreRegisteredRoutes:
    """Test that ``INVENTORY_PATH_SEGMENTS`` still names a route the inventory app serves.

    Guards against the two silently drifting apart.
    """

    @pytest.mark.parametrize("entity_type", list(INVENTORY_PATH_SEGMENTS))
    def test_the_posted_path_resolves_to_a_registered_route(
        self, entity_type: SyncInventoryEntityTypeEnum
    ) -> None:
        """Match the path ``_post`` builds against the inventory app's routes.

        Renaming the route the segment is meant to address should fail this
        test rather than only 404 silently in production, where ``_post``'s
        best-effort ``except Exception`` would swallow it.
        """
        path = f"/{INVENTORY_PATH_SEGMENTS[entity_type]}/1/sync-health"
        scope = {"type": "http", "method": "POST", "path": path}

        assert any(
            route.matches(scope)[0] == Match.FULL for route in inventory_app.routes
        )
