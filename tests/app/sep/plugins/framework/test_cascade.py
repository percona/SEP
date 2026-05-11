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

"""Unit tests for the cascade POST/PUT/DELETE helpers."""

from typing import Any
from unittest.mock import AsyncMock, call

import pytest
from fastapi import HTTPException, status
from pytest_mock import MockerFixture

from app.core.requests.remote_api import RemoteAPI
from app.sep.plugins.framework.cascade import (
    build_derived_payload,
    cascade_create_tasks,
    cascade_delete_tasks,
    cascade_update_tasks,
    CascadeFailure,
    CascadeResult,
)
from app.sep.plugins.framework.schema import DerivedTask


def _parent_payload(**overrides: Any) -> dict[str, Any]:
    """Return a minimal alters-shaped parent task payload for testing."""
    payload = {
        "name": "t1",
        "data": {"meta": {"args": "--execute --target db1.example.com"}},
    }
    payload.update(overrides)
    return payload


# ── build_derived_payload ────────────────────────────────────────────────


class TestBuildDerivedPayload:
    """Cover the pure ``build_derived_payload`` helper."""

    def test_minimal_suffixes_name_and_sets_parent_link(self) -> None:
        """Suffix the parent name and set ``data["parent"]`` by default."""
        result = build_derived_payload(
            _parent_payload(), DerivedTask(name_suffix="-dry-run")
        )

        assert result["name"] == "t1-dry-run"
        assert result["data"]["parent"] == "t1"
        assert result["data"]["meta"]["args"] == "--execute --target db1.example.com"

    def test_applies_arg_substitutions(self) -> None:
        """Apply ``arg_substitutions`` to ``data.meta.args`` literally."""
        result = build_derived_payload(
            _parent_payload(),
            DerivedTask(
                name_suffix="-dry-run",
                arg_substitutions={"--execute": "--dry-run"},
            ),
        )

        assert result["data"]["meta"]["args"] == "--dry-run --target db1.example.com"

    def test_applies_substitutions_in_dict_order(self) -> None:
        """Apply ``arg_substitutions`` in dict insertion order (a→b, then b→c)."""
        parent = {"name": "t1", "data": {"meta": {"args": "a"}}}
        result = build_derived_payload(
            parent,
            DerivedTask(name_suffix="-x", arg_substitutions={"a": "b", "b": "c"}),
        )

        assert result["data"]["meta"]["args"] == "c"

    def test_parent_link_false_omits_parent_key(self) -> None:
        """Skip the ``data["parent"]`` plumbing when ``parent_link`` is false."""
        result = build_derived_payload(
            _parent_payload(),
            DerivedTask(name_suffix="-x", parent_link=False),
        )

        assert "parent" not in result["data"]

    def test_no_meta_args_is_noop_for_substitutions(self) -> None:
        """Skip substitution silently when ``data.meta.args`` is absent."""
        parent = {"name": "t1", "data": {}}
        result = build_derived_payload(
            parent,
            DerivedTask(
                name_suffix="-dry-run",
                arg_substitutions={"--execute": "--dry-run"},
            ),
        )

        assert result["name"] == "t1-dry-run"
        assert result["data"]["parent"] == "t1"
        assert "meta" not in result["data"]

    def test_does_not_mutate_parent_payload(self) -> None:
        """Leave the caller's ``parent_payload`` dict untouched."""
        parent = _parent_payload()
        before = {"name": parent["name"], "args": parent["data"]["meta"]["args"]}
        build_derived_payload(
            parent,
            DerivedTask(
                name_suffix="-dry-run",
                arg_substitutions={"--execute": "--dry-run"},
            ),
        )

        assert parent["name"] == before["name"]
        assert parent["data"]["meta"]["args"] == before["args"]
        assert "parent" not in parent["data"]


