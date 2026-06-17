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

"""Prove the framework test kit has teeth.

The green classes bind correct synthetic definitions (full, read-only,
paginated, connectivity, full-CRUD) and pass every inherited contract case. The
red tests drive the assertion core against deliberately broken definitions — a
create route returning 200 and an execute route missing its conflict guard — and
assert the suite raises ``AssertionError``, so a real contract regression cannot
pass silently. The kit unit tests pin :class:`MockTaskAPI`'s batch-status
semantics against the ``batch_get_latest_statuses`` contract every migration
trusts.
"""

from typing import Annotated

import pytest
from fastapi import APIRouter, Body, status

from app.core.pagination.deps import make_pagination_dep
from app.models import CasdoorUser
from app.sep.deps import IsApiAuthenticated, TaskAPI
from app.sep.plugins.framework.apps import AppCapabilities, TaskExecutionApp
from app.sep.plugins.framework.task_status import batch_get_latest_statuses
from app.tasks.models import LATEST_HISTORY_STATUS_NAMES_MAX, TaskHistoryStatusEnum
from tests.app.sep.plugins.framework.contract_suite import (
    app_base_url,
    build_contract_client,
    DerivedRouterContractTests,
)
from tests.app.sep.plugins.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    SEEDED_TASK_NAME,
    synth_app,
    synth_app_kwargs,
    synth_delete_handler,
    SYNTH_OWNER,
    synth_update_handler,
    SynthExecuteResponse,
    SynthForm,
    SynthResponse,
)


class TestSyntheticContract(DerivedRouterContractTests):
    """Cover every contract case against the canonical correct definition."""

    app_def = synth_app()


class TestSyntheticReadOnlyContract(DerivedRouterContractTests):
    """Cover the absence cases against a create- and execute-disabled definition."""

    app_def = synth_app(
        capabilities=AppCapabilities(create=False, execute=False),
        create_extra_deps=(),
    )


class TestSyntheticPaginatedContract(DerivedRouterContractTests):
    """Cover the paginated-list case against a definition with pagination on."""

    app_def = synth_app(pagination=make_pagination_dep(max_limit=50))


class TestSyntheticConnectivityContract(DerivedRouterContractTests):
    """Cover the connectivity-warning case against a connectivity-checked definition."""

    app_def = synth_app(connectivity_check=True)


class TestSyntheticFullCrudContract(DerivedRouterContractTests):
    """Cover the update-present and delete cases against a full-CRUD definition."""

    app_def = synth_app(
        capabilities=AppCapabilities(update=True, delete=True),
        update_handler=synth_update_handler,
        delete_handler=synth_delete_handler,
    )


class TestSyntheticFormEncodedContract(DerivedRouterContractTests):
    """Cover the create cases against a Form-encoded (escape-hatch) definition."""

    app_def = synth_app(create_form_encoded=True)


class _WrongStatusCreateApp(TaskExecutionApp):
    """Build a router whose ``POST /`` returns 200 instead of 201."""

    def build_router(self) -> APIRouter:
        router = APIRouter()
        form_param = Annotated[self.create_model, Body()]

        async def _create(form: form_param) -> SynthResponse:
            return SynthResponse(name=form.task_name)

        router.add_api_route(
            "/",
            _create,
            methods=["POST"],
            status_code=status.HTTP_200_OK,
            response_model=SynthResponse,
            dependencies=[IsApiAuthenticated],
        )
        return router


class _NoGuardExecuteApp(TaskExecutionApp):
    """Build an execute route that omits the ``HasNoConflictedRunningTasks`` guard."""

    def build_router(self) -> APIRouter:
        router = APIRouter()
        task_dep = self.task_dep
        write_model = self.execute_write_model

        async def _execute(
            task: task_dep, body: write_model, tasks_api: TaskAPI
        ) -> SynthExecuteResponse:
            await tasks_api.post(
                f"/execute/{task.name}", json=body.model_dump(exclude_none=True)
            )
            return SynthExecuteResponse(task_name=task.name, task_id=1)

        router.add_api_route(
            "/{task_name}/execute",
            _execute,
            methods=["POST"],
            status_code=status.HTTP_201_CREATED,
            response_model=SynthExecuteResponse,
            dependencies=[IsApiAuthenticated],
        )
        return router


