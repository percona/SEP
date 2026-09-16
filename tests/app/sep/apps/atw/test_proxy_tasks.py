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

"""Tests for resolving the ATW-owned PROXY task that carries ATW's recorder."""

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPNotFoundException,
    HTTPServiceUnavailableException,
)
from app.core.requests import RemoteAPI
from app.sep.apps.atw.proxy_tasks import (
    atw_proxy_task_name,
    ATW_PROXY_TASK_PREFIX,
    clear_atw_proxy_task_cache,
    ensure_atw_proxy_task,
)
from app.sep.apps.atw.recorder import RUN_RESULT_RECORDER
from app.tasks.execution.executors.nomad.steps import RUN_SCRIPT_OUTPUT_FILES_PATH
from app.tasks.models import ANY_OWNER, TaskBackendEnum

_ROOT_TASK_NAME = "exec-artifact"
_PROXY_NAME = f"{ATW_PROXY_TASK_PREFIX}{_ROOT_TASK_NAME}"
#: A non-default ``AnonymizeMask``; the type is an int bitmask, not a name list.
_CUSTOM_ANONYMIZE_MASK = 6


def _root_task(
    backend: TaskBackendEnum = TaskBackendEnum.NOMAD, **overrides: Any
) -> dict[str, Any]:
    """Build the upstream payload for the interpreter root ATW would wrap.

    Carries every behavioural field a real ``TaskResponse`` does, including the ones
    that default, because the proxy is validated against the root's values.
    """
    return {
        "name": _ROOT_TASK_NAME,
        "backend": backend.value,
        "owner": ANY_OWNER,
        "data": {"Constraints": [{"RTarget": "host1"}]},
        "run_result_recorder": None,
        "output_files_path": RUN_SCRIPT_OUTPUT_FILES_PATH,
        "anonymize_mask": None,
        "alert_on_fail": False,
        "alert_detail_builder": None,
    } | overrides


def _valid_proxy(**overrides: Any) -> dict[str, Any]:
    """Build the upstream payload of a proxy that passes every validation check."""
    return {
        "name": _PROXY_NAME,
        "backend": TaskBackendEnum.PROXY.value,
        "owner": ANY_OWNER,
        "data": {"task": _ROOT_TASK_NAME},
        "run_result_recorder": RUN_RESULT_RECORDER,
        "output_files_path": RUN_SCRIPT_OUTPUT_FILES_PATH,
        "anonymize_mask": None,
        "alert_on_fail": False,
        "alert_detail_builder": None,
    } | overrides


@pytest.fixture(autouse=True)
def _clear_proxy_cache() -> Iterator[None]:
    """Drop the process-wide memoization so each test resolves from scratch."""
    clear_atw_proxy_task_cache()
    yield
    clear_atw_proxy_task_cache()


@pytest.fixture
def tasks_api(mocker: MockerFixture) -> AsyncMock:
    """Replace the service-principal client this module builds with a mock.

    ``ensure_atw_proxy_task`` constructs its own client precisely so it works from a
    worker, so there is no dependency override to lean on here.
    """
    api = AsyncMock(spec=RemoteAPI)
    client = MagicMock()
    client.auth.return_value.__enter__.return_value = api
    mocker.patch(
        "app.sep.apps.atw.proxy_tasks.get_tasks_api",
        new=AsyncMock(return_value=client),
    )
    mocker.patch(
        "app.sep.apps.atw.proxy_tasks.require_internal_token", return_value="token"
    )
    return api


