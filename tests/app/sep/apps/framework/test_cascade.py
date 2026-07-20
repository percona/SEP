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

import copy
from typing import Any, Literal
from unittest.mock import AsyncMock, call

import pytest
from fastapi import HTTPException, status
from pytest_mock import MockerFixture

from app.core.exceptions import HTTPInternalServerErrorException, HTTPNotFoundException
from app.core.requests.remote_api import RemoteAPI
from app.sep.apps.framework.cascade import (
    build_derived_payload,
    build_predecessor_chain_execute_body,
    build_predecessor_payload,
    cascade_create_independent_tasks,
    cascade_create_predecessors,
    cascade_create_tasks,
    cascade_delete_predecessors,
    cascade_delete_tasks,
    cascade_update_predecessors,
    cascade_update_tasks,
    CascadeFailure,
    CascadeResult,
)
from app.sep.apps.framework.schema import ChainedPredecessor, DerivedTask
from app.sep.apps.framework.spec import RESERVED_FORM_KEY


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

    def test_strips_reserved_form_key_from_child(self) -> None:
        """Drop the parent's create-form stamp from the derived child copy."""
        parent = _parent_payload()
        parent["data"][RESERVED_FORM_KEY] = {"task_name": "t1"}

        result = build_derived_payload(parent, DerivedTask(name_suffix="-dry-run"))

        assert RESERVED_FORM_KEY not in result["data"]
        assert parent["data"][RESERVED_FORM_KEY] == {"task_name": "t1"}

    def test_applies_payload_substitutions(self) -> None:
        """Apply ``payload_substitutions`` to ``data.payload`` literally."""
        parent = {
            "name": "my-backup",
            "data": {
                "backup_type": "pbm_config",
                "payload": "file:///plugins/backup_mongo/pbm_config_payload",
            },
        }
        result = build_derived_payload(
            parent,
            DerivedTask(
                name_suffix="-logical",
                payload_substitutions={"pbm_config": "pbm_logical"},
                data_overrides={"backup_type": "pbm_logical"},
            ),
        )

        assert result["name"] == "my-backup-logical"
        assert result["data"]["parent"] == "my-backup"
        assert result["data"]["backup_type"] == "pbm_logical"
        assert (
            result["data"]["payload"]
            == "file:///plugins/backup_mongo/pbm_logical_payload"
        )

    def test_applies_payload_substitutions_in_dict_order(self) -> None:
        """Apply ``payload_substitutions`` in dict insertion order."""
        parent = {
            "name": "my-backup",
            "data": {
                "backup_type": "pbm_config",
                "payload": "file:///plugins/backup_mongo/pbm_config_payload",
            },
        }
        result = build_derived_payload(
            parent,
            DerivedTask(
                name_suffix="-physical",
                payload_substitutions={
                    "pbm_config": "pbm_logical",
                    "pbm_logical": "pbm_physical",
                },
                data_overrides={"backup_type": "pbm_physical"},
            ),
        )

        assert result["data"]["backup_type"] == "pbm_physical"
        assert (
            result["data"]["payload"]
            == "file:///plugins/backup_mongo/pbm_physical_payload"
        )

    def test_no_payload_is_noop_for_payload_substitutions(self) -> None:
        """Skip payload substitution silently when ``data.payload`` is absent."""
        parent = {"name": "t1", "data": {"backup_type": "pbm_config"}}
        result = build_derived_payload(
            parent,
            DerivedTask(
                name_suffix="-logical",
                payload_substitutions={"pbm_config": "pbm_logical"},
                data_overrides={"backup_type": "pbm_logical"},
            ),
        )

        assert result["data"]["backup_type"] == "pbm_logical"
        assert "payload" not in result["data"]

    def test_status_payload_substitution_chains_through_logical(
        self,
    ) -> None:
        """Chain ``pbm_config`` → ``pbm_logical`` → ``pbm_status`` in the payload path."""
        parent = {
            "name": "my-backup",
            "data": {
                "backup_type": "pbm_config",
                "payload": "file:///plugins/backup_mongo/pbm_config_payload",
            },
        }
        result = build_derived_payload(
            parent,
            DerivedTask(
                name_suffix="-status",
                payload_substitutions={
                    "pbm_config": "pbm_logical",
                    "pbm_logical": "pbm_status",
                },
                data_overrides={"backup_type": "pbm_status"},
            ),
        )

        assert result["name"] == "my-backup-status"
        assert result["data"]["backup_type"] == "pbm_status"
        assert (
            result["data"]["payload"]
            == "file:///plugins/backup_mongo/pbm_status_payload"
        )