# ── cascade_create_tasks ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCascadeCreateTasks:
    """Cover the all-or-nothing POST cascade with rollback."""

    async def test_no_derived_only_posts_parent(self) -> None:
        """POST the parent and skip derived iteration when the spec list is empty."""
        tasks_api = AsyncMock(spec=RemoteAPI)

        await cascade_create_tasks(tasks_api, _parent_payload(), [])

        tasks_api.post.assert_awaited_once_with("/", json=_parent_payload())
        tasks_api.delete.assert_not_awaited()

    @pytest.mark.parametrize("derived_count", [1, 2, 4])
    async def test_all_succeed_posts_parent_then_each_derived_in_order(
        self, derived_count: int
    ) -> None:
        """POST the parent first, then each derived spec in declaration order."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        derived_specs = [
            DerivedTask(name_suffix=f"-d{idx}") for idx in range(derived_count)
        ]

        await cascade_create_tasks(tasks_api, _parent_payload(), derived_specs)

        expected_calls = [
            call("/", json=_parent_payload()),
            *(
                call("/", json=build_derived_payload(_parent_payload(), spec))
                for spec in derived_specs
            ),
        ]
        assert tasks_api.post.await_args_list == expected_calls
        tasks_api.delete.assert_not_awaited()

    async def test_parent_post_failure_re_raises_and_skips_rollback(self) -> None:
        """Skip the rollback loop when the parent POST itself fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.post.side_effect = exc

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_tasks(
                tasks_api, _parent_payload(), [DerivedTask(name_suffix="-x")]
            )

        assert exc_info.value is exc
        tasks_api.delete.assert_not_awaited()

    async def test_first_derived_failure_rolls_back_parent(self) -> None:
        """Roll back the parent only when the first derived POST fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post.side_effect = [
            None,
            HTTPException(status_code=status.HTTP_409_CONFLICT),
        ]

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_tasks(
                tasks_api, _parent_payload(), [DerivedTask(name_suffix="-dry-run")]
            )

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        tasks_api.delete.assert_awaited_once_with("/t1")

    async def test_second_derived_failure_rolls_back_in_reverse_order(self) -> None:
        """DELETE created tasks in reverse creation order (LIFO rollback)."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post.side_effect = [
            None,
            None,
            HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR),
        ]
        derived = [
            DerivedTask(name_suffix="-a"),
            DerivedTask(name_suffix="-b"),
        ]

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_tasks(tasks_api, _parent_payload(), derived)

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert tasks_api.delete.await_args_list == [call("/t1-a"), call("/t1")]

    async def test_rollback_delete_failure_is_logged_and_swallowed(
        self, mocker: MockerFixture
    ) -> None:
        """Log a rollback DELETE failure at WARNING and re-raise the original exception."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        original = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.post.side_effect = [None, original]
        tasks_api.delete.side_effect = HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
        logger_warning = mocker.patch(
            "app.sep.plugins.framework.cascade.logger.warning"
        )

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_tasks(
                tasks_api, _parent_payload(), [DerivedTask(name_suffix="-x")]
            )

        assert exc_info.value is original
        logger_warning.assert_called_once()
        assert "Rollback DELETE failed" in logger_warning.call_args.args[0]


# ── cascade_update_tasks ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCascadeUpdateTasks:
    """Cover the best-effort PUT cascade."""

    async def test_length_mismatch_raises_value_error(self) -> None:
        """Reject ``derived_existing_names`` whose length differs from ``derived_specs``."""
        tasks_api = AsyncMock(spec=RemoteAPI)

        with pytest.raises(ValueError, match="does not match"):
            await cascade_update_tasks(
                tasks_api,
                "t1",
                _parent_payload(),
                ["t1-a"],
                [DerivedTask(name_suffix="-a"), DerivedTask(name_suffix="-b")],
            )

    async def test_all_succeed_returns_success_result(self) -> None:
        """Record every PUT in ``successes`` and report ``result.success`` true."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent_updated = _parent_payload()

        result = await cascade_update_tasks(
            tasks_api,
            "t1",
            parent_updated,
            ["t1-a", "t1-b"],
            [DerivedTask(name_suffix="-a"), DerivedTask(name_suffix="-b")],
        )

        assert result.success
        assert result.successes == ["t1", "t1-a", "t1-b"]
        assert tasks_api.put.await_args_list == [
            call("/t1", json=parent_updated),
            call(
                "/t1-a",
                json=build_derived_payload(
                    parent_updated, DerivedTask(name_suffix="-a")
                ),
            ),
            call(
                "/t1-b",
                json=build_derived_payload(
                    parent_updated, DerivedTask(name_suffix="-b")
                ),
            ),
        ]

    async def test_parent_failure_collects_and_continues_with_derived(self) -> None:
        """Continue with derived PUTs when the parent PUT fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.put.side_effect = [parent_exc, None, None]

        result = await cascade_update_tasks(
            tasks_api,
            "t1",
            _parent_payload(),
            ["t1-a", "t1-b"],
            [DerivedTask(name_suffix="-a"), DerivedTask(name_suffix="-b")],
        )

        assert not result.success
        assert len(result.failures) == 1
        assert result.failures[0].task_name == "t1"
        assert result.failures[0].exception is parent_exc
        assert result.successes == ["t1-a", "t1-b"]

    async def test_derived_failure_collects_and_continues_with_remaining(self) -> None:
        """Continue with remaining derived PUTs when one derived PUT fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        derived_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.put.side_effect = [None, derived_exc, None]

        result = await cascade_update_tasks(
            tasks_api,
            "t1",
            _parent_payload(),
            ["t1-a", "t1-b"],
            [DerivedTask(name_suffix="-a"), DerivedTask(name_suffix="-b")],
        )

        assert not result.success
        assert len(result.failures) == 1
        assert result.failures[0].task_name == "t1-a"
        assert result.failures[0].exception is derived_exc
        assert result.successes == ["t1", "t1-b"]