def _bind_suite(app_def: TaskExecutionApp) -> DerivedRouterContractTests:
    suite = DerivedRouterContractTests()
    suite.app_def = app_def
    return suite


def test_suite_detects_wrong_create_status(regular_user: CasdoorUser) -> None:
    """Assert the create case fails when ``POST /`` returns the wrong status."""
    broken = _WrongStatusCreateApp(**synth_app_kwargs())
    tasks_api = MockTaskAPI()
    tasks_api.seed_task(SEEDED_TASK_NAME, owner=broken.owner)
    client = build_contract_client(
        broken,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )

    with pytest.raises(AssertionError):
        _bind_suite(broken).test_create_201(client, tasks_api)


def test_suite_detects_missing_conflict_guard(regular_user: CasdoorUser) -> None:
    """Assert the conflict case fails when the execute route omits the guard."""
    broken = _NoGuardExecuteApp(**synth_app_kwargs())
    tasks_api = MockTaskAPI()
    tasks_api.seed_task(SEEDED_TASK_NAME, owner=broken.owner)
    client = build_contract_client(broken, user=regular_user, tasks_api=tasks_api)

    with pytest.raises(AssertionError):
        _bind_suite(broken).test_execute_conflict_409(client, tasks_api)


@pytest.mark.asyncio
async def test_mock_task_api_latest_status_per_name() -> None:
    """Assert ``/history/latest`` returns the latest non-null status, null if absent."""
    api = MockTaskAPI()
    api.seed_task(
        "t-resolved",
        owner=SYNTH_OWNER,
        statuses=[TaskHistoryStatusEnum.SUCCESS, TaskHistoryStatusEnum.FAILED],
    )
    api.seed_task("t-no-history", owner=SYNTH_OWNER, statuses=[])

    result = await api.post(
        "/history/latest", json={"names": ["t-resolved", "t-no-history", "t-unknown"]}
    )

    assert result == {
        "t-resolved": TaskHistoryStatusEnum.SUCCESS.value,
        "t-no-history": None,
        "t-unknown": None,
    }


@pytest.mark.asyncio
async def test_batch_get_latest_statuses_through_mock() -> None:
    """Assert the helper resolves seeded statuses and degrades unknowns to None."""
    api = MockTaskAPI()
    api.seed_task(
        "t-running", owner=SYNTH_OWNER, statuses=[TaskHistoryStatusEnum.RUNNING]
    )

    result = await batch_get_latest_statuses(api, ["t-running", "t-unknown"])

    assert result == {"t-running": TaskHistoryStatusEnum.RUNNING, "t-unknown": None}


@pytest.mark.asyncio
async def test_batch_get_latest_statuses_chunks_over_the_limit() -> None:
    """Assert the mock answers every name across the helper's request chunking."""
    api = MockTaskAPI()
    names = [f"t-{index}" for index in range(LATEST_HISTORY_STATUS_NAMES_MAX + 1)]
    for name in names:
        api.seed_task(name, owner=SYNTH_OWNER, statuses=[TaskHistoryStatusEnum.SUCCESS])

    result = await batch_get_latest_statuses(api, names)

    assert len(result) == len(names)
    assert set(result.values()) == {TaskHistoryStatusEnum.SUCCESS}


def test_synth_ui_default_distinct_from_model_default(
    regular_user: CasdoorUser,
) -> None:
    """Assert ``Ui(default=...)`` sets the schema default apart from the model default."""
    app_def = synth_app()
    client = build_contract_client(
        app_def,
        user=regular_user,
        tasks_api=MockTaskAPI(),
        inventory_api=MockInventoryAPI(),
    )

    response = client.get(f"{app_base_url(app_def)}/schema")

    assert response.status_code == status.HTTP_200_OK
    mode_field = next(
        field
        for section in response.json()["forms"]
        for field in section["fields"]
        if field["name"] == "mode"
    )
    assert mode_field["default"] == "display-default"
    assert SynthForm.model_fields["mode"].default == "body-default"