def _backup_mongo_parent_payload() -> dict[str, Any]:
    """Return a minimal backup_mongo-shaped parent task payload for testing."""
    return {
        "name": "my-backup",
        "data": {
            "backup_type": "pbm_config",
            "payload": "file:///plugins/backup_mongo/pbm_config_payload",
        },
    }


def _backup_mongo_derived_specs() -> list[DerivedTask]:
    """Return derived specs for the backup_mongo logical/physical/status cascade."""
    return [
        DerivedTask(
            name_suffix="-logical",
            payload_substitutions={"pbm_config": "pbm_logical"},
            data_overrides={"backup_type": "pbm_logical"},
        ),
        DerivedTask(
            name_suffix="-physical",
            payload_substitutions={
                "pbm_config": "pbm_logical",
                "pbm_logical": "pbm_physical",
            },
            data_overrides={"backup_type": "pbm_physical"},
        ),
        DerivedTask(
            name_suffix="-status",
            payload_substitutions={
                "pbm_config": "pbm_logical",
                "pbm_logical": "pbm_status",
            },
            data_overrides={"backup_type": "pbm_status"},
        ),
    ]


class TestBackupMongoDerivedCascade:
    """Cover ``build_derived_payload`` with backup_mongo-shaped substitution maps."""

    def test_logical_physical_status_payloads(self) -> None:
        """Suffix names and rewrite payload paths for each derived leg."""
        parent = _backup_mongo_parent_payload()
        logical, physical, status = [
            build_derived_payload(parent, spec)
            for spec in _backup_mongo_derived_specs()
        ]

        assert logical["data"]["payload"].endswith("pbm_logical_payload")
        assert physical["data"]["payload"].endswith("pbm_physical_payload")
        assert status["data"]["payload"].endswith("pbm_status_payload")

    @pytest.mark.asyncio
    async def test_cascade_create_posts_parent_and_three_derived(self) -> None:
        """POST the parent first, then each derived spec in declaration order."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent = _backup_mongo_parent_payload()
        derived_specs = _backup_mongo_derived_specs()

        await cascade_create_tasks(tasks_api, parent, derived_specs)

        expected_calls = [
            call("/", json=parent),
            *(
                call("/", json=build_derived_payload(parent, spec))
                for spec in derived_specs
            ),
        ]
        assert tasks_api.post.await_args_list == expected_calls
        tasks_api.delete.assert_not_awaited()


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
        logger_warning = mocker.patch("app.sep.apps.framework.cascade.logger.warning")

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_tasks(
                tasks_api, _parent_payload(), [DerivedTask(name_suffix="-x")]
            )

        assert exc_info.value is original
        logger_warning.assert_called_once()
        assert "Rollback DELETE failed" in logger_warning.call_args.args[0]


# ── cascade_create_independent_tasks ─────────────────────────────────────


@pytest.mark.asyncio
class TestCascadeCreateIndependentTasks:
    """Cover the parent + N independent children POST cascade with rollback."""

    async def test_posts_parent_then_each_child_in_order(self) -> None:
        """POST the parent first, then each independent child in declaration order."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent = {"name": "p1", "data": {}}
        children = [
            {"name": "c1", "data": {"parent": "p1"}},
            {"name": "c2", "data": {"parent": "p1"}},
        ]

        await cascade_create_independent_tasks(tasks_api, parent, children)

        assert tasks_api.post.await_args_list == [
            call("/", json=parent),
            call("/", json=children[0]),
            call("/", json=children[1]),
        ]
        tasks_api.delete.assert_not_awaited()

    async def test_no_children_only_posts_parent(self) -> None:
        """POST the parent and skip the children loop when the list is empty."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent = {"name": "p1", "data": {}}

        await cascade_create_independent_tasks(tasks_api, parent, [])

        tasks_api.post.assert_awaited_once_with("/", json=parent)
        tasks_api.delete.assert_not_awaited()

    async def test_parent_post_failure_re_raises_and_skips_rollback(self) -> None:
        """Skip the rollback loop when the parent POST itself fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.post.side_effect = exc

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_independent_tasks(
                tasks_api,
                {"name": "p1", "data": {}},
                [{"name": "c1", "data": {}}],
            )

        assert exc_info.value is exc
        tasks_api.delete.assert_not_awaited()

    async def test_child_post_failure_rolls_back_in_reverse_order(self) -> None:
        """DELETE created tasks in reverse creation order (LIFO rollback)."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post.side_effect = [
            None,
            None,
            HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR),
        ]
        parent = {"name": "p1", "data": {}}
        children = [
            {"name": "c1", "data": {"parent": "p1"}},
            {"name": "c2", "data": {"parent": "p1"}},
        ]

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_independent_tasks(tasks_api, parent, children)

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert tasks_api.delete.await_args_list == [call("/c1"), call("/p1")]

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
        logger_warning = mocker.patch("app.sep.apps.framework.cascade.logger.warning")

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_independent_tasks(
                tasks_api,
                {"name": "p1", "data": {}},
                [{"name": "c1", "data": {}}],
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

    async def test_parent_failure_no_rename_continues_with_derived(self) -> None:
        """Continue with derived PUTs when the parent PUT fails and no rename was attempted."""
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

    async def test_parent_rename_failure_skips_derived_loop(self) -> None:
        """Skip derived PUTs when a parent rename fails (would orphan children)."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.put.side_effect = [parent_exc]
        parent_updated = _parent_payload(name="t2")

        result = await cascade_update_tasks(
            tasks_api,
            "t1",
            parent_updated,
            ["t1-a", "t1-b"],
            [DerivedTask(name_suffix="-a"), DerivedTask(name_suffix="-b")],
        )

        tasks_api.put.assert_awaited_once_with("/t1", json=parent_updated)
        assert not result.success
        assert result.successes == []
        assert [f.task_name for f in result.failures] == ["t1", "t1-a", "t1-b"]
        assert result.failures[0].exception is parent_exc
        assert isinstance(result.failures[1].exception, RuntimeError)
        assert "parent rename failed" in str(result.failures[1].exception)

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
        derived_names = [f"t1-d{idx}" for idx in range(derived_count)]

        result = await cascade_delete_tasks(tasks_api, "t1", derived_names)

        expected_calls = [call(f"/t1-d{idx}") for idx in range(derived_count)] + [
            call("/t1")
        ]
        assert tasks_api.delete.await_args_list == expected_calls
        assert result.success
        assert result.successes == [*derived_names, "t1"]

    async def test_deletes_orphan_renamed_derived_names_directly(self) -> None:
        """Use the caller's actual derived names rather than recomputing from suffixes.

        Regression guard for the rename-orphan scenario: after a partial rename
        update (parent renamed but a derived rename failed), the stored derived
        names no longer match the schema suffix convention. The caller fetches
        the actual names and passes them in — the cascade must NOT recompute.
        """
        tasks_api = AsyncMock(spec=RemoteAPI)
        result = await cascade_delete_tasks(tasks_api, "new", ["old-a"])

        assert tasks_api.delete.await_args_list == [call("/old-a"), call("/new")]
        assert result.success
        assert result.successes == ["old-a", "new"]

    async def test_http_404_treated_as_success(self) -> None:
        """Treat HTTP 404 on any leg as success (idempotent intent)."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.delete.side_effect = [
            HTTPNotFoundException(),
            None,
        ]

        result = await cascade_delete_tasks(tasks_api, "t1", ["t1-a"])

        assert result.success
        assert result.successes == ["t1-a", "t1"]
        assert result.failures == []

    async def test_http_500_collected_as_failure(self) -> None:
        """Collect non-404 HTTP errors into ``CascadeResult.failures``."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        derived_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.delete.side_effect = [derived_exc, None]

        result = await cascade_delete_tasks(tasks_api, "t1", ["t1-a"])

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

        result = await cascade_delete_tasks(tasks_api, "t1", ["t1-a"])

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

    def test_raise_if_failed_does_not_raise_on_success(self) -> None:
        """Return without raising when the cascade has no failures."""
        CascadeResult().raise_if_failed(op="update")
        CascadeResult(successes=["t1", "t1-a"]).raise_if_failed(op="delete")

    @pytest.mark.parametrize(
        ("op", "message"),
        [
            ("create", "Partial create failure; incomplete task group"),
            ("update", "Partial update failure; inconsistent task group"),
            ("delete", "Partial delete failure; orphaned tasks"),
        ],
    )
    def test_raise_if_failed_raises_with_structured_detail(
        self, op: Literal["create", "update", "delete"], message: str
    ) -> None:
        """Raise HTTP 500 with a structured task-name-to-error detail mapping."""
        result = CascadeResult(
            failures=[
                CascadeFailure("t1-a", RuntimeError("boom")),
                CascadeFailure("t1-b", ConnectionError("timeout")),
            ],
        )

        with pytest.raises(HTTPInternalServerErrorException) as exc_info:
            result.raise_if_failed(op=op)

        assert exc_info.value.detail == {
            "message": message,
            "errors": {
                "t1-a": "boom",
                "t1-b": "timeout",
            },
        }

    def test_raise_if_failed_nests_failures_when_task_name_is_message(self) -> None:
        """Keep the human-readable message when a failing task is named ``message``."""
        result = CascadeResult(
            failures=[CascadeFailure("message", RuntimeError("boom"))],
        )

        with pytest.raises(HTTPInternalServerErrorException) as exc_info:
            result.raise_if_failed(op="delete")

        assert exc_info.value.detail == {
            "message": "Partial delete failure; orphaned tasks",
            "errors": {"message": "boom"},
        }


