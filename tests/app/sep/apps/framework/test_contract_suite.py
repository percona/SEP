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
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Body, status
from fastapi.routing import APIRoute
from pydantic import BaseModel
from pytest_mock import MockerFixture

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.pagination.deps import make_pagination_dep
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.archives.constants import SwapDropEnum
from app.sep.apps.framework import ConnectivityWarning
from app.sep.apps.framework.apps import AppCapabilities, TaskExecutionApp, UNGUARDED
from app.sep.apps.framework.task_status import batch_get_latest_statuses
from app.sep.deps import IsApiAuthenticated, TaskAPI
from app.tasks.models import LATEST_HISTORY_STATUS_NAMES_MAX, TaskHistoryStatusEnum
from tests.app.sep.apps.framework.contract_suite import (
    _select_branch,
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
    """Cover the handler-less derived PUT/DELETE with an explicit guard override."""

    app_def = synth_app(
        capabilities=AppCapabilities(update=True, delete=True),
        update_guard=(synth_update_guard,),
        delete_guard=(synth_update_guard,),
    )


class TestSyntheticDefaultGuardedCrudContract(DerivedRouterContractTests):
    """Cover the framework default guards on a derived PUT/DELETE with no override.

    Leaving ``update_guard`` / ``delete_guard`` unset (``()``) makes the framework
    ride its default protected-task + running-conflict guards on the derived
    routes, so the inherited running-conflict and protected-task 409 cases run
    without a per-app guard being declared.
    """

    app_def = synth_app(
        capabilities=AppCapabilities(update=True, delete=True),
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


def test_unguarded_opt_out_leaves_derived_routes_unguarded(
    regular_user: CasdoorUser,
) -> None:
    """Assert ``UNGUARDED`` drops the framework default guards from PUT and DELETE.

    A task seeded both RUNNING and protected would trip either default guard; with
    both knobs opted out, the derived PUT and DELETE succeed against it.
    """
    app_def = synth_app(
        capabilities=AppCapabilities(update=True, delete=True),
        update_guard=UNGUARDED,
        delete_guard=UNGUARDED,
    )
    tasks_api = MockTaskAPI()
    tasks_api.seed_task(
        SEEDED_TASK_NAME,
        owner=app_def.owner,
        statuses=(TaskHistoryStatusEnum.RUNNING,),
        protected=True,
    )
    client = build_contract_client(
        app_def,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )
    base = app_base_url(app_def)
    body = build_valid_create_body(app_def, task_name=SEEDED_TASK_NAME)

    put = client.put(f"{base}/{SEEDED_TASK_NAME}", json=body)
    delete = client.delete(f"{base}/{SEEDED_TASK_NAME}")

    assert put.status_code == status.HTTP_200_OK
    assert delete.status_code == status.HTTP_204_NO_CONTENT


def test_default_guard_rides_only_the_derived_verb(regular_user: CasdoorUser) -> None:
    """Assert the default guard attaches to the derived verb but not its absent sibling.

    An update-only app guards its PUT (409 on a running task) yet derives no DELETE
    route (the ``delete`` path exists for GET only, so DELETE is 405).
    """
    app_def = synth_app(capabilities=AppCapabilities(update=True, delete=False))
    tasks_api = MockTaskAPI()
    tasks_api.seed_running(SEEDED_TASK_NAME, owner=app_def.owner)
    client = build_contract_client(
        app_def,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )
    base = app_base_url(app_def)
    body = build_valid_create_body(app_def, task_name=SEEDED_TASK_NAME)

    put = client.put(f"{base}/{SEEDED_TASK_NAME}", json=body)
    delete = client.delete(f"{base}/{SEEDED_TASK_NAME}")

    assert put.status_code == status.HTTP_409_CONFLICT
    assert delete.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_default_guards_share_one_task_fetch(
    regular_user: CasdoorUser, mocker: MockerFixture
) -> None:
    """Assert the two default guards and the handler share one cached task fetch.

    All three depend on the same ``_task_getter`` callable, so FastAPI's
    ``use_cache`` collapses the get-by-name to a single upstream call per request.
    """
    app_def = synth_app(capabilities=AppCapabilities(update=True, delete=True))
    tasks_api = MockTaskAPI()
    tasks_api.seed_task(SEEDED_TASK_NAME, owner=app_def.owner)
    spy = mocker.spy(tasks_api, "get")
    client = build_contract_client(
        app_def,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )
    base = app_base_url(app_def)
    body = build_valid_create_body(app_def, task_name=SEEDED_TASK_NAME)

    response = client.put(f"{base}/{SEEDED_TASK_NAME}", json=body)

    assert response.status_code == status.HTTP_200_OK
    detail_fetches = [
        call for call in spy.call_args_list if call.args[0] == f"/{SEEDED_TASK_NAME}"
    ]
    assert len(detail_fetches) == 1


@pytest.mark.asyncio
async def test_mock_task_api_latest_per_name() -> None:
    """Assert ``/history/latest`` returns the projection, null if absent."""
    api = MockTaskAPI()
    api.seed_task(
        "t-resolved",
        owner=SYNTH_OWNER,
        statuses=[TaskHistoryStatusEnum.SUCCESS, TaskHistoryStatusEnum.FAILED],
    )
    api.seed_task("t-no-history", owner=SYNTH_OWNER, statuses=[])

    result = await api.post(
        "/history/latest",
        json={"names": ["t-resolved", "t-no-history", "t-unknown"]},
    )

    assert result["t-resolved"]["status"] == TaskHistoryStatusEnum.SUCCESS.value
    assert result["t-no-history"] is None
    assert result["t-unknown"] is None


@pytest.mark.asyncio
async def test_batch_get_latest_statuses_through_mock() -> None:
    """Assert the helper resolves seeded statuses and degrades unknowns to None."""
    api = MockTaskAPI()
    api.seed_task(
        "t-running", owner=SYNTH_OWNER, statuses=[TaskHistoryStatusEnum.RUNNING]
    )

    result = await batch_get_latest_statuses(api, ["t-running", "t-unknown"])

    assert result["t-running"].status == TaskHistoryStatusEnum.RUNNING
    assert result["t-unknown"] is None


@pytest.mark.asyncio
async def test_batch_get_latest_statuses_chunks_over_the_limit() -> None:
    """Assert the mock answers every name across the helper's request chunking."""
    api = MockTaskAPI()
    names = [f"t-{index}" for index in range(LATEST_HISTORY_STATUS_NAMES_MAX + 1)]
    for name in names:
        api.seed_task(name, owner=SYNTH_OWNER, statuses=[TaskHistoryStatusEnum.SUCCESS])

    result = await batch_get_latest_statuses(api, names)

    assert len(result) == len(names)
    assert {value.status for value in result.values()} == {
        TaskHistoryStatusEnum.SUCCESS
    }


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


def test_build_valid_create_body_wraps_multi_value_refs() -> None:
    """Wrap seeded inventory ids in lists when a ref marker declares ``multiple=True``."""
    from app.sep.apps.checksums.app import app as checksums_app
    from app.sep.apps.checksums.models import ChecksumsForm
    from tests.app.factories import (
        MOCK_CREATED_SCHEMA_ID,
        MOCK_CREATED_SERVICE_ID,
        MOCK_CREATED_TABLE_ID,
    )

    body = build_valid_create_body(checksums_app)

    assert body is not None
    assert body["service_id"] == MOCK_CREATED_SERVICE_ID
    assert body["databases"] == [MOCK_CREATED_SCHEMA_ID]
    assert body["tables"] == [MOCK_CREATED_TABLE_ID]
    ChecksumsForm.model_validate(body)


class _FirstArm(BaseModel):
    """The first-declared model arm a union branch pick must return."""

    value: int


class _SecondArm(BaseModel):
    """A second model arm, present so the union is not a degenerate single type."""

    other: str


class _SelectBranchModel(BaseModel):
    """Carry each shape ``_select_branch`` must classify.

    ``one_of`` is a genuine model union (recurse into its first arm); ``optional_one_of``
    adds a ``None`` arm (recurse, dropping ``None``); ``items`` is a container that also
    yields a model from ``get_args`` but must keep its list shape; ``mixed`` unions a
    model with a scalar (a collapsed reference, not a model union); ``scalar`` and
    ``scalar_union`` are non-model shapes the generic factory handles unaided.
    """

    one_of: _FirstArm | _SecondArm
    optional_one_of: _FirstArm | None
    items: list[_FirstArm]
    mixed: _FirstArm | int
    scalar: int
    scalar_union: int | str


class TestSelectBranch:
    """Pin which annotations ``_select_branch`` treats as a model union to recurse into."""

    def test_selects_first_model_union_arm(self) -> None:
        """Return the first model arm for a genuine union, dropping any ``None`` arm."""
        fields = _SelectBranchModel.model_fields
        assert _select_branch(fields["one_of"]) is _FirstArm
        assert _select_branch(fields["optional_one_of"]) is _FirstArm

    def test_ignores_container_and_non_model_shapes(self) -> None:
        """Return ``None`` for a container, scalar, or model/scalar mix — never collapsing shape.

        A ``list[Model]`` yields a ``BaseModel`` from ``get_args`` too, so a pick keyed
        only on the args — not the union origin — would replace the list with a single
        instance and break factory construction. A ``Model | int`` mix is a collapsed
        reference, not a one-of group, so it is left to the generic factory.
        """
        fields = _SelectBranchModel.model_fields
        assert _select_branch(fields["items"]) is None
        assert _select_branch(fields["mixed"]) is None
        assert _select_branch(fields["scalar"]) is None
        assert _select_branch(fields["scalar_union"]) is None


# Pins the archives one-of create model's validator-/rule-constrained scalars so the
# generic generator can build it: ``swap_drop`` (``__form_rules__`` accepts only
# ``PURGE_ONLY``, enforced at model validation), ``where`` (``Requires`` rule), and a
# falsy ``delete_data`` so ``_check_destination_presence`` accepts the destination
# branch the generator populates. Leaves ``source`` / ``destination`` / ``host``
# unpinned so the recursion under test is observable.
_ARCHIVES_BUILD_PINS = {
    "swap_drop": SwapDropEnum.PURGE_ONLY,
    "where": "id < 100",
    "delete_data": None,
}


def test_build_valid_create_body_recurses_into_oneof_branches() -> None:
    """Resolve references nested inside discriminated-union branches to seeded ids.

    Archives is the first one-of create model: its ``source`` / ``destination`` /
    ``host`` groups carry the inventory references, so the generator must recurse
    into the selected branch and pin each nested ref to its seeded ``MOCK_*_ID``.
    """
    from app.sep.apps.archives.app import app as archives_app
    from tests.app.factories import (
        MOCK_CREATED_SCHEMA_ID,
        MOCK_CREATED_SERVICE_ID,
        MOCK_CREATED_TABLE_ID,
    )

    body = build_valid_create_body(
        archives_app, create_body_overrides=_ARCHIVES_BUILD_PINS
    )

    assert body is not None
    assert body["service_id"] == MOCK_CREATED_SERVICE_ID
    assert body["source"] == {
        "mode": "table",
        "source_db": MOCK_CREATED_SCHEMA_ID,
        "source_table": MOCK_CREATED_TABLE_ID,
    }
    assert body["destination"]["dest_table"] == MOCK_CREATED_TABLE_ID
    assert body["destination"]["dest_db"] == MOCK_CREATED_SCHEMA_ID
    assert body["host"] == {"mode": "service", "dest_service": MOCK_CREATED_SERVICE_ID}


_EXPECTED_ARCHIVES_MODES = {
    "source": "table",
    "destination": "table",
    "host": "service",
}


def archives_branch_modes_match() -> bool:
    """Report whether the generator picks the first-declared arm of every archives union.

    Builds a valid archives create body and compares the ``mode`` chosen for each of
    the ``source`` / ``destination`` / ``host`` one-of groups against the first-declared
    arms. Called from a subprocess under a fixed ``PYTHONHASHSEED`` so the branch pick
    can be swept across hash seeds without polluting the assertion with the framework's
    stdout log noise.

    :return: ``True`` when every group resolves to its expected first-declared arm.
    """
    from app.sep.apps.archives.app import app as archives_app

    body = build_valid_create_body(
        archives_app, create_body_overrides=_ARCHIVES_BUILD_PINS
    )
    assert body is not None
    modes = {key: body[key]["mode"] for key in _EXPECTED_ARCHIVES_MODES}
    return modes == _EXPECTED_ARCHIVES_MODES


class TestBranchSelectionDeterminism:
    """Sweep the union-branch pick across hash seeds in isolated interpreters.

    The branch choice must follow declaration order — never set/hash ordering, the
    flake class the derived one-of body schema was hardened against. A same-interpreter
    double-call cannot see that regression: a set-backed pick returns the same arm both
    times within one process. Each seed therefore runs in its own interpreter with
    ``PYTHONHASHSEED`` fixed at start, and every seed must select the first-declared
    arm — never the ``None`` arm of the optional ``destination`` / ``host`` unions. The
    probe reports via exit code (not stdout) because the framework logs to stdout at
    import.
    """

    _REPO_ROOT = Path(__file__).resolve().parents[5]
    _SUBPROCESS = (
        "import sys;"
        "from tests.app.sep.apps.framework.test_contract_suite import"
        " archives_branch_modes_match;"
        "sys.exit(0 if archives_branch_modes_match() else 1)"
    )

    @pytest.mark.parametrize("seed", range(3))
    def test_first_declared_branch_selected_under_seed(self, seed: int) -> None:
        """Assert every one-of group resolves to its first-declared arm under ``seed``."""
        result = subprocess.run(
            [sys.executable, "-c", self._SUBPROCESS],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            cwd=self._REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"seed={seed} selected a non-first-declared union branch\n{result.stderr}"
        )


def test_create_body_overrides_win_over_generated_values() -> None:
    """Apply ``create_body_overrides`` last, so a pin beats a generated or ref value.

    The override must win even over an inventory-reference field the generator would
    otherwise pin to its seeded ``MOCK_*_ID`` (``service_id`` here).
    """
    from app.sep.apps.archives.app import app as archives_app

    pinned_service_id = 4242
    body = build_valid_create_body(
        archives_app,
        create_body_overrides={**_ARCHIVES_BUILD_PINS, "service_id": pinned_service_id},
    )

    assert body is not None
    assert body["service_id"] == pinned_service_id


def test_create_response_builder_pins_stable_component(
    regular_user: CasdoorUser, mocker: MockerFixture
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