def _serve(tasks: dict[str, dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Build a ``get`` side effect answering from ``tasks``, else raising 404."""

    def _get(path: str, **_kwargs: Any) -> dict[str, Any]:
        name = path.lstrip("/")
        if name not in tasks:
            raise HTTPNotFoundException(f"no task {name}")
        return tasks[name]

    return _get


class TestProxyTaskName:
    """Check the naming that distinguishes ATW's proxy from the root it wraps."""

    def test_name_prefixes_the_root(self) -> None:
        """Ensure the proxy name is derived from the root, not configured separately."""
        assert atw_proxy_task_name(_ROOT_TASK_NAME) == _PROXY_NAME


class TestCreatesTheProxy:
    """Check the create path and the exact payload it posts."""

    @pytest.mark.asyncio
    async def test_creates_proxy_when_absent(self, tasks_api: AsyncMock) -> None:
        """Ensure a missing proxy is created and its name returned."""
        tasks_api.get.side_effect = _serve({_ROOT_TASK_NAME: _root_task()})
        tasks_api.post.return_value = _valid_proxy()

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) == _PROXY_NAME
        assert tasks_api.post.await_count == 1

    @pytest.mark.asyncio
    async def test_posted_payload_carries_the_recorder_and_parity_fields(
        self, tasks_api: AsyncMock
    ) -> None:
        """Ensure the created proxy carries every field the design depends on.

        ``owner`` and ``anonymize_mask`` keep anonymization byte-identical to today
        (the mask resolves off the proxy, not the root); ``output_files_path`` keeps
        result reading working; and the absence of a ``meta`` key is what stops the
        proxy overwriting each run's own execution meta.
        """
        tasks_api.get.side_effect = _serve({_ROOT_TASK_NAME: _root_task()})
        tasks_api.post.return_value = _valid_proxy()

        await ensure_atw_proxy_task(_ROOT_TASK_NAME)

        payload = tasks_api.post.await_args.kwargs["json"]
        assert payload["name"] == _PROXY_NAME
        assert payload["backend"] == TaskBackendEnum.PROXY
        assert payload["owner"] == ANY_OWNER
        assert payload["data"] == {"task": _ROOT_TASK_NAME}
        assert "meta" not in payload["data"]
        assert "payload" not in payload["data"]
        assert payload["run_result_recorder"] == RUN_RESULT_RECORDER
        assert payload["output_files_path"] == RUN_SCRIPT_OUTPUT_FILES_PATH
        assert payload["anonymize_mask"] is None

    @pytest.mark.asyncio
    async def test_custom_root_behaviour_is_copied_onto_the_proxy(
        self, tasks_api: AsyncMock
    ) -> None:
        """Ensure a non-default interpreter's behaviour survives being wrapped.

        ``SnippetInterpreterConfig.task`` is an overridable setting, so the root is
        not necessarily one of the seeded rows. Anonymization, result reading and
        dispatch-failure alerting all resolve off the *dispatched* task, so hardcoding
        the seeded defaults would silently apply the wrong policy to a custom one.
        """
        custom = _root_task(
            owner="pii-restricted",
            anonymize_mask=_CUSTOM_ANONYMIZE_MASK,
            output_files_path="custom/output",
            alert_on_fail=True,
            alert_detail_builder="app.sep.apps.atw.recorder:record_atw_run",
        )
        tasks_api.get.side_effect = _serve({_ROOT_TASK_NAME: custom})
        tasks_api.post.return_value = _valid_proxy()

        await ensure_atw_proxy_task(_ROOT_TASK_NAME)

        payload = tasks_api.post.await_args.kwargs["json"]
        assert payload["owner"] == "pii-restricted"
        assert payload["anonymize_mask"] == _CUSTOM_ANONYMIZE_MASK
        assert payload["output_files_path"] == "custom/output"
        assert payload["alert_on_fail"] is True
        assert payload["alert_detail_builder"] == (
            "app.sep.apps.atw.recorder:record_atw_run"
        )
        assert payload["run_result_recorder"] == RUN_RESULT_RECORDER

    @pytest.mark.asyncio
    async def test_proxy_left_from_a_different_root_configuration_is_refused(
        self, tasks_api: AsyncMock
    ) -> None:
        """Ensure a proxy carrying the old root's behaviour is not reused.

        Re-pointing an interpreter at a task with a different policy leaves the
        previous proxy in place under the same name; reusing it would keep applying
        the superseded owner and mask.
        """
        tasks_api.get.side_effect = _serve(
            {
                _ROOT_TASK_NAME: _root_task(owner="pii-restricted"),
                _PROXY_NAME: _valid_proxy(),
            }
        )

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) is None

    @pytest.mark.asyncio
    async def test_existing_valid_proxy_is_reused_without_a_second_post(
        self, tasks_api: AsyncMock
    ) -> None:
        """Ensure a proxy that already exists and validates is reused as-is."""
        tasks_api.get.side_effect = _serve(
            {_ROOT_TASK_NAME: _root_task(), _PROXY_NAME: _valid_proxy()}
        )

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) == _PROXY_NAME
        tasks_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolution_is_memoized_across_calls(
        self, tasks_api: AsyncMock
    ) -> None:
        """Ensure a validated resolution is cached, so dispatch is not per-run traffic."""
        tasks_api.get.side_effect = _serve(
            {_ROOT_TASK_NAME: _root_task(), _PROXY_NAME: _valid_proxy()}
        )

        await ensure_atw_proxy_task(_ROOT_TASK_NAME)
        first_call_count = tasks_api.get.await_count
        await ensure_atw_proxy_task(_ROOT_TASK_NAME)

        assert tasks_api.get.await_count == first_call_count