# ── build_predecessor_payload (SEP-1123) ─────────────────────────────────


def _predecessor_payload(**overrides: Any) -> dict[str, Any]:
    """Return a minimal plugin-built predecessor payload for testing."""
    payload = {
        "name": "ignored-by-cascade",
        "data": {"meta": {"args": "--pre-check"}},
    }
    payload.update(overrides)
    return payload


class TestBuildPredecessorPayload:
    """Cover the pure ``build_predecessor_payload`` helper."""

    def test_minimal_suffixes_name_and_sets_parent_link(self) -> None:
        """Suffix the parent name and set ``data["parent"]`` by default."""
        result = build_predecessor_payload(
            _parent_payload(),
            _predecessor_payload(),
            ChainedPredecessor(name_suffix="-pre-checks"),
        )

        assert result["name"] == "t1-pre-checks"
        assert result["data"]["parent"] == "t1"
        assert result["data"]["meta"]["args"] == "--pre-check"

    def test_parent_link_false_omits_parent_key(self) -> None:
        """Skip ``data["parent"]`` plumbing when ``parent_link`` is false."""
        result = build_predecessor_payload(
            _parent_payload(),
            _predecessor_payload(),
            ChainedPredecessor(name_suffix="-x", parent_link=False),
        )

        assert "parent" not in result["data"]

    def test_predecessor_name_is_overridden(self) -> None:
        """Override any plugin-set ``name`` on the predecessor payload."""
        result = build_predecessor_payload(
            _parent_payload(),
            _predecessor_payload(name="plugin-chose-this"),
            ChainedPredecessor(name_suffix="-pre-checks"),
        )

        assert result["name"] == "t1-pre-checks"

    def test_adds_data_key_when_absent_with_parent_link(self) -> None:
        """Create ``data`` via ``setdefault`` when the predecessor payload lacks it."""
        pred = {"name": "ignored"}
        result = build_predecessor_payload(
            _parent_payload(),
            pred,
            ChainedPredecessor(name_suffix="-x"),
        )

        assert result["data"] == {"parent": "t1"}

    def test_preserves_other_data_keys(self) -> None:
        """Preserve unrelated keys under ``data`` when applying ``parent_link``."""
        pred = {"name": "ignored", "data": {"other": "x"}}
        result = build_predecessor_payload(
            _parent_payload(),
            pred,
            ChainedPredecessor(name_suffix="-x"),
        )

        assert result["data"] == {"other": "x", "parent": "t1"}

    def test_does_not_mutate_inputs(self) -> None:
        """Leave both caller payload dicts untouched."""
        parent = _parent_payload()
        parent_before = copy.deepcopy(parent)
        pred = _predecessor_payload()
        pred_before = copy.deepcopy(pred)

        build_predecessor_payload(
            parent, pred, ChainedPredecessor(name_suffix="-pre-checks")
        )

        assert parent == parent_before
        assert pred == pred_before


