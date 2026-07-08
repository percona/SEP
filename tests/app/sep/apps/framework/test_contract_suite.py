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

import functools
from typing import Annotated, Any
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Body, status
from fastapi.routing import APIRoute

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.pagination.deps import make_pagination_dep
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import ConnectivityWarning
from app.sep.apps.framework.apps import AppCapabilities, TaskExecutionApp
from app.sep.apps.framework.task_status import batch_get_latest_statuses
from app.sep.deps import IsApiAuthenticated, TaskAPI
from app.tasks.models import LATEST_HISTORY_STATUS_NAMES_MAX, TaskHistoryStatusEnum
from tests.app.sep.apps.framework.contract_suite import (
    app_base_url,
    build_contract_client,
    build_valid_create_body,
    DerivedRouterContractTests,
)
from tests.app.sep.apps.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    SEEDED_TASK_NAME,
    synth_app,
    synth_app_kwargs,
    synth_create_response_builder,
    SYNTH_CREATED_BY_NAME,
    synth_delete_handler,
    synth_detail_builder,
    SYNTH_OWNER,
    synth_response_builder,
    synth_update_guard,
    synth_update_handler,
    SynthCreateResponse,
    SynthDetailResponse,
    SynthExecuteResponse,
    SynthForm,
    SynthResponse,
)


class TestSyntheticContract(DerivedRouterContractTests):
    """Cover every contract case against the canonical correct definition."""

    app_def = synth_app()


class TestSyntheticNewOwnerContract(DerivedRouterContractTests):
    """Cover the full contract for a brand-new owner string no core module knows.

    Proves AC6's seam: a plugin declares its own owner string and service type and
    round-trips create/list/get with zero edits under ``app/tasks`` or ``app/sep``.
    ``create_extra_deps`` is dropped because the kit's conflict guard hardcodes the
    canonical synth owner; the guard is orthogonal to the owner-string seam and is
    covered by :class:`TestSyntheticContract`.
    """

    app_def = synth_app(
        owner="CONTRACT_NEW_OWNER",
        service_type=ServiceTypeEnum.POSTGRESQL,
        create_extra_deps=(),
    )


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


class TestSyntheticDerivedCrudContract(DerivedRouterContractTests):
    """Cover the handler-less derived PUT/DELETE and the ``update_guard``."""

    app_def = synth_app(
        capabilities=AppCapabilities(update=True, delete=True),
        update_guard=(synth_update_guard,),
        delete_guard=(synth_update_guard,),
    )


class TestSyntheticCreateResponseBuilderContract(DerivedRouterContractTests):
    """Cover the create cases against an explicit stable ``create_response_builder``."""

    app_def = synth_app(
        connectivity_check=True,
        create_response_builder=synth_create_response_builder,
    )


class TestSyntheticFormEncodedContract(DerivedRouterContractTests):
    """Cover the create cases against a Form-encoded (escape-hatch) definition."""

    app_def = synth_app(create_form_encoded=True)


class TestSyntheticDetailBuilderContract(DerivedRouterContractTests):
    """Cover the detail/create cases against a richer-detail definition."""

    app_def = synth_app(
        detail_response_builder=synth_detail_builder,
        detail_response_model=SynthDetailResponse,
    )


class TestSyntheticPartialBuilderContract(DerivedRouterContractTests):
    """Cover every contract case against a ``functools.partial``-wrapped builder."""

    app_def = synth_app(response_builder=functools.partial(synth_response_builder))


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


def test_create_response_builder_pins_stable_component(
    regular_user: CasdoorUser, mocker: Any
) -> None:
    """Assert an explicit ``create_response_builder`` pins the stable create model.

    The create route serves the hand-authored ``SynthCreateResponse`` (not the
    framework's auto-derived create model), and the create response combines the
    injected ``service_type`` / resolved username extras with the probe warning.
    """
    app_def = synth_app(
        connectivity_check=True,
        create_response_builder=synth_create_response_builder,
    )
    create_route = next(
        route
        for route in app_def.api_router.routes
        if isinstance(route, APIRoute) and route.path == "/" and "POST" in route.methods
    )
    assert create_route.response_model is SynthCreateResponse

    tasks_api = MockTaskAPI()
    tasks_api.seed_task(SEEDED_TASK_NAME, owner=app_def.owner)
    client = build_contract_client(
        app_def,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )
    mocker.patch(
        "app.sep.apps.framework.connectivity.record_connectivity_warning",
        new_callable=AsyncMock,
        return_value=ConnectivityWarning(
            target="db-host", service_type="mysql", message="unreachable"
        ),
    )
    body = build_valid_create_body(app_def)

    response = client.post(f"{app_base_url(app_def)}/", json=body)

    assert response.status_code == status.HTTP_201_CREATED
    payload = response.json()
    assert payload["service_type"] == ServiceTypeEnum.MYSQL.value
    assert payload["created_by"] == SYNTH_CREATED_BY_NAME
    assert payload["connectivity_warning"] is not None
