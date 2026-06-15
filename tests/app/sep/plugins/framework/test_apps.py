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

"""Cover ``TaskExecutionApp``: route composition, derived surfaces, and binding.

Every derived surface is exercised through a real ``TestClient`` against a
synthetic app definition, so body parsing and dependency injection resolve
end-to-end. The create test issues a real form POST and never overrides the
``create_payload`` dependency — only the inventory client — so the three-phase
body resolution it exists to cover is genuinely executed.
"""

from typing import Annotated, get_args
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.pagination.deps import make_pagination_dep
from app.core.requests.remote_api import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.models import CasdoorUser
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.deps import (
    get_api_authenticated_user,
    get_inventory_api,
    get_tasks_api,
    InventoryAPI,
    IsApiAuthenticated,
)
from app.sep.plugins.framework import ConnectivityWarning
from app.sep.plugins.framework.apps import AppCapabilities, TaskExecutionApp, Views
from app.sep.plugins.framework.form_dsl import (
    AppFormModel,
    FormLayout,
    SectionLayout,
    ServiceRef,
    Ui,
)
from app.sep.plugins.framework.payload import ResolvedEntities, RunCommandSpec
from app.sep.plugins.framework.schema import (
    BoolField,
    Column,
    FormSection,
    ListView,
    PluginSchema,
)
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskOwner, TaskWrite
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedServiceFactory,
    TaskFactory,
)

_OWNER = TaskOwner.ARCHIVER
_PREFIX = "/synthetic-app"
_BASE = f"/api/plugins{_PREFIX}"
_SERVICE_HOST = "db-host"
_SERVICE_PORT = 3306

_LAYOUT = FormLayout(sections=(SectionLayout(key="main", title="Main"),))
_LIST_VIEW = ListView(columns=[Column(key="name", label="Name")])


class _SynthForm(AppFormModel):
    """Represent a synthetic create form with one service ref and a manual flag."""

    task_name: Annotated[str, Ui(label="Name", section="main")]
    service_id: Annotated[
        int,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,)),
        Ui(label="Service", section="main"),
    ]
    alert_on_fail: Annotated[bool, Ui(label="Alert", section="main")] = False


class _SynthResponse(BaseModel):
    """Represent the list/detail response built from the task dump plus status."""

    name: str
    status: TaskHistoryStatusEnum | None = None


class _SynthExecuteWrite(BaseModel):
    """Represent the execute request body for the synthetic app."""

    note: str | None = None


class _SynthExecuteResponse(BaseModel):
    """Represent the execute response carrying the dispatched task name and id."""

    task_name: str
    task_id: int


class _NoTaskNameForm(AppFormModel):
    """Represent a synthetic create form that omits the mandatory ``task_name`` field."""

    label: Annotated[str, Ui(label="Label", section="main")] = ""


class _SynthCapabilities(BaseModel):
    """Represent the runtime capability flags returned by ``GET /capabilities``."""

    manual_sync_enabled: bool = True


async def _delete_handler(task_name: str) -> None:
    """Stand in as a delete handler so the delete route can be registered."""


async def _passthrough_payload_builder(inventory_api: InventoryAPI) -> TaskWrite:
    """Stand in as the create payload for a transitional ``schema=`` app."""
    return TaskWrite(name="passthrough", owner=_OWNER, data={})


def _capabilities_provider() -> _SynthCapabilities:
    """Return the synthetic runtime capability flags."""
    return _SynthCapabilities()


def _spec_builder(form: AppFormModel, resolved: ResolvedEntities) -> RunCommandSpec:
    """Build a synthetic run-command spec from the form and resolved service."""
    service = resolved.service
    return RunCommandSpec(
        command="synth-cmd",
        args=f"--task={form.task_name}",
        extra_meta={
            "_service_host": service.node.address,
            "_service_port": service.port,
        },
    )


def _extra_router() -> APIRouter:
    """Return an extra router exposing a fixed ``GET /ping`` route."""
    router = APIRouter()

    @router.get("/ping", dependencies=[IsApiAuthenticated])
    async def _ping() -> dict[str, bool]:
        return {"pong": True}

    return router


_PASSTHROUGH_SCHEMA = PluginSchema(
    name="synthetic-app",
    display_name="Synthetic App",
    forms=[FormSection(title="Options", fields=[BoolField(name="flag", label="Flag")])],
    list_view=_LIST_VIEW,
)