# ── build_predecessor_chain_execute_body ───────────────────────────────


class TestBuildPredecessorChainExecuteBody:
    """Cover the pure chain execute body builder."""

    def test_empty_specs_raises_value_error(self) -> None:
        """Reject an empty predecessor spec list."""
        with pytest.raises(ValueError, match="at least one predecessor"):
            build_predecessor_chain_execute_body("t1", [])

    def test_single_predecessor_halt(self) -> None:
        """Map a single predecessor to chain into the parent with halt."""
        body = build_predecessor_chain_execute_body(
            "t1",
            [ChainedPredecessor(name_suffix="-pre-checks", on_failure="halt")],
        )

        assert body == {
            "chain_task_names": ["t1"],
            "chain_on_failure": False,
        }

    def test_single_predecessor_continue(self) -> None:
        """Map ``on_failure="continue"`` to ``chain_on_failure=True``."""
        body = build_predecessor_chain_execute_body(
            "t1",
            [ChainedPredecessor(name_suffix="-pre-checks", on_failure="continue")],
        )

        assert body == {
            "chain_task_names": ["t1"],
            "chain_on_failure": True,
        }

    def test_multi_predecessor_order(self) -> None:
        """Chain remaining predecessors before the parent name."""
        body = build_predecessor_chain_execute_body(
            "t1",
            [
                ChainedPredecessor(name_suffix="-pred1"),
                ChainedPredecessor(name_suffix="-pred2"),
            ],
        )

        assert body == {
            "chain_task_names": ["t1-pred2", "t1"],
            "chain_on_failure": False,
        }