# ── cascade_delete_tasks ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCascadeDeleteTasks:
    """Cover the best-effort DELETE cascade."""

    @pytest.mark.parametrize("derived_count", [0, 1, 2, 4])
    async def test_deletes_children_first_then_parent(self, derived_count: int) -> None:
        """Issue DELETEs for derived tasks first, then the parent."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        derived_specs = [
            DerivedTask(name_suffix=f"-d{idx}") for idx in range(derived_count)
        ]

        result = await cascade_delete_tasks(tasks_api, "t1", derived_specs)

        expected_calls = [call(f"/t1-d{idx}") for idx in range(derived_count)] + [
            call("/t1")
        ]
        assert tasks_api.delete.await_args_list == expected_calls
        assert result.success
        assert result.successes == [f"t1-d{idx}" for idx in range(derived_count)] + [
            "t1"
        ]

    async def test_http_404_treated_as_success(self) -> None:
        """Treat HTTP 404 on any leg as success (idempotent intent)."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.delete.side_effect = [
            HTTPException(status_code=status.HTTP_404_NOT_FOUND),
            None,
        ]

        result = await cascade_delete_tasks(
            tasks_api, "t1", [DerivedTask(name_suffix="-a")]
        )

        assert result.success
        assert result.successes == ["t1-a", "t1"]
        assert result.failures == []

    async def test_http_500_collected_as_failure(self) -> None:
        """Collect non-404 HTTP errors into ``CascadeResult.failures``."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        derived_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.delete.side_effect = [derived_exc, None]

        result = await cascade_delete_tasks(
            tasks_api, "t1", [DerivedTask(name_suffix="-a")]
        )

        assert not result.success
        assert result.successes == ["t1"]
        assert len(result.failures) == 1
        assert result.failures[0].task_name == "t1-a"
        assert result.failures[0].exception is derived_exc

    async def test_non_http_exception_collected_as_failure(self) -> None:
        """Catch non-HTTP exceptions on a DELETE and collect them as a failure."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        connection_error = ConnectionError("upstream timeout")
        tasks_api.delete.side_effect = [connection_error, None]

        result = await cascade_delete_tasks(
            tasks_api, "t1", [DerivedTask(name_suffix="-a")]
        )

        assert not result.success
        assert result.failures[0].task_name == "t1-a"
        assert result.failures[0].exception is connection_error


# ── CascadeResult ───────────────────────────────────────────────────────


class TestCascadeResult:
    """Cover the ``CascadeResult`` dataclass surface."""

    def test_success_is_true_when_no_failures(self) -> None:
        """Report ``success=True`` for an empty result."""
        assert CascadeResult().success is True

    def test_success_is_false_when_failures_present(self) -> None:
        """Report ``success=False`` when at least one failure is recorded."""
        result = CascadeResult(
            failures=[CascadeFailure("t1", RuntimeError("boom"))],
        )

        assert result.success is False