def _synth_app(**overrides: object) -> TaskExecutionApp:
    """Build a ``TaskExecutionApp`` with sane synthetic defaults."""
    kwargs = {
        "name": "synthetic-app",
        "uri_path": _PREFIX,
        "owner": _OWNER,
        "create_model": _SynthForm,
        "response_model": _SynthResponse,
        "views": Views(layout=_LAYOUT, list_view=_LIST_VIEW),
        "task_spec_builder": _spec_builder,
        "execute_write_model": _SynthExecuteWrite,
        "execute_response_model": _SynthExecuteResponse,
        "capabilities_provider": _capabilities_provider,
        "extra_routes": (_extra_router(),),
    }
    kwargs.update(overrides)
    return TaskExecutionApp(**kwargs)


def _task_dict(name: str, *, meta: dict | None = None) -> dict:
    """Return a created-task payload owned by the synthetic owner."""
    return TaskFactory.build(
        name=name, owner=_OWNER.value, data={"meta": meta or {}}
    ).model_dump(mode="json")


def _execute_response(name: str, task_id: int = 99) -> dict:
    """Return a minimal ``TaskHistoryResponse``-shaped dict for execute tests."""
    return {
        "id": task_id,
        "execution_request": {"task": "synth-cmd", "target": "host1"},
        "task": {**_task_dict(name), "deleted_at": None},
    }


def _fake_service() -> dict:
    """Return the inventory service wire dict the fake Inventory API returns."""
    return CreatedServiceFactory.build(
        node=CreatedNodeFactory.build(address=_SERVICE_HOST),
        type=ServiceTypeEnum.MYSQL,
        name="svc-1",
        port=_SERVICE_PORT,
    ).model_dump(mode="json")


def _make_tasks_api(
    *,
    list_items: list[dict] | None = None,
    list_total: int | None = None,
    detail_task: dict | None = None,
    created_task: dict | None = None,
    latest_statuses: dict[str, str | None] | None = None,
) -> AsyncMock:
    """Build an ``AsyncMock(spec=RemoteAPI)`` routing Tasks-API calls in memory."""
    api = AsyncMock(spec=RemoteAPI)

    async def _get(path: str, params: dict | None = None) -> dict:
        if path == "/":
            envelope = {"items": list_items or []}
            if list_total is not None:
                envelope["total"] = list_total
            return envelope
        if path.endswith("/history/"):
            return {"items": []}
        return detail_task if detail_task is not None else {}

    async def _post(path: str, json: dict | None = None) -> dict:
        if path == "/history/latest":
            names = (json or {}).get("names", [])
            return {name: (latest_statuses or {}).get(name) for name in names}
        return created_task if created_task is not None else {}

    api.get.side_effect = _get
    api.post.side_effect = _post
    return api


def _make_inventory_api() -> AsyncMock:
    """Build an ``AsyncMock(spec=RemoteAPI)`` returning the fake service."""
    api = AsyncMock(spec=RemoteAPI)

    async def _get(path: str, params: dict | None = None) -> dict:
        return _fake_service()

    api.get.side_effect = _get
    return api


def _mount(app_def: TaskExecutionApp) -> FastAPI:
    """Mount the app's derived router under the production-shape router tree."""
    plugins_router = APIRouter(prefix="/plugins")
    plugins_router.include_router(app_def.api_router, prefix=_PREFIX)
    api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
    api_router.include_router(plugins_router)
    app = FastAPI()
    app.include_router(api_router)

    @app.get("/login", name="login")
    async def _login() -> dict[str, bool]:
        return {"ok": True}

    return app


def _client(
    app_def: TaskExecutionApp,
    tasks_api: AsyncMock,
    user: CasdoorUser,
    inventory_api: AsyncMock | None = None,
) -> TestClient:
    """Mount ``app_def`` with auth, Tasks-API, and Inventory-API overrides."""
    app = _mount(app_def)
    app.dependency_overrides[get_api_authenticated_user] = lambda: user
    app.dependency_overrides[get_tasks_api] = lambda: tasks_api
    if inventory_api is not None:
        app.dependency_overrides[get_inventory_api] = lambda: inventory_api
    return TestClient(app, raise_server_exceptions=False)