# ── cascade_create_predecessors ──────────────────────────────────────────


@pytest.mark.asyncio
class TestCascadeCreatePredecessors:
    """Cover the predecessor create-only cascade."""

    async def test_empty_list_raises_value_error(self) -> None:
        """Reject an empty predecessor list rather than silently downgrading."""
        tasks_api = AsyncMock(spec=RemoteAPI)

        with pytest.raises(ValueError, match="at least one predecessor"):
            await cascade_create_predecessors(tasks_api, _parent_payload(), [])

        tasks_api.post.assert_not_awaited()

    async def test_single_predecessor_success(self) -> None:
        """POST parent then predecessor without firing execute."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        spec = ChainedPredecessor(name_suffix="-pre-checks", on_failure="halt")
        pred_payload = _predecessor_payload()
        parent_payload = _parent_payload()

        await cascade_create_predecessors(
            tasks_api, parent_payload, [(spec, pred_payload)]
        )

        expected_pred_built = build_predecessor_payload(
            parent_payload, pred_payload, spec
        )
        assert tasks_api.post.await_args_list == [
            call("/", json=parent_payload),
            call("/", json=expected_pred_built),
        ]
        tasks_api.delete.assert_not_awaited()

    async def test_multi_predecessor_success(self) -> None:
        """POST parent and every predecessor without firing execute."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        specs = [
            ChainedPredecessor(name_suffix="-pred1"),
            ChainedPredecessor(name_suffix="-pred2"),
        ]
        pred_payloads = [_predecessor_payload(), _predecessor_payload()]
        parent_payload = _parent_payload()

        await cascade_create_predecessors(
            tasks_api,
            parent_payload,
            list(zip(specs, pred_payloads, strict=True)),
        )

        first_built = build_predecessor_payload(
            parent_payload, pred_payloads[0], specs[0]
        )
        second_built = build_predecessor_payload(
            parent_payload, pred_payloads[1], specs[1]
        )
        assert tasks_api.post.await_args_list == [
            call("/", json=parent_payload),
            call("/", json=first_built),
            call("/", json=second_built),
        ]

    async def test_parent_create_failure_no_rollback(self) -> None:
        """Skip rollback when the parent POST itself fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.post.side_effect = exc

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_predecessors(
                tasks_api,
                _parent_payload(),
                [(ChainedPredecessor(name_suffix="-x"), _predecessor_payload())],
            )

        assert exc_info.value is exc
        tasks_api.delete.assert_not_awaited()

    async def test_first_predecessor_create_failure_rolls_back_parent(self) -> None:
        """Roll back the parent when the first predecessor POST fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        exc = HTTPException(status_code=status.HTTP_409_CONFLICT)
        tasks_api.post.side_effect = [None, exc]
        specs = [
            ChainedPredecessor(name_suffix="-a"),
            ChainedPredecessor(name_suffix="-b"),
        ]
        pred_payloads = [_predecessor_payload(), _predecessor_payload()]

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_predecessors(
                tasks_api,
                _parent_payload(),
                list(zip(specs, pred_payloads, strict=True)),
            )

        assert exc_info.value is exc
        assert tasks_api.delete.await_args_list == [call("/t1")]

    async def test_second_predecessor_create_failure_rolls_back_lifo(self) -> None:
        """Roll back the first predecessor and parent in reverse after the second predecessor POST fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.post.side_effect = [None, None, exc]
        specs = [
            ChainedPredecessor(name_suffix="-a"),
            ChainedPredecessor(name_suffix="-b"),
        ]
        pred_payloads = [_predecessor_payload(), _predecessor_payload()]

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_predecessors(
                tasks_api,
                _parent_payload(),
                list(zip(specs, pred_payloads, strict=True)),
            )

        assert exc_info.value is exc
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
        logger_warning = mocker.patch("app.sep.apps.framework.cascade.logger.warning")

        with pytest.raises(HTTPException) as exc_info:
            await cascade_create_predecessors(
                tasks_api,
                _parent_payload(),
                [
                    (
                        ChainedPredecessor(name_suffix="-pre-checks"),
                        _predecessor_payload(),
                    )
                ],
            )

        assert exc_info.value is original
        assert tasks_api.delete.await_args_list == [call("/t1")]
        assert logger_warning.call_count == len(tasks_api.delete.await_args_list)
        for warning_call in logger_warning.call_args_list:
            assert "Rollback DELETE failed" in warning_call.args[0]


# ── cascade_update_predecessors ──────────────────────────────────────────


@pytest.mark.asyncio
class TestCascadeUpdatePredecessors:
    """Cover the best-effort PUT cascade for predecessors."""

    async def test_length_mismatch_raises_value_error(self) -> None:
        """Reject existing-names whose length differs from the spec list."""
        tasks_api = AsyncMock(spec=RemoteAPI)

        with pytest.raises(ValueError, match="does not match"):
            await cascade_update_predecessors(
                tasks_api,
                "t1",
                _parent_payload(),
                ["t1-a"],
                [
                    (ChainedPredecessor(name_suffix="-a"), _predecessor_payload()),
                    (ChainedPredecessor(name_suffix="-b"), _predecessor_payload()),
                ],
            )

    async def test_all_succeed_returns_success_result(self) -> None:
        """Record every PUT in ``successes`` and report ``result.success`` true."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent_updated = _parent_payload()
        specs_with_payloads = [
            (ChainedPredecessor(name_suffix="-a"), _predecessor_payload()),
            (ChainedPredecessor(name_suffix="-b"), _predecessor_payload()),
        ]

        result = await cascade_update_predecessors(
            tasks_api,
            "t1",
            parent_updated,
            ["t1-a", "t1-b"],
            specs_with_payloads,
        )

        assert result.success
        assert result.successes == ["t1", "t1-a", "t1-b"]
        expected_first = build_predecessor_payload(
            parent_updated, specs_with_payloads[0][1], specs_with_payloads[0][0]
        )
        expected_second = build_predecessor_payload(
            parent_updated, specs_with_payloads[1][1], specs_with_payloads[1][0]
        )
        assert tasks_api.put.await_args_list == [
            call("/t1", json=parent_updated),
            call("/t1-a", json=expected_first),
            call("/t1-b", json=expected_second),
        ]

    async def test_parent_failure_no_rename_continues_with_predecessors(self) -> None:
        """Continue with predecessor PUTs when the parent PUT fails and no rename was attempted."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.put.side_effect = [parent_exc, None, None]

        result = await cascade_update_predecessors(
            tasks_api,
            "t1",
            _parent_payload(),
            ["t1-a", "t1-b"],
            [
                (ChainedPredecessor(name_suffix="-a"), _predecessor_payload()),
                (ChainedPredecessor(name_suffix="-b"), _predecessor_payload()),
            ],
        )

        assert not result.success
        assert len(result.failures) == 1
        assert result.failures[0].task_name == "t1"
        assert result.failures[0].exception is parent_exc
        assert result.successes == ["t1-a", "t1-b"]

    async def test_parent_rename_rejected_upfront(self) -> None:
        """Reject a parent rename before any PUT — the chain wiring stores the old name."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent_updated = _parent_payload(name="t2")

        with pytest.raises(ValueError, match="does not support renaming the parent"):
            await cascade_update_predecessors(
                tasks_api,
                "t1",
                parent_updated,
                ["t1-a"],
                [(ChainedPredecessor(name_suffix="-a"), _predecessor_payload())],
            )

        tasks_api.put.assert_not_awaited()

    async def test_predecessor_rename_rejected_upfront(self) -> None:
        """Reject a predecessor rename before any PUT — the chain wiring stores the old name."""
        tasks_api = AsyncMock(spec=RemoteAPI)

        with pytest.raises(ValueError, match="does not support renaming predecessors"):
            await cascade_update_predecessors(
                tasks_api,
                "t1",
                _parent_payload(),
                ["t1-old"],
                [
                    (
                        ChainedPredecessor(name_suffix="-new"),
                        _predecessor_payload(),
                    )
                ],
            )

        tasks_api.put.assert_not_awaited()

    async def test_single_predecessor_put_failure_collects_and_continues(
        self,
    ) -> None:
        """Continue with remaining predecessor PUTs when one fails."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        pred_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        tasks_api.put.side_effect = [None, pred_exc, None]

        result = await cascade_update_predecessors(
            tasks_api,
            "t1",
            _parent_payload(),
            ["t1-a", "t1-b"],
            [
                (ChainedPredecessor(name_suffix="-a"), _predecessor_payload()),
                (ChainedPredecessor(name_suffix="-b"), _predecessor_payload()),
            ],
        )

        assert not result.success
        assert len(result.failures) == 1
        assert result.failures[0].task_name == "t1-a"
        assert result.failures[0].exception is pred_exc
        assert result.successes == ["t1", "t1-b"]

    async def test_empty_predecessor_lists_put_only_parent(self) -> None:
        """PUT only the parent when both predecessor inputs are empty."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        parent_updated = _parent_payload()

        result = await cascade_update_predecessors(
            tasks_api,
            "t1",
            parent_updated,
            [],
            [],
        )

        tasks_api.put.assert_awaited_once_with("/t1", json=parent_updated)
        assert result.success
        assert result.successes == ["t1"]