class TestRefusesToWrap:
    """Check every degradation, each of which dispatches under the root unchanged."""

    @pytest.mark.asyncio
    async def test_proxy_backed_root_is_not_wrapped(self, tasks_api: AsyncMock) -> None:
        """Ensure an already-PROXY interpreter is left alone rather than double-wrapped.

        ``get_root_task`` resolves exactly one hop, so a proxy-of-a-proxy reaches
        ``get_executor`` still PROXY and breaks every dispatch under it.
        """
        tasks_api.get.side_effect = _serve(
            {_ROOT_TASK_NAME: _root_task(backend=TaskBackendEnum.PROXY)}
        )

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) is None
        tasks_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_absent_root_is_not_wrapped(self, tasks_api: AsyncMock) -> None:
        """Ensure a root that does not exist upstream is not given a proxy."""
        tasks_api.get.side_effect = _serve({})

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) is None
        tasks_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"run_result_recorder": "other.module:hook"}, id="recorder"),
            pytest.param({"data": {"task": "some-other-root"}}, id="root"),
            pytest.param({"backend": TaskBackendEnum.NOMAD.value}, id="backend"),
            pytest.param({"owner": "someone-else"}, id="owner"),
            pytest.param({"output_files_path": None}, id="output_files_path"),
            pytest.param({"anonymize_mask": {"entities": []}}, id="anonymize_mask"),
            pytest.param(
                {"data": {"task": _ROOT_TASK_NAME, "meta": {"target": "elsewhere"}}},
                id="meta",
            ),
            pytest.param(
                {"data": {"task": _ROOT_TASK_NAME, "payload": "file:///etc/passwd"}},
                id="payload",
            ),
        ],
    )
    async def test_incompatible_existing_task_refuses_to_wrap(
        self, tasks_api: AsyncMock, overrides: dict[str, Any]
    ) -> None:
        """Ensure a name collision is not taken as proof the right proxy exists.

        ``update_task`` can reshape any task after creation, and each of these fields
        changes behaviour silently, so every one is validated.
        """
        tasks_api.get.side_effect = _serve(
            {
                _ROOT_TASK_NAME: _root_task(),
                _PROXY_NAME: _valid_proxy(**overrides),
            }
        )

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) is None

    @pytest.mark.asyncio
    async def test_degraded_resolution_is_not_memoized(
        self, tasks_api: AsyncMock
    ) -> None:
        """Ensure a poisoned row is re-examined next dispatch, not pinned for the TTL."""
        tasks_api.get.side_effect = _serve(
            {
                _ROOT_TASK_NAME: _root_task(),
                _PROXY_NAME: _valid_proxy(run_result_recorder=None),
            }
        )
        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) is None

        tasks_api.get.side_effect = _serve(
            {_ROOT_TASK_NAME: _root_task(), _PROXY_NAME: _valid_proxy()}
        )

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) == _PROXY_NAME


class TestTransientFailuresSurface:
    """Check that an unreachable upstream is raised, not degraded to an unwrapped run."""

    @pytest.mark.asyncio
    async def test_transient_upstream_error_propagates(
        self, tasks_api: AsyncMock
    ) -> None:
        """Ensure a 503 while resolving the proxy surfaces rather than dispatching.

        Every *validation* outcome degrades to ``None``, so the absence of a
        degradation here is the contract: a dispatch failing because the Tasks API
        is unreachable would fail at dispatch anyway, and silently running it
        unwrapped would lose the recorder with nothing said.
        """
        tasks_api.get.side_effect = HTTPServiceUnavailableException("try later")

        with pytest.raises(HTTPServiceUnavailableException):
            await ensure_atw_proxy_task(_ROOT_TASK_NAME)

    @pytest.mark.asyncio
    async def test_a_raised_resolution_is_not_memoized(
        self, tasks_api: AsyncMock
    ) -> None:
        """Ensure a transient failure does not pin dispatch broken for the cache TTL."""
        tasks_api.get.side_effect = HTTPServiceUnavailableException("try later")
        with pytest.raises(HTTPServiceUnavailableException):
            await ensure_atw_proxy_task(_ROOT_TASK_NAME)

        tasks_api.get.side_effect = _serve(
            {_ROOT_TASK_NAME: _root_task(), _PROXY_NAME: _valid_proxy()}
        )

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) == _PROXY_NAME


class TestCreateRace:
    """Check that a concurrent creator is resolved rather than treated as an error."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "raised",
        [
            pytest.param(HTTPConflictException("exists"), id="409"),
            pytest.param(HTTPBadRequestException("integrity"), id="400"),
        ],
    )
    async def test_race_refetches_and_validates_the_winner(
        self, tasks_api: AsyncMock, raised: Exception
    ) -> None:
        """Ensure both race statuses re-fetch the winner and proceed.

        The duplicate precheck answers 409 only when it *sees* the row, so a
        concurrent insert trips the commit branch and surfaces as a 400 instead. A
        409-only handler would turn a live race into a failed dispatch.
        """
        served = {_ROOT_TASK_NAME: _root_task()}
        tasks_api.get.side_effect = _serve(served)

        def _post(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            served[_PROXY_NAME] = _valid_proxy()
            raise raised

        tasks_api.post.side_effect = _post

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) == _PROXY_NAME

    @pytest.mark.asyncio
    async def test_race_winner_is_still_validated(self, tasks_api: AsyncMock) -> None:
        """Ensure the row a race produced is validated, not trusted for existing."""
        served = {_ROOT_TASK_NAME: _root_task()}
        tasks_api.get.side_effect = _serve(served)

        def _post(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            served[_PROXY_NAME] = _valid_proxy(backend=TaskBackendEnum.NOMAD.value)
            raise HTTPConflictException("exists")

        tasks_api.post.side_effect = _post

        assert await ensure_atw_proxy_task(_ROOT_TASK_NAME) is None