def _routes(app_def: TaskExecutionApp) -> set[tuple[str, str]]:
    """Return the ``(path, method)`` pairs registered on the app's router."""
    return {
        (route.path, method)
        for route in app_def.api_router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


class TestRouterComposition:
    """Inspect the derived router without HTTP."""

    def test_registers_every_derived_surface(self) -> None:
        """Assert schema, capabilities, list, detail, create, execute, extra exist."""
        routes = _routes(_synth_app())

        assert ("/schema", "GET") in routes
        assert ("/capabilities", "GET") in routes
        assert ("/", "GET") in routes
        assert ("/{task_name}", "GET") in routes
        assert ("/", "POST") in routes
        assert ("/{task_name}/execute", "POST") in routes
        assert ("/ping", "GET") in routes

    def test_capabilities_registered_before_greedy_detail(self) -> None:
        """Assert ``/capabilities`` precedes the greedy ``/{task_name}`` route."""
        api_routes = [
            r for r in _synth_app().api_router.routes if isinstance(r, APIRoute)
        ]
        paths = [r.path for r in api_routes]

        assert paths.index("/capabilities") < paths.index("/{task_name}")

    def test_no_create_route_when_create_capability_off(self) -> None:
        """Assert ``create=False`` derives no ``POST /`` route."""
        routes = _routes(_synth_app(capabilities=AppCapabilities(create=False)))

        assert ("/", "POST") not in routes
        assert ("/{task_name}", "GET") in routes

    def test_no_execute_route_when_execute_capability_off(self) -> None:
        """Assert ``execute=False`` derives no execute route."""
        routes = _routes(_synth_app(capabilities=AppCapabilities(execute=False)))

        assert ("/{task_name}/execute", "POST") not in routes

    def test_no_update_or_delete_routes_by_default(self) -> None:
        """Assert no ``PUT`` / ``DELETE`` route is derived without the capability."""
        routes = _routes(_synth_app())

        assert ("/{task_name}", "PUT") not in routes
        assert ("/{task_name}", "DELETE") not in routes

    def test_delete_route_when_capability_and_handler(self) -> None:
        """Assert ``delete=True`` with a handler derives a ``DELETE`` route at 204."""
        app_def = _synth_app(
            capabilities=AppCapabilities(delete=True), delete_handler=_delete_handler
        )
        delete_route = next(
            route
            for route in app_def.api_router.routes
            if isinstance(route, APIRoute)
            and route.path == "/{task_name}"
            and "DELETE" in route.methods
        )

        assert delete_route.status_code == status.HTTP_204_NO_CONTENT

    def test_task_dep_property_resolves_to_task(self) -> None:
        """Assert ``task_dep`` exposes an ``Annotated[Task, Depends(...)]`` alias."""
        task_dep = _synth_app().task_dep

        assert get_args(task_dep)[0] is Task


class TestSchemaEndpoint:
    """Exercise ``GET /schema`` over HTTP."""

    def test_schema_returns_derived_plugin_schema(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert the schema route returns the derived ``PluginSchema``."""
        client = _client(_synth_app(), _make_tasks_api(), regular_user)

        response = client.get(f"{_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "synthetic-app"


class TestCapabilitiesEndpoint:
    """Exercise ``GET /capabilities`` over HTTP."""

    def test_capabilities_not_shadowed_by_greedy_detail(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert ``/capabilities`` resolves to the provider, not the detail route."""
        client = _client(_synth_app(), _make_tasks_api(), regular_user)

        response = client.get(f"{_BASE}/capabilities")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"manual_sync_enabled": True}


class TestListAndDetail:
    """Exercise the list and detail routes over HTTP."""

    def test_list_returns_responses(self, regular_user: CasdoorUser) -> None:
        """Assert ``GET /`` returns the derived list responses."""
        tasks_api = _make_tasks_api(list_items=[_task_dict("t-1")])
        client = _client(_synth_app(), tasks_api, regular_user)

        response = client.get(f"{_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        assert [item["name"] for item in response.json()] == ["t-1"]

    def test_paginated_list_returns_paginated_response(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert a pagination dep switches the list to a ``PaginatedResponse``."""
        tasks_api = _make_tasks_api(list_items=[_task_dict("t-1")], list_total=1)
        client = _client(
            _synth_app(pagination=make_pagination_dep(max_limit=50)),
            tasks_api,
            regular_user,
        )

        response = client.get(f"{_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert [item["name"] for item in body["items"]] == ["t-1"]

    def test_detail_returns_response(self, regular_user: CasdoorUser) -> None:
        """Assert ``GET /{task_name}`` returns the derived detail response."""
        tasks_api = _make_tasks_api(detail_task=_task_dict("t-1"))
        client = _client(_synth_app(), tasks_api, regular_user)

        response = client.get(f"{_BASE}/t-1")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "t-1"


class TestCreateRoute:
    """Exercise the ``POST /`` create route over HTTP without overriding the body dep."""

    def test_create_posts_derived_envelope(self, regular_user: CasdoorUser) -> None:
        """Assert a real form POST builds and posts the three-phase envelope."""
        tasks_api = _make_tasks_api(created_task=_task_dict("new-task"))
        client = _client(
            _synth_app(), tasks_api, regular_user, inventory_api=_make_inventory_api()
        )

        response = client.post(
            f"{_BASE}/",
            data={"task_name": "new-task", "service_id": 1, "alert_on_fail": "true"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        create_call = next(
            call for call in tasks_api.post.await_args_list if call.args[0] == "/"
        )
        posted = create_call.kwargs["json"]
        assert posted["data"]["task"] == "run-command"
        assert posted["data"]["meta"]["command"] == "synth-cmd"
        assert posted["data"]["meta"][CONNECTIVITY_META_HOST_KEY] == _SERVICE_HOST
        assert posted["data"]["meta"][CONNECTIVITY_META_PORT_KEY] == _SERVICE_PORT
        assert (
            posted["data"]["meta"][CONNECTIVITY_META_SERVICE_TYPE_KEY]
            == ServiceTypeEnum.MYSQL.value
        )
        assert posted["alert_on_fail"] is True

    def test_create_422_on_invalid_body(self, regular_user: CasdoorUser) -> None:
        """Assert a body missing required fields 422s before any upstream POST."""
        tasks_api = _make_tasks_api(created_task=_task_dict("new-task"))
        client = _client(
            _synth_app(), tasks_api, regular_user, inventory_api=_make_inventory_api()
        )

        response = client.post(f"{_BASE}/", data={"task_name": "new-task"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        tasks_api.post.assert_not_awaited()

    def test_create_attaches_connectivity_warning(
        self, regular_user: CasdoorUser, mocker
    ) -> None:
        """Assert ``connectivity_check`` attaches the probe warning to the response."""
        warning = ConnectivityWarning(
            target="db-host", service_type="mysql", message="unreachable"
        )
        mocker.patch(
            "app.sep.plugins.framework.connectivity.record_connectivity_warning",
            new_callable=AsyncMock,
            return_value=warning,
        )
        created = _task_dict(
            "new-task",
            meta={
                "target": "db-host",
                CONNECTIVITY_META_HOST_KEY: "db-host",
                CONNECTIVITY_META_PORT_KEY: 3306,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: "mysql",
            },
        )
        tasks_api = _make_tasks_api(created_task=created)
        client = _client(
            _synth_app(connectivity_check=True),
            tasks_api,
            regular_user,
            inventory_api=_make_inventory_api(),
        )

        response = client.post(
            f"{_BASE}/", data={"task_name": "new-task", "service_id": 1}
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["connectivity_warning"] == {
            "target": "db-host",
            "service_type": "mysql",
            "message": "unreachable",
        }


class TestExecuteRoute:
    """Exercise the ``POST /{task_name}/execute`` route over HTTP."""

    def test_execute_returns_201(self, regular_user: CasdoorUser) -> None:
        """Assert execute dispatches upstream and returns task name + id."""
        tasks_api = _make_tasks_api(
            detail_task=_task_dict("t-1"), created_task=_execute_response("t-1")
        )
        client = _client(_synth_app(), tasks_api, regular_user)

        response = client.post(f"{_BASE}/t-1/execute", json={"note": "go"})

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {"task_name": "t-1", "task_id": 99}


class TestVerbGating:
    """Cover that capability flags gate which verbs are reachable over HTTP."""

    def test_read_only_app_blocks_create_and_execute(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert a read-only app 404/405s create and execute but serves reads."""
        app_def = _synth_app(capabilities=AppCapabilities(create=False, execute=False))
        tasks_api = _make_tasks_api(detail_task=_task_dict("t-1"))
        client = _client(app_def, tasks_api, regular_user)

        create = client.post(f"{_BASE}/", data={"task_name": "t", "service_id": 1})
        execute = client.post(f"{_BASE}/t-1/execute", json={})
        detail = client.get(f"{_BASE}/t-1")

        assert create.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        assert execute.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        assert detail.status_code == status.HTTP_200_OK


class TestExtraRoutePrecedence:
    """Cover that extra routes never shadow a derived route."""

    def test_extra_route_does_not_shadow_derived_detail(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert a colliding extra route loses to the first-registered derived one."""
        colliding = APIRouter()

        @colliding.get("/{task_name}", dependencies=[IsApiAuthenticated])
        async def _shadow(task_name: str) -> dict[str, str]:
            return {"shadowed": task_name}

        tasks_api = _make_tasks_api(detail_task=_task_dict("t-1"))
        client = _client(_synth_app(extra_routes=(colliding,)), tasks_api, regular_user)

        response = client.get(f"{_BASE}/t-1")

        assert response.status_code == status.HTTP_200_OK
        assert "shadowed" not in response.json()
        assert response.json()["name"] == "t-1"


class TestDefinitionValidation:
    """Cover the construction-time guards on the definition."""

    def test_both_schema_sources_raises(self) -> None:
        """Assert setting both ``create_model`` and ``schema=`` is rejected."""
        with pytest.raises(ValueError, match="create_model"):
            _synth_app(schema=_PASSTHROUGH_SCHEMA)

    def test_no_schema_source_raises(self) -> None:
        """Assert setting neither ``create_model`` nor ``schema=`` is rejected."""
        with pytest.raises(ValueError, match="schema"):
            _synth_app(create_model=None, payload_builder=None, task_spec_builder=None)

    def test_schema_passthrough_with_spec_builder_raises(self) -> None:
        """Assert a ``schema=`` app with a ``task_spec_builder`` is rejected."""
        with pytest.raises(ValueError, match="payload_builder"):
            _synth_app(create_model=None, schema=_PASSTHROUGH_SCHEMA)

    def test_non_default_detail_path_without_custom_dep_raises(self) -> None:
        """Assert a non-default ``detail_path_param`` needs a custom task dep."""
        with pytest.raises(ValueError, match="detail_path_param"):
            _synth_app(detail_path_param="name")

    def test_execute_without_models_raises(self) -> None:
        """Assert enabling execute without its models is rejected."""
        with pytest.raises(ValueError, match="execute"):
            _synth_app(execute_write_model=None)

    def test_missing_response_model_raises(self) -> None:
        """Assert a definition without a ``response_model`` is rejected."""
        with pytest.raises(ValueError, match="response_model"):
            _synth_app(response_model=None)

    def test_create_model_without_task_name_raises(self) -> None:
        """Assert a ``create_model`` lacking a ``task_name`` field is rejected."""
        with pytest.raises(ValueError, match="task_name"):
            _synth_app(create_model=_NoTaskNameForm)

    def test_create_model_without_layout_raises(self) -> None:
        """Assert a ``create_model`` app without ``views.layout`` is rejected."""
        with pytest.raises(ValueError, match="layout"):
            _synth_app(views=Views(list_view=_LIST_VIEW))

    def test_create_disabled_with_connectivity_check_raises(self) -> None:
        """Assert a create-disabled app with connectivity_check is rejected."""
        with pytest.raises(ValueError, match="connectivity_check"):
            _synth_app(
                capabilities=AppCapabilities(create=False),
                connectivity_check=True,
            )

    def test_create_disabled_with_create_response_model_raises(self) -> None:
        """Assert a create-disabled app with create_response_model is rejected."""
        with pytest.raises(ValueError, match="create_response_model"):
            _synth_app(
                capabilities=AppCapabilities(create=False),
                create_response_model=_SynthResponse,
            )


class TestSchemaPassthrough:
    """Cover the transitional ``schema=`` app with a ``payload_builder``."""

    def test_schema_app_with_payload_builder_serves_passthrough_schema(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert a ``schema=`` app derives routes and serves the supplied schema."""
        app_def = _synth_app(
            create_model=None,
            task_spec_builder=None,
            schema=_PASSTHROUGH_SCHEMA,
            payload_builder=_passthrough_payload_builder,
        )

        assert ("/", "POST") in _routes(app_def)
        client = _client(app_def, _make_tasks_api(), regular_user)
        response = client.get(f"{_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "synthetic-app"


class TestRegistryBinding:
    """Cover that binding an activation entry preserves the prebuilt router."""

    def test_display_only_overrides_keep_router_schema_intact(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert display-only overrides leave the derived schema name intact."""
        app_def = _synth_app()
        bound = app_def.model_copy(
            update={
                "key": "synthetic-app",
                "display_name": "Renamed Synthetic",
                "uri_path": "/renamed",
            }
        )
        client = _client(bound, _make_tasks_api(), regular_user)

        response = client.get(f"{_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "synthetic-app"
        assert bound.api_router is app_def.api_router