# ── cascade_delete_predecessors ──────────────────────────────────────────


@pytest.mark.asyncio
class TestCascadeDeletePredecessors:
    """Cover the children-first DELETE cascade for predecessors."""

    @pytest.mark.parametrize("predecessor_count", [0, 1, 2])
    async def test_deletes_predecessors_first_then_parent(
        self, predecessor_count: int
    ) -> None:
        """Issue DELETEs for predecessors first, then the parent."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        predecessor_names = [f"t1-pre{idx}" for idx in range(predecessor_count)]

        result = await cascade_delete_predecessors(tasks_api, "t1", predecessor_names)

        expected_calls = [call(f"/{name}") for name in predecessor_names] + [
            call("/t1")
        ]
        assert tasks_api.delete.await_args_list == expected_calls
        assert result.success
        assert result.successes == [*predecessor_names, "t1"]

    async def test_http_404_treated_as_success(self) -> None:
        """Treat HTTP 404 on any leg as success (idempotent intent)."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.delete.side_effect = [
            HTTPNotFoundException(),
            None,
        ]

        result = await cascade_delete_predecessors(tasks_api, "t1", ["t1-a"])

        assert result.success
        assert result.successes == ["t1-a", "t1"]
        assert result.failures == []

    async def test_non_http_exception_collected_as_failure(self) -> None:
        """Catch non-HTTP exceptions on a DELETE and collect them as a failure."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        connection_error = ConnectionError("upstream timeout")
        tasks_api.delete.side_effect = [connection_error, None]

        result = await cascade_delete_predecessors(tasks_api, "t1", ["t1-a"])

        assert not result.success
        assert result.failures[0].task_name == "t1-a"
        assert result.failures[0].exception is connection_error
