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

"""Define tests for the plugin route helpers in ``framework.api``.

Covers the ``/schema`` and ``/capabilities`` discovery endpoints plus the
``derive_crud_routes`` CRUD route factory.
"""

from dataclasses import dataclass
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Body, Depends, FastAPI, status
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import HTTPConflictException
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import make_pagination_dep
from app.core.requests.remote_api import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.models import CasdoorUser
from app.sep.deps import (
    get_api_authenticated_user,
    get_task_by_name,
    get_tasks_api,
    IsApiAuthenticated,
    TaskAPI,
)
from app.sep.plugins.framework.api import (
    capabilities_endpoint,
    derive_crud_routes,
    schema_endpoint,
)
from app.sep.plugins.framework.deps import make_task_dep
from app.sep.plugins.framework.rules import (
    CardinalityRule,
    F,
    FailRule,
    FieldGate,
    truthy,
)
from app.sep.plugins.framework.schema import (
    BoolField,
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    DateTimeField,
    DerivedTask,
    DetailField,
    DetailSection,
    DetailView,
    FileField,
    FloatField,
    FormSection,
    HostField,
    IntegerField,
    ListView,
    MultiChoiceField,
    PluginSchema,
    SchemaField,
    ServiceField,
    StringField,
    TableField,
    TextAreaField,
    YamlField,
)
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskOwner, TaskWrite
from tests.app.factories import TaskFactory

_TEST_SCHEMA = PluginSchema(
    name="test-schema-endpoint",
    display_name="Test Schema Endpoint",
    forms=[
        FormSection(
            title="Options",
            fields=[BoolField(name="flag", label="Flag")],
        ),
    ],
    list_view=ListView(columns=[Column(key="id", label="ID")]),
)


_ALL_FIELDS_SCHEMA = PluginSchema(
    name="test-all-fields",
    display_name="Test All Fields",
    description="Schema instance exercising every concrete field class.",
    task_type="test-all-fields-task",
    forms=[
        FormSection(
            title="Everything",
            fields=[
                BoolField(name="boolField", label="Bool"),
                ChoiceField(
                    name="choiceField",
                    label="Choice",
                    choices=[Choice(label="A", value="a")],
                ),
                DateTimeField(name="datetimeField", label="DateTime"),
                FileField(name="fileField", label="File"),
                FloatField(name="floatField", label="Float"),
                HostField(name="hostField", label="Host"),
                IntegerField(name="integerField", label="Integer"),
                MultiChoiceField(
                    name="multiChoiceField",
                    label="Multi Choice",
                    choices=[Choice(label="B", value="b")],
                ),
                ServiceField(
                    name="serviceField",
                    label="Service",
                    service_types=[ServiceTypeEnum.MYSQL],
                ),
                SchemaField(
                    name="schemaField",
                    label="Schema",
                    depends_on="serviceField",
                ),
                StringField(name="stringField", label="String"),
                TableField(
                    name="tableField",
                    label="Table",
                    depends_on="schemaField",
                ),
                TextAreaField(name="textareaField", label="TextArea"),
                YamlField(name="yamlField", label="Yaml"),
            ],
        ),
    ],
    capabilities=Capabilities(alert_on_fail=True, scheduling=True),
    list_view=ListView(
        columns=[
            Column(key="id", label="ID"),
            Column(key="status", label="Status", format=ColumnFormat.STATUS),
        ],
    ),
    detail_view=DetailView(
        sections=[
            DetailSection(
                title="Execution",
                fields=[
                    DetailField(path="data.meta.command", label="Command"),
                ],
            ),
        ],
    ),
)


_EMPTY_FORMS_SCHEMA = PluginSchema(
    name="test-empty-forms",
    display_name="Test Empty Forms",
    forms=[],
    list_view=ListView(columns=[Column(key="id", label="ID")]),
)


def _register_login_placeholder(app: FastAPI) -> None:
    """Register a no-op ``/login`` route so ``LoginRedirectException`` resolves.

    ``LoginRedirectException`` constructs its ``Location`` via
    ``request.url_for("login")``; without a named ``login`` route on the app
    that call raises ``NoMatchFound`` and masks the real 401 behaviour the
    test suite wants to observe.
    """

    @app.get("/login", name="login")
    async def _login_placeholder() -> dict[str, bool]:
        """Return a placeholder payload so ``request.url_for('login')`` resolves.

        :return: A fixed success payload.
        :rtype: dict[str, bool]
        """
        return {"ok": True}


def _mount_plugin_router(plugin_router: APIRouter, plugin_prefix: str) -> FastAPI:
    """Mount ``plugin_router`` under the production-shape router tree.

    Mirror ``app/sep/api/router.py`` exactly: plugin router → plugins router
    (``/plugins``) → api router (``/api`` with ``IsApiAuthenticated``) →
    ``FastAPI``. Return a fresh instance on every call so tests never touch
    the real ``sep_app``.

    :param plugin_router: The plugin's ``APIRouter`` (already carrying its routes).
    :type plugin_router: APIRouter
    :param plugin_prefix: The prefix under which the plugin router is mounted
        on the shared plugins router (for example ``/test-schema-endpoint``).
    :type plugin_prefix: str
    :return: A ``FastAPI`` application instance with the composed router tree.
    :rtype: FastAPI
    """
    plugins_router = APIRouter(prefix="/plugins")
    plugins_router.include_router(plugin_router, prefix=plugin_prefix)
    api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
    api_router.include_router(plugins_router)
    app = FastAPI()
    app.include_router(api_router)
    _register_login_placeholder(app)
    return app


def _build_composed_app(schema: PluginSchema, plugin_prefix: str) -> FastAPI:
    """Build a fresh FastAPI app exposing ``schema_endpoint`` over a schema.

    :param schema: The plugin schema the helper registers on the plugin router.
    :type schema: PluginSchema
    :param plugin_prefix: The prefix under which the plugin router is mounted
        on the shared plugins router (for example ``/test-schema-endpoint``).
    :type plugin_prefix: str
    :return: A ``FastAPI`` application instance with the composed router tree.
    :rtype: FastAPI
    """
    plugin_router = APIRouter()
    schema_endpoint(plugin_router, schema)
    return _mount_plugin_router(plugin_router, plugin_prefix)


@pytest.fixture
def authed_client(regular_user: CasdoorUser) -> TestClient:
    """Yield an authed ``TestClient`` over a production-shape composed app."""
    app = _build_composed_app(_TEST_SCHEMA, "/test-schema-endpoint")
    app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def authed_all_fields_client(regular_user: CasdoorUser) -> TestClient:
    """Yield an authed ``TestClient`` whose schema exercises every field class."""
    app = _build_composed_app(_ALL_FIELDS_SCHEMA, "/test-all-fields")
    app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def authed_empty_forms_client(regular_user: CasdoorUser) -> TestClient:
    """Yield an authed ``TestClient`` whose schema has zero form sections."""
    app = _build_composed_app(_EMPTY_FORMS_SCHEMA, "/test-empty-forms")
    app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def unauthed_client() -> TestClient:
    """Yield an unauthed ``TestClient`` over the same composed app."""
    app = _build_composed_app(_TEST_SCHEMA, "/test-schema-endpoint")
    return TestClient(app, raise_server_exceptions=False)


class TestSchemaEndpointRouterComposition:
    """Inspect the router in isolation, without involving HTTP or FastAPI apps."""

    def test_registers_single_get_schema_route(self) -> None:
        """Assert the helper registers exactly one ``GET /schema`` route."""
        router = APIRouter()
        schema_endpoint(router, _TEST_SCHEMA)

        schema_routes = [
            r for r in router.routes if isinstance(r, APIRoute) and r.path == "/schema"
        ]
        assert len(schema_routes) == 1
        assert schema_routes[0].methods == {"GET"}

    def test_route_declares_api_authenticated(self) -> None:
        """Assert the route declares ``IsApiAuthenticated`` as a per-route dep."""
        router = APIRouter()
        schema_endpoint(router, _TEST_SCHEMA)

        [route] = [r for r in router.routes if isinstance(r, APIRoute)]
        callables = {d.dependency for d in route.dependencies}
        assert get_api_authenticated_user in callables

    def test_route_declares_response_model(self) -> None:
        """Assert the route wires ``response_model=PluginSchema`` for OpenAPI."""
        router = APIRouter()
        schema_endpoint(router, _TEST_SCHEMA)

        [route] = [r for r in router.routes if isinstance(r, APIRoute)]
        assert route.response_model is PluginSchema

    def test_route_response_model_emits_by_alias(self) -> None:
        """Assert the route pins ``response_model_by_alias=True`` explicitly."""
        router = APIRouter()
        schema_endpoint(router, _TEST_SCHEMA)

        [route] = [r for r in router.routes if isinstance(r, APIRoute)]
        assert route.response_model_by_alias is True

    def test_second_call_raises_value_error(self) -> None:
        """Assert calling the helper twice on the same router raises."""
        router = APIRouter()
        schema_endpoint(router, _TEST_SCHEMA)

        with pytest.raises(ValueError, match="schema_endpoint"):
            schema_endpoint(router, _TEST_SCHEMA)

    def test_second_call_raises_value_error_on_prefixed_router(self) -> None:
        """Assert the duplicate guard works when the router carries a prefix.

        A prefix-bearing ``APIRouter`` records the route path as
        ``{prefix}/schema``, so the guard must compare against the router's
        effective path — not the bare ``/schema`` literal — or a second
        registration would slip through silently.
        """
        router = APIRouter(prefix="/plugin-prefix")
        schema_endpoint(router, _TEST_SCHEMA)

        with pytest.raises(ValueError, match="schema_endpoint"):
            schema_endpoint(router, _TEST_SCHEMA)

    def test_naked_app_unauth_returns_401(self) -> None:
        """Assert the per-route dep gates the route outside ``api_router``.

        Mount the plugin router on a naked ``FastAPI`` with no router-level
        auth, then confirm an unauthenticated GET still returns 401.
        """
        plugin_router = APIRouter()
        schema_endpoint(plugin_router, _TEST_SCHEMA)
        app = FastAPI()
        app.include_router(plugin_router)
        _register_login_placeholder(app)

        response = TestClient(app, raise_server_exceptions=False).get(
            "/schema", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")

    def test_duplicate_dep_runs_once_per_request(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert FastAPI deduplicates the router-level + per-route dep per request.

        Compose the production-shape router tree with ``IsApiAuthenticated``
        declared at both router level and (via the helper) route level, then
        spy on ``get_api_authenticated_user`` and confirm one authed request
        invokes it exactly once — the behaviour that makes the belt-and-
        braces deviation free.
        """
        call_count = {"n": 0}

        def spy() -> CasdoorUser:
            call_count["n"] += 1
            return regular_user

        app = _build_composed_app(_TEST_SCHEMA, "/test-schema-endpoint")
        app.dependency_overrides[get_api_authenticated_user] = spy
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/plugins/test-schema-endpoint/schema")
        assert response.status_code == status.HTTP_200_OK
        assert call_count["n"] == 1


class TestSchemaEndpointAuthenticated:
    """Exercise the helper over the production-shape composed router tree."""

    def test_authed_get_returns_serialised_schema(
        self, authed_client: TestClient
    ) -> None:
        """Assert an authed GET returns the full serialised schema payload."""
        response = authed_client.get("/api/plugins/test-schema-endpoint/schema")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == _TEST_SCHEMA.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )

    def test_response_content_type_is_json(self, authed_client: TestClient) -> None:
        """Assert the response carries a JSON ``content-type``."""
        response = authed_client.get("/api/plugins/test-schema-endpoint/schema")

        assert response.headers["content-type"].startswith("application/json")

    def test_response_uses_snake_case_keys(self, authed_client: TestClient) -> None:
        """Assert the response emits snake_case wire keys (not camelCase)."""
        body = authed_client.get("/api/plugins/test-schema-endpoint/schema").json()

        assert "display_name" in body
        assert "list_view" in body
        assert "displayName" not in body
        assert "listView" not in body

    def test_field_discriminator_key_is_type(self, authed_client: TestClient) -> None:
        """Assert each field carries ``type`` (not ``field_type``) as its discriminator."""
        body = authed_client.get("/api/plugins/test-schema-endpoint/schema").json()

        assert body["forms"][0]["fields"][0]["type"] == "bool"
        assert "field_type" not in body["forms"][0]["fields"][0]

    def test_openapi_documents_response_schema(self, authed_client: TestClient) -> None:
        """Assert the OpenAPI spec documents the ``PluginSchema`` response."""
        openapi = authed_client.get("/openapi.json").json()

        path = openapi["paths"]["/api/plugins/test-schema-endpoint/schema"]
        response_ref = path["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        schema_name = response_ref.rsplit("/", 1)[-1]
        resolved = openapi["components"]["schemas"][schema_name]
        property_keys = set(resolved["properties"].keys())

        assert {"display_name", "list_view", "forms"} <= property_keys

    def test_openapi_documents_detail_view(self, authed_client: TestClient) -> None:
        """Assert OpenAPI surfaces ``PluginSchema.detail_view`` + DetailView models.

        Regression guard: ``detail_view`` must remain visible to the generated
        TypeScript client. If the field is renamed or dropped without updating
        the frontend codegen, this test fails before the generated types go
        stale.
        """
        openapi = authed_client.get("/openapi.json").json()

        components = openapi["components"]["schemas"]
        plugin_schema = next(
            v for k, v in components.items() if k.endswith("PluginSchema")
        )
        assert "detail_view" in plugin_schema["properties"]

        for name in ("DetailView", "DetailSection", "DetailField"):
            assert any(k.endswith(name) for k in components), (
                f"{name!r} not present in OpenAPI components"
            )

    def test_empty_forms_serialises_as_empty_list(
        self, authed_empty_forms_client: TestClient
    ) -> None:
        """Assert a schema with no form sections round-trips as ``forms: []``."""
        body = authed_empty_forms_client.get(
            "/api/plugins/test-empty-forms/schema"
        ).json()

        assert body["forms"] == []


class TestSchemaEndpointUnauthenticated:
    """Assert unauthenticated access returns JSON 401 with no redirect."""

    def test_unauthed_get_returns_401_json(self, unauthed_client: TestClient) -> None:
        """Assert unauthenticated GET returns 401 JSON, not a 303 redirect."""
        response = unauthed_client.get(
            "/api/plugins/test-schema-endpoint/schema",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    def test_unauthed_response_has_no_location_header(
        self, unauthed_client: TestClient
    ) -> None:
        """Assert the 401 response does not carry a ``Location`` redirect header."""
        response = unauthed_client.get(
            "/api/plugins/test-schema-endpoint/schema",
            follow_redirects=False,
        )

        assert "location" not in {k.lower() for k in response.headers}


class TestSchemaEndpointAllFieldsRoundTrip:
    """Round-trip a schema containing every concrete field class."""

    def test_all_fields_schema_reparses_losslessly(
        self, authed_all_fields_client: TestClient
    ) -> None:
        """Assert the emitted JSON re-validates back into the original schema."""
        body = authed_all_fields_client.get(
            "/api/plugins/test-all-fields/schema"
        ).json()

        reparsed = PluginSchema.model_validate(body)
        assert reparsed == _ALL_FIELDS_SCHEMA


# ── Conditional-rule primitives wire-shape regression (SEP-1071) ────────


_CONDITIONAL_RULES_SCHEMA = PluginSchema(
    name="test-conditional-rules",
    display_name="Test Conditional Rules",
    forms=[
        FormSection(
            title="Recursion",
            fields=[
                StringField(name="recursion_method", label="Method"),
                StringField(
                    name="dsn_table",
                    label="DSN Table",
                    requires=[
                        FieldGate(when=F("recursion_method") == "dsn"),
                    ],
                    forbidden=[
                        FieldGate(when=F("recursion_method") == "none"),
                    ],
                ),
            ],
            cardinality_rules=[
                CardinalityRule(
                    when=truthy("recursion_method"),
                    fields=["dsn_table"],
                    max=1,
                    message="at most one",
                ),
            ],
        ),
    ],
    list_view=ListView(columns=[Column(key="id", label="ID")]),
    fail_when=[
        FailRule(
            fail_when=truthy("recursion_method"),
            error_fields=["recursion_method"],
            message="must not be set",
        ),
    ],
)


@pytest.fixture
def authed_conditional_rules_client(regular_user: CasdoorUser) -> TestClient:
    """Yield an authed client whose schema exercises the new rule primitives."""
    app = _build_composed_app(_CONDITIONAL_RULES_SCHEMA, "/test-conditional-rules")
    app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    return TestClient(app, raise_server_exceptions=False)


class TestConditionalRulePrimitivesWireShape:
    """Verify the new primitive keys serialize correctly over HTTP."""

    def test_response_carries_snake_case_primitive_keys(
        self, authed_conditional_rules_client: TestClient
    ) -> None:
        """Hit the live route and confirm snake_case primitive keys appear."""
        body = authed_conditional_rules_client.get(
            "/api/plugins/test-conditional-rules/schema"
        ).json()

        # PluginSchema-scope primitive
        assert "fail_when" in body
        assert isinstance(body["fail_when"], list)

        # FormSection-scope primitive
        section = body["forms"][0]
        assert "cardinality_rules" in section
        assert isinstance(section["cardinality_rules"], list)

        # BaseField-scope primitives
        dsn_table = section["fields"][1]
        assert dsn_table["name"] == "dsn_table"
        assert "requires" in dsn_table
        assert "forbidden" in dsn_table

    def test_predicate_serializes_via_to_dict(
        self, authed_conditional_rules_client: TestClient
    ) -> None:
        """Predicate serialises via to_dict."""
        body = authed_conditional_rules_client.get(
            "/api/plugins/test-conditional-rules/schema"
        ).json()

        gate = body["forms"][0]["fields"][1]["requires"][0]
        assert gate["when"] == {"equals": {"recursion_method": "dsn"}}

        rule = body["forms"][0]["cardinality_rules"][0]
        assert rule["when"] == {"truthy": "recursion_method"}
        assert rule["fields"] == ["dsn_table"]
        assert rule["max"] == 1


class TestSchemaResponseExcludeNone:
    """Verify ``response_model_exclude_none=True`` keeps unused keys absent."""

    def test_no_new_primitive_keys_when_unused(
        self, authed_all_fields_client: TestClient
    ) -> None:
        """A schema without conditional rules emits no rule-primitive keys."""
        body = authed_all_fields_client.get(
            "/api/plugins/test-all-fields/schema"
        ).json()

        for forbidden_key in (
            "requires",
            "forbidden",
            "cardinality_rules",
            "fail_when",
        ):
            assert forbidden_key not in body, f"{forbidden_key!r} leaked at top level"

        for section in body["forms"]:
            for forbidden_key in ("cardinality_rules", "fail_when"):
                assert forbidden_key not in section, (
                    f"{forbidden_key!r} leaked into a section"
                )
            for field in section["fields"]:
                for forbidden_key in ("requires", "forbidden"):
                    assert forbidden_key not in field, (
                        f"{forbidden_key!r} leaked into field {field['name']!r}"
                    )


# ── DerivedTask cascade primitive wire-shape regression (SEP-1074) ──────


_DERIVED_SCHEMA = PluginSchema(
    name="test-derived",
    display_name="Test Derived",
    forms=[
        FormSection(
            title="Options",
            fields=[BoolField(name="flag", label="Flag")],
        ),
    ],
    list_view=ListView(columns=[Column(key="id", label="ID")]),
    derived=[
        DerivedTask(
            name_suffix="-dry-run",
            arg_substitutions={"--execute": "--dry-run"},
            parent_link=True,
        ),
    ],
)


@pytest.fixture
def authed_derived_client(regular_user: CasdoorUser) -> TestClient:
    """Yield an authed client whose schema exercises the ``derived`` field."""
    app = _build_composed_app(_DERIVED_SCHEMA, "/test-derived")
    app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    return TestClient(app, raise_server_exceptions=False)


class TestDerivedFieldWireShape:
    """Verify the ``derived`` key behaves correctly on the live response."""

    def test_response_excludes_derived_when_none(
        self, authed_client: TestClient
    ) -> None:
        """Verify ``derived`` is absent when the schema does not set it (BC guard)."""
        body = authed_client.get("/api/plugins/test-schema-endpoint/schema").json()

        assert "derived" not in body

    def test_response_includes_derived_when_set(
        self, authed_derived_client: TestClient
    ) -> None:
        """Verify ``derived`` serialises in snake_case when the schema sets it."""
        body = authed_derived_client.get("/api/plugins/test-derived/schema").json()

        assert "derived" in body
        assert isinstance(body["derived"], list)
        assert len(body["derived"]) == 1
        entry = body["derived"][0]
        assert entry["name_suffix"] == "-dry-run"
        assert entry["arg_substitutions"] == {"--execute": "--dry-run"}
        assert entry["parent_link"] is True


# ── capabilities_endpoint() helper (SEP-1133) ───────────────────────────


class _DummyCapabilities(BaseModel):
    """Tiny capability response model used by the helper tests."""

    flag: bool


_provider_state: dict[str, bool] = {"flag": False}


def _stateful_provider() -> _DummyCapabilities:
    """Read from a module-level dict so a test can mutate it between requests."""
    return _DummyCapabilities(flag=_provider_state["flag"])


def _build_capabilities_app(
    provider, plugin_prefix: str = "/test-capabilities-endpoint"
) -> FastAPI:
    """Build a production-shape composed app exposing ``GET /capabilities``."""
    plugin_router = APIRouter()
    capabilities_endpoint(plugin_router, capabilities_provider=provider)
    return _mount_plugin_router(plugin_router, plugin_prefix)


class TestCapabilitiesEndpointRegistration:
    """Inspect the router and the fail-fast guards in isolation."""

    def test_registers_single_get_capabilities_route(self) -> None:
        """Assert the helper registers exactly one ``GET /capabilities`` route."""

        def provider() -> _DummyCapabilities:
            return _DummyCapabilities(flag=True)

        router = APIRouter()
        capabilities_endpoint(router, capabilities_provider=provider)

        routes = [
            r
            for r in router.routes
            if isinstance(r, APIRoute) and r.path == "/capabilities"
        ]
        assert len(routes) == 1
        assert routes[0].methods == {"GET"}

    def test_route_declares_api_authenticated(self) -> None:
        """Assert the route declares ``IsApiAuthenticated`` as a per-route dependency."""

        def provider() -> _DummyCapabilities:
            return _DummyCapabilities(flag=True)

        router = APIRouter()
        capabilities_endpoint(router, capabilities_provider=provider)

        [route] = [
            r
            for r in router.routes
            if isinstance(r, APIRoute) and r.path == "/capabilities"
        ]
        callables = {d.dependency for d in route.dependencies}
        assert get_api_authenticated_user in callables

    def test_response_model_inferred_from_return_annotation(self) -> None:
        """Assert the route's ``response_model`` matches the provider's return annotation."""

        def provider() -> _DummyCapabilities:
            return _DummyCapabilities(flag=True)

        router = APIRouter()
        capabilities_endpoint(router, capabilities_provider=provider)

        [route] = [
            r
            for r in router.routes
            if isinstance(r, APIRoute) and r.path == "/capabilities"
        ]
        assert route.response_model is _DummyCapabilities

    def test_second_call_raises_value_error(self) -> None:
        """Assert calling the helper twice on same router raises ``ValueError``."""

        def provider() -> _DummyCapabilities:
            return _DummyCapabilities(flag=True)

        router = APIRouter()
        capabilities_endpoint(router, capabilities_provider=provider)

        with pytest.raises(ValueError, match="capabilities_endpoint"):
            capabilities_endpoint(router, capabilities_provider=provider)

    def test_second_call_raises_value_error_on_prefixed_router(self) -> None:
        """Assert the duplicate guard works when the router carries a prefix."""

        def provider() -> _DummyCapabilities:
            return _DummyCapabilities(flag=True)

        router = APIRouter(prefix="/plugin-prefix")
        capabilities_endpoint(router, capabilities_provider=provider)

        with pytest.raises(ValueError, match="capabilities_endpoint"):
            capabilities_endpoint(router, capabilities_provider=provider)

    def test_coexists_with_schema_endpoint_on_same_router(self) -> None:
        """Assert schema and capabilities helpers do not collide on the same router."""

        def provider() -> _DummyCapabilities:
            return _DummyCapabilities(flag=True)

        router = APIRouter()
        schema_endpoint(router, _TEST_SCHEMA)
        capabilities_endpoint(router, capabilities_provider=provider)

        paths = {r.path for r in router.routes if isinstance(r, APIRoute)}
        assert "/schema" in paths
        assert "/capabilities" in paths

    def test_missing_return_annotation_raises_type_error(self) -> None:
        """Assert a provider without a return annotation fails at registration."""

        def provider():  # no return annotation
            return _DummyCapabilities(flag=True)

        router = APIRouter()
        with pytest.raises(TypeError, match="return type annotation"):
            capabilities_endpoint(router, capabilities_provider=provider)

    def test_non_class_return_annotation_raises_type_error(self) -> None:
        """Assert a provider whose return annotation isn't a class fails."""

        def provider() -> int | None:
            return None

        router = APIRouter()
        with pytest.raises(TypeError, match="BaseModel"):
            capabilities_endpoint(router, capabilities_provider=provider)

    def test_non_basemodel_class_return_annotation_raises_type_error(self) -> None:
        """Assert a provider returning a non-BaseModel class fails."""

        def provider() -> dict:
            return {}

        router = APIRouter()
        with pytest.raises(TypeError, match="BaseModel"):
            capabilities_endpoint(router, capabilities_provider=provider)

    def test_dataclass_return_annotation_raises_type_error(self) -> None:
        """Assert a dataclass return annotation is not a BaseModel subclass — fails."""

        @dataclass
        class _NotAModel:
            flag: bool

        def provider() -> _NotAModel:
            return _NotAModel(flag=True)

        router = APIRouter()
        with pytest.raises(TypeError, match="BaseModel"):
            capabilities_endpoint(router, capabilities_provider=provider)

    def test_async_provider_raises_type_error(self) -> None:
        """Assert an ``async def`` provider is rejected at registration.

        Calling an async function from the sync handler would return a
        coroutine object, which response_model serialisation cannot
        handle. Async / DB-backed providers are explicitly out of scope;
        the guard prevents the silent-500-at-first-request footgun and
        keeps the contract fail-fast.
        """

        async def provider() -> _DummyCapabilities:
            return _DummyCapabilities(flag=True)

        router = APIRouter()
        with pytest.raises(TypeError, match="sync callable"):
            capabilities_endpoint(router, capabilities_provider=provider)

    def test_future_annotations_provider_resolved(self) -> None:
        """Assert a provider whose return annotation is stringized.

        ``from __future__ import annotations`` stores every annotation
        as a string; the helper must resolve it back to the real class
        via ``typing.get_type_hints`` instead of failing the BaseModel
        guard with a misleading error.
        """
        import textwrap
        import types

        module = types.ModuleType("_sep1133_future_annotations_probe")
        module.__dict__["_DummyCapabilities"] = _DummyCapabilities
        exec(
            textwrap.dedent(
                """
                from __future__ import annotations

                def provider() -> _DummyCapabilities:
                    return _DummyCapabilities(flag=True)
                """
            ),
            module.__dict__,
        )

        router = APIRouter()
        capabilities_endpoint(router, capabilities_provider=module.provider)

        [route] = [
            r
            for r in router.routes
            if isinstance(r, APIRoute) and r.path == "/capabilities"
        ]
        assert route.response_model is _DummyCapabilities

    def test_plain_basemodel_subclass_accepted(self) -> None:
        """Assert any direct BaseModel subclass is accepted as the response type."""

        class _RawModel(BaseModel):
            flag: bool

        def provider() -> _RawModel:
            return _RawModel(flag=True)

        router = APIRouter()
        capabilities_endpoint(router, capabilities_provider=provider)
        [route] = [
            r
            for r in router.routes
            if isinstance(r, APIRoute) and r.path == "/capabilities"
        ]
        assert route.response_model is _RawModel


class TestCapabilitiesEndpointAuthenticated:
    """Exercise the helper over the production-shape composed router tree."""

    @pytest.fixture
    def authed_capabilities_client(self, regular_user: CasdoorUser) -> TestClient:
        """Yield an authed ``TestClient`` over the capabilities-app."""
        _provider_state["flag"] = True
        app = _build_capabilities_app(_stateful_provider)
        app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
        return TestClient(app, raise_server_exceptions=False)

    def test_authed_get_returns_provider_payload(
        self, authed_capabilities_client: TestClient
    ) -> None:
        """Assert an authed GET returns the provider's payload as JSON."""
        _provider_state["flag"] = True
        response = authed_capabilities_client.get(
            "/api/plugins/test-capabilities-endpoint/capabilities"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"flag": True}
        assert response.headers["content-type"].startswith("application/json")

    def test_response_body_matches_pydantic_dump(
        self, authed_capabilities_client: TestClient
    ) -> None:
        """Assert the response equals the provider's pydantic dump."""
        _provider_state["flag"] = False
        body = authed_capabilities_client.get(
            "/api/plugins/test-capabilities-endpoint/capabilities"
        ).json()

        assert body == _DummyCapabilities(flag=False).model_dump(mode="json")

    def test_provider_invoked_per_request(
        self, authed_capabilities_client: TestClient
    ) -> None:
        """Assert mutating provider state between requests is reflected live.

        Critical for hot-reload semantics: the helper must not cache
        the provider's return value across requests, or deployment-
        config changes would require a restart to take effect.
        """
        _provider_state["flag"] = False
        first = authed_capabilities_client.get(
            "/api/plugins/test-capabilities-endpoint/capabilities"
        )
        _provider_state["flag"] = True
        second = authed_capabilities_client.get(
            "/api/plugins/test-capabilities-endpoint/capabilities"
        )

        assert first.json() == {"flag": False}
        assert second.json() == {"flag": True}


class TestCapabilitiesEndpointUnauthenticated:
    """Assert unauthenticated access returns JSON 401 with no redirect."""

    @pytest.fixture
    def unauthed_capabilities_client(self) -> TestClient:
        """Yield an unauthed ``TestClient`` over the same composed app."""
        app = _build_capabilities_app(_stateful_provider)
        return TestClient(app, raise_server_exceptions=False)

    def test_unauthed_get_returns_401_json(
        self, unauthed_capabilities_client: TestClient
    ) -> None:
        """Assert unauthenticated GET returns 401 JSON, not a 303 redirect."""
        response = unauthed_capabilities_client.get(
            "/api/plugins/test-capabilities-endpoint/capabilities",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    def test_naked_app_unauth_returns_401(self) -> None:
        """Assert the per-route dep gates the route even outside ``api_router``."""
        plugin_router = APIRouter()
        capabilities_endpoint(plugin_router, capabilities_provider=_stateful_provider)
        app = FastAPI()
        app.include_router(plugin_router)
        _register_login_placeholder(app)

        response = TestClient(app, raise_server_exceptions=False).get(
            "/capabilities", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")


class TestCapabilitiesEndpointOpenApi:
    """Assert the capabilities route documents itself in the OpenAPI spec."""

    def test_openapi_documents_capabilities_response(
        self, regular_user: CasdoorUser
    ) -> None:
        """``/openapi.json`` references the provider's response model.

        Parity with ``test_openapi_documents_response_schema`` for
        ``schema_endpoint``. The FE generator (``pnpm --filter @sep/api
        generate``) consumes this spec; a missing schema there would
        produce an untyped client.
        """
        app = _build_capabilities_app(_stateful_provider)
        app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
        client = TestClient(app, raise_server_exceptions=False)

        openapi = client.get("/openapi.json").json()

        path = openapi["paths"]["/api/plugins/test-capabilities-endpoint/capabilities"]
        response_ref = path["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        schema_name = response_ref.rsplit("/", 1)[-1]
        resolved = openapi["components"]["schemas"][schema_name]
        assert "flag" in resolved["properties"]


class TestCapabilitiesEndpointRuntime:
    """Assert request-time failure modes are surfaced, not silently swallowed."""

    def test_provider_exception_returns_500(self, regular_user: CasdoorUser) -> None:
        """Assert a provider raising at request time propagates to a 500.

        Pins the documented "out of scope to swallow" contract: provider
        correctness is the caller's responsibility. A regression that
        wrapped the handler in a silent try/except would mask plugin
        bugs in production.
        """

        def provider() -> _DummyCapabilities:
            raise RuntimeError("provider failed")

        app = _build_capabilities_app(provider)
        app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/plugins/test-capabilities-endpoint/capabilities")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_provider_with_depends_param_resolved(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert provider params annotated with ``Depends`` resolve per request.

        ``functools.wraps`` preserves the provider's signature so FastAPI
        inspects its parameter defaults and wires DI normally. This pins
        the contract that plugin authors may declare ``Depends(...)``
        params (settings, session, current user) on the provider rather
        than reading module globals.
        """

        def provide_flag() -> bool:
            return True

        def provider(
            *,
            flag: bool = Depends(provide_flag),
        ) -> _DummyCapabilities:
            return _DummyCapabilities(flag=flag)

        app = _build_capabilities_app(provider)
        app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/plugins/test-capabilities-endpoint/capabilities")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"flag": True}


# ── derive_crud_routes() helper ─────────────────────────────────────────


_SYNTHETIC_OWNER = TaskOwner.ARCHIVER
_CRUD_PREFIX = "/test-derive-crud"
_CRUD_BASE_URL = f"/api/plugins{_CRUD_PREFIX}"

_PAGE_OFFSET = 5
_PAGE_LIMIT = 2
_PAGE_TOTAL = 10


_SYNTHETIC_SCHEMA = PluginSchema(
    name="test-derive-crud",
    display_name="Test Derive CRUD",
    forms=[
        FormSection(title="Options", fields=[BoolField(name="flag", label="Flag")]),
    ],
    list_view=ListView(columns=[Column(key="id", label="ID")]),
)


class _SyntheticTaskResponse(BaseModel):
    """List/detail response model for the synthetic CRUD plugin.

    ``display_label`` carries a wire alias so the tests can prove the derived
    routes serialise with ``response_model_by_alias=True``.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    display_label: str = Field(alias="displayLabel")
    status: TaskHistoryStatusEnum | None = None


class _SyntheticCreateResponse(BaseModel):
    """Distinct create response model proving create may carry its own model."""

    name: str
    created: bool = True


class _SyntheticCreate(BaseModel):
    """Request body model for the synthetic create route."""

    name: str


def _build_synthetic_response(
    task: Task, status: TaskHistoryStatusEnum | None = None
) -> _SyntheticTaskResponse:
    """Build the synthetic list/detail response for ``task``."""
    return _SyntheticTaskResponse(
        name=task.name, display_label=task.name.upper(), status=status
    )


def _build_synthetic_create_response(task: Task) -> _SyntheticCreateResponse:
    """Build the distinct synthetic create response for ``task``."""
    return _SyntheticCreateResponse(name=task.name)


async def _build_synthetic_payload(
    form: Annotated[_SyntheticCreate, Body()],
) -> TaskWrite:
    """Build a ``TaskWrite`` from the synthetic create body (drives the 422)."""
    return TaskWrite(name=form.name, data={})


async def _get_task_by_alt_param(name: str, tasks_api: TaskAPI) -> Task:
    """Resolve a task whose detail path parameter is ``name`` (not ``task_name``)."""
    return await get_task_by_name(tasks_api, name, _SYNTHETIC_OWNER)


async def _synthetic_update_handler(
    task_name: str, tasks_api: TaskAPI
) -> _SyntheticTaskResponse:
    """Override update handler: resolve the task and echo it back."""
    task = await get_task_by_name(tasks_api, task_name, _SYNTHETIC_OWNER)
    return _build_synthetic_response(task, status=None)


async def _synthetic_delete_handler(task_name: str, tasks_api: TaskAPI) -> None:
    """Override delete handler: resolve the task and delete it upstream."""
    task = await get_task_by_name(tasks_api, task_name, _SYNTHETIC_OWNER)
    await tasks_api.delete(f"/{task.name}")


def _task_dict(name: str, owner: TaskOwner = _SYNTHETIC_OWNER) -> dict:
    """Return a JSON-serialisable ``Task`` payload for the mock Tasks API."""
    return TaskFactory.build(name=name, owner=owner.value, data={}).model_dump(
        mode="json"
    )


async def _fake_tasks_get(
    path: str,
    *,
    list_items: list[dict],
    list_total: int | None,
    detail_task: dict | None,
    history_items: list[dict],
    history_error: Exception | None,
) -> dict:
    """Route a fake Tasks-API ``GET`` by path for the in-memory backend."""
    if path == "/":
        envelope = {"items": list_items}
        if list_total is not None:
            envelope["total"] = list_total
        return envelope
    if path.endswith("/history/"):
        if history_error is not None:
            raise history_error
        return {"items": history_items}
    return detail_task if detail_task is not None else {}


async def _fake_tasks_post(
    path: str,
    json: dict | None,
    *,
    latest_statuses: dict[str, str | None],
    created_task: dict | None,
    batch_error: Exception | None,
    create_error: Exception | None,
) -> dict:
    """Route a fake Tasks-API ``POST`` by path for the in-memory backend."""
    if path == "/history/latest":
        if batch_error is not None:
            raise batch_error
        names = (json or {}).get("names", [])
        return {name: latest_statuses.get(name) for name in names}
    if create_error is not None:
        raise create_error
    return created_task if created_task is not None else {}


def _make_tasks_api(
    *,
    list_items: list[dict] | None = None,
    list_total: int | None = None,
    detail_task: dict | None = None,
    history_items: list[dict] | None = None,
    latest_statuses: dict[str, str | None] | None = None,
    created_task: dict | None = None,
    history_error: Exception | None = None,
    batch_error: Exception | None = None,
    create_error: Exception | None = None,
) -> AsyncMock:
    """Build an ``AsyncMock(spec=RemoteAPI)`` routing Tasks-API calls in memory."""
    api = AsyncMock(spec=RemoteAPI)

    async def _get(path: str, params: dict | None = None) -> dict:
        return await _fake_tasks_get(
            path,
            list_items=list_items or [],
            list_total=list_total,
            detail_task=detail_task,
            history_items=history_items or [],
            history_error=history_error,
        )

    async def _post(path: str, json: dict | None = None) -> dict:
        return await _fake_tasks_post(
            path,
            json,
            latest_statuses=latest_statuses or {},
            created_task=created_task,
            batch_error=batch_error,
            create_error=create_error,
        )

    async def _delete(path: str) -> None:
        return None

    api.get.side_effect = _get
    api.post.side_effect = _post
    api.delete.side_effect = _delete
    return api


def _crud_router(**overrides: object) -> APIRouter:
    """Build a ``derive_crud_routes`` router with sane synthetic defaults."""
    kwargs = {
        "task_owner": _SYNTHETIC_OWNER,
        "get_task": make_task_dep(_SYNTHETIC_OWNER),
        "response_builder": _build_synthetic_response,
        "create_payload": _build_synthetic_payload,
    }
    kwargs.update(overrides)
    return derive_crud_routes(_SYNTHETIC_SCHEMA, **kwargs)


def _authed_crud_client(
    router: APIRouter, tasks_api: AsyncMock, user: CasdoorUser
) -> TestClient:
    """Mount ``router`` in a production-shape app with auth + Tasks-API overrides."""
    app = _mount_plugin_router(router, _CRUD_PREFIX)
    app.dependency_overrides[get_api_authenticated_user] = lambda: user
    app.dependency_overrides[get_tasks_api] = lambda: tasks_api
    return TestClient(app, raise_server_exceptions=False)


def _api_routes(router: APIRouter) -> list[APIRoute]:
    """Return the concrete ``APIRoute`` objects registered on ``router``."""
    return [r for r in router.routes if isinstance(r, APIRoute)]


def _route_for(router: APIRouter, path: str, method: str) -> APIRoute:
    """Return the single ``APIRoute`` on ``router`` matching ``path`` + ``method``."""
    [route] = [r for r in _api_routes(router) if r.path == path and method in r.methods]
    return route


class TestDeriveCrudRoutesComposition:
    """Inspect the returned router in isolation, without HTTP."""

    def test_registers_schema_and_core_routes(self) -> None:
        """Assert the router carries ``/schema`` plus list / detail / create."""
        router = _crud_router()
        registered = {(r.path, frozenset(r.methods)) for r in _api_routes(router)}

        assert ("/schema", frozenset({"GET"})) in registered
        assert ("/", frozenset({"GET"})) in registered
        assert ("/{task_name}", frozenset({"GET"})) in registered
        assert ("/", frozenset({"POST"})) in registered

    def test_no_update_or_delete_route_by_default(self) -> None:
        """Assert no ``PUT`` / ``DELETE`` route is registered without overrides."""
        router = _crud_router()
        methods = {m for r in _api_routes(router) for m in r.methods}

        assert "PUT" not in methods
        assert "DELETE" not in methods

    def test_update_route_only_when_handler_passed(self) -> None:
        """Assert a ``PUT /{task_name}`` route appears only with an update handler."""
        router = _crud_router(update_handler=_synthetic_update_handler)
        route = _route_for(router, "/{task_name}", "PUT")

        assert route.methods == {"PUT"}

    def test_delete_route_only_when_handler_passed(self) -> None:
        """Assert a ``DELETE /{task_name}`` route appears only with a delete handler."""
        router = _crud_router(delete_handler=_synthetic_delete_handler)
        route = _route_for(router, "/{task_name}", "DELETE")

        assert route.methods == {"DELETE"}

    def test_create_route_pins_201(self) -> None:
        """Assert the create route sets ``status_code=201``."""
        route = _route_for(_crud_router(), "/", "POST")

        assert route.status_code == status.HTTP_201_CREATED

    def test_delete_route_pins_204(self) -> None:
        """Assert the delete route sets ``status_code=204``."""
        router = _crud_router(delete_handler=_synthetic_delete_handler)
        route = _route_for(router, "/{task_name}", "DELETE")

        assert route.status_code == status.HTTP_204_NO_CONTENT

    def test_derived_routes_declare_api_authenticated(self) -> None:
        """Assert every derived route redeclares ``IsApiAuthenticated``."""
        router = _crud_router(
            update_handler=_synthetic_update_handler,
            delete_handler=_synthetic_delete_handler,
        )

        for route in _api_routes(router):
            callables = {d.dependency for d in route.dependencies}
            assert get_api_authenticated_user in callables, route.path

    def test_derived_routes_emit_by_alias(self) -> None:
        """Assert list / detail / create pin ``response_model_by_alias=True``."""
        router = _crud_router()

        for path, method in (("/", "GET"), ("/{task_name}", "GET"), ("/", "POST")):
            assert _route_for(router, path, method).response_model_by_alias is True

    def test_list_response_model_is_list_of_builder_model(self) -> None:
        """Assert the list route's response model is ``list[<builder model>]``."""
        route = _route_for(_crud_router(), "/", "GET")

        assert route.response_model == list[_SyntheticTaskResponse]

    def test_detail_response_model_is_builder_model(self) -> None:
        """Assert the detail route's response model is the builder's model."""
        route = _route_for(_crud_router(), "/{task_name}", "GET")

        assert route.response_model is _SyntheticTaskResponse

    def test_create_response_model_defaults_to_builder_model(self) -> None:
        """Assert create reuses the list/detail model when no create builder is given."""
        route = _route_for(_crud_router(), "/", "POST")

        assert route.response_model is _SyntheticTaskResponse

    def test_create_response_model_distinct_when_create_builder_passed(self) -> None:
        """Assert a create builder gives create its own distinct response model."""
        router = _crud_router(create_response_builder=_build_synthetic_create_response)
        create_route = _route_for(router, "/", "POST")
        list_route = _route_for(router, "/", "GET")

        assert create_route.response_model is _SyntheticCreateResponse
        assert list_route.response_model == list[_SyntheticTaskResponse]

    def test_paginated_list_response_model_is_paginated(self) -> None:
        """Assert a pagination dep switches the list model to ``PaginatedResponse``."""
        router = _crud_router(pagination_dep=make_pagination_dep(max_limit=50))
        route = _route_for(router, "/", "GET")

        assert route.response_model == PaginatedResponse[_SyntheticTaskResponse]

    def test_configurable_detail_path_param_changes_route_path(self) -> None:
        """Assert ``detail_path_param`` renames the detail/create-sibling path."""
        router = _crud_router(get_task=_get_task_by_alt_param, detail_path_param="name")
        paths = {r.path for r in _api_routes(router)}

        assert "/{name}" in paths
        assert "/{task_name}" not in paths


class TestDeriveCrudRoutesList:
    """Exercise the non-paginated ``GET /`` list route over HTTP."""

    def test_list_200_with_alias_and_status(self, regular_user: CasdoorUser) -> None:
        """Assert list returns 200, alias-mapped keys, and batched statuses."""
        tasks_api = _make_tasks_api(
            list_items=[_task_dict("t1"), _task_dict("t2")],
            latest_statuses={"t1": TaskHistoryStatusEnum.SUCCESS.value, "t2": None},
        )
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.get(f"{_CRUD_BASE_URL}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["name"] for item in body] == ["t1", "t2"]
        assert body[0]["displayLabel"] == "T1"
        assert "display_label" not in body[0]
        assert body[0]["status"] == TaskHistoryStatusEnum.SUCCESS
        assert body[1]["status"] is None

    def test_list_empty_returns_empty_list_without_batch(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert an empty upstream page yields ``[]`` and skips the batch call."""
        tasks_api = _make_tasks_api(list_items=[])
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.get(f"{_CRUD_BASE_URL}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        tasks_api.post.assert_not_awaited()

    def test_list_degrades_to_none_when_batch_chunk_fails(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert a failed batch-status call degrades rows to ``status=None``."""
        tasks_api = _make_tasks_api(
            list_items=[_task_dict("t1")],
            batch_error=RuntimeError("batch endpoint down"),
        )
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.get(f"{_CRUD_BASE_URL}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body[0]["name"] == "t1"
        assert body[0]["status"] is None


class TestDeriveCrudRoutesPaginatedList:
    """Exercise the paginated ``GET /`` list route over HTTP."""

    def test_paginated_list_200_forwards_offset_limit(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert paginated list returns the envelope and forwards offset/limit."""
        tasks_api = _make_tasks_api(
            list_items=[_task_dict("t1"), _task_dict("t2")],
            list_total=_PAGE_TOTAL,
            latest_statuses={
                "t1": TaskHistoryStatusEnum.SUCCESS.value,
                "t2": TaskHistoryStatusEnum.FAILED.value,
            },
        )
        router = _crud_router(pagination_dep=make_pagination_dep(max_limit=50))
        client = _authed_crud_client(router, tasks_api, regular_user)

        response = client.get(
            f"{_CRUD_BASE_URL}/",
            params={"offset": _PAGE_OFFSET, "limit": _PAGE_LIMIT},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == _PAGE_TOTAL
        assert body["offset"] == _PAGE_OFFSET
        assert body["limit"] == _PAGE_LIMIT
        assert [item["name"] for item in body["items"]] == ["t1", "t2"]
        forwarded = tasks_api.get.await_args.kwargs["params"]
        assert forwarded["offset"] == _PAGE_OFFSET
        assert forwarded["limit"] == _PAGE_LIMIT

    def test_paginated_list_total_falls_back_to_page_length(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert ``total`` falls back to the page length when upstream omits it."""
        items = [_task_dict("t1"), _task_dict("t2")]
        tasks_api = _make_tasks_api(
            list_items=items,
            latest_statuses={"t1": None, "t2": None},
        )
        router = _crud_router(pagination_dep=make_pagination_dep(max_limit=50))
        client = _authed_crud_client(router, tasks_api, regular_user)

        response = client.get(f"{_CRUD_BASE_URL}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == len(items)


class TestDeriveCrudRoutesDetail:
    """Exercise the ``GET /{task_name}`` detail route over HTTP."""

    def test_detail_200(self, regular_user: CasdoorUser) -> None:
        """Assert detail returns 200 with the resolved task and latest status."""
        tasks_api = _make_tasks_api(
            detail_task=_task_dict("t1"),
            history_items=[{"status": TaskHistoryStatusEnum.SUCCESS.value}],
        )
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.get(f"{_CRUD_BASE_URL}/t1")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "t1"
        assert body["displayLabel"] == "T1"
        assert body["status"] == TaskHistoryStatusEnum.SUCCESS

    def test_detail_404_on_owner_mismatch(self, regular_user: CasdoorUser) -> None:
        """Assert detail 404s when the resolved task's owner mismatches."""
        tasks_api = _make_tasks_api(
            detail_task=_task_dict("t1", owner=TaskOwner.BACKUPS),
        )
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.get(f"{_CRUD_BASE_URL}/t1")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_detail_propagates_history_error(self, regular_user: CasdoorUser) -> None:
        """Assert an upstream history error surfaces, not swallowed to None."""
        tasks_api = _make_tasks_api(
            detail_task=_task_dict("t1"),
            history_error=HTTPConflictException(),
        )
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.get(f"{_CRUD_BASE_URL}/t1")

        assert response.status_code == status.HTTP_409_CONFLICT


class TestDeriveCrudRoutesCreate:
    """Exercise the ``POST /`` create route over HTTP."""

    def test_create_201(self, regular_user: CasdoorUser) -> None:
        """Assert a valid body returns 201 and posts the built payload upstream."""
        tasks_api = _make_tasks_api(created_task=_task_dict("new-task"))
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.post(f"{_CRUD_BASE_URL}/", json={"name": "new-task"})

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == "new-task"
        assert tasks_api.post.await_args.args[0] == "/"

    def test_create_422_on_invalid_body(self, regular_user: CasdoorUser) -> None:
        """Assert an invalid body 422s before the handler body posts anything."""
        tasks_api = _make_tasks_api(created_task=_task_dict("new-task"))
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.post(f"{_CRUD_BASE_URL}/", json={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        tasks_api.post.assert_not_awaited()

    def test_create_uses_distinct_response_model(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert a create builder produces its own response model on the wire."""
        tasks_api = _make_tasks_api(created_task=_task_dict("new-task"))
        router = _crud_router(create_response_builder=_build_synthetic_create_response)
        client = _authed_crud_client(router, tasks_api, regular_user)

        response = client.post(f"{_CRUD_BASE_URL}/", json={"name": "new-task"})

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body == {"name": "new-task", "created": True}
        assert "displayLabel" not in body

    def test_create_propagates_upstream_error(self, regular_user: CasdoorUser) -> None:
        """Assert an upstream create error surfaces rather than being swallowed."""
        tasks_api = _make_tasks_api(create_error=HTTPConflictException())
        client = _authed_crud_client(_crud_router(), tasks_api, regular_user)

        response = client.post(f"{_CRUD_BASE_URL}/", json={"name": "new-task"})

        assert response.status_code == status.HTTP_409_CONFLICT


class TestDeriveCrudRoutesUpdate:
    """Exercise the override-driven ``PUT /{task_name}`` update route."""

    def test_update_200(self, regular_user: CasdoorUser) -> None:
        """Assert the update override drives a 200 with conventions applied."""
        tasks_api = _make_tasks_api(detail_task=_task_dict("t1"))
        router = _crud_router(update_handler=_synthetic_update_handler)
        client = _authed_crud_client(router, tasks_api, regular_user)

        response = client.put(f"{_CRUD_BASE_URL}/t1")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["displayLabel"] == "T1"

    def test_update_404_on_owner_mismatch(self, regular_user: CasdoorUser) -> None:
        """Assert the update override 404s when the task owner mismatches."""
        tasks_api = _make_tasks_api(
            detail_task=_task_dict("t1", owner=TaskOwner.BACKUPS)
        )
        router = _crud_router(update_handler=_synthetic_update_handler)
        client = _authed_crud_client(router, tasks_api, regular_user)

        response = client.put(f"{_CRUD_BASE_URL}/t1")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeriveCrudRoutesDelete:
    """Exercise the override-driven ``DELETE /{task_name}`` delete route."""

    def test_delete_204(self, regular_user: CasdoorUser) -> None:
        """Assert the delete override returns 204 with no body and deletes upstream."""
        tasks_api = _make_tasks_api(detail_task=_task_dict("t1"))
        router = _crud_router(delete_handler=_synthetic_delete_handler)
        client = _authed_crud_client(router, tasks_api, regular_user)

        response = client.delete(f"{_CRUD_BASE_URL}/t1")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        tasks_api.delete.assert_awaited_once_with("/t1")

    def test_delete_404_on_owner_mismatch(self, regular_user: CasdoorUser) -> None:
        """Assert the delete override 404s when the task owner mismatches."""
        tasks_api = _make_tasks_api(
            detail_task=_task_dict("t1", owner=TaskOwner.BACKUPS)
        )
        router = _crud_router(delete_handler=_synthetic_delete_handler)
        client = _authed_crud_client(router, tasks_api, regular_user)

        response = client.delete(f"{_CRUD_BASE_URL}/t1")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeriveCrudRoutesConfigurablePathParam:
    """Exercise a non-default ``detail_path_param`` over HTTP."""

    def test_detail_resolves_with_custom_path_param(
        self, regular_user: CasdoorUser
    ) -> None:
        """Assert ``detail_path_param='name'`` resolves the detail route correctly."""
        tasks_api = _make_tasks_api(
            detail_task=_task_dict("t1"),
            history_items=[{"status": TaskHistoryStatusEnum.SUCCESS.value}],
        )
        router = _crud_router(get_task=_get_task_by_alt_param, detail_path_param="name")
        client = _authed_crud_client(router, tasks_api, regular_user)

        response = client.get(f"{_CRUD_BASE_URL}/t1")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "t1"


class TestDeriveCrudRoutesUnauthenticated:
    """Assert every derived route returns JSON 401 without an auth override."""

    @pytest.fixture
    def unauthed_crud_client(self) -> TestClient:
        """Yield an unauthed client (Tasks-API stubbed, no auth override)."""
        tasks_api = _make_tasks_api(
            list_items=[], detail_task=_task_dict("t1"), created_task=_task_dict("t1")
        )
        app = _mount_plugin_router(_crud_router(), _CRUD_PREFIX)
        app.dependency_overrides[get_tasks_api] = lambda: tasks_api
        return TestClient(app, raise_server_exceptions=False)

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/"),
            ("get", "/t1"),
            ("post", "/"),
            ("get", "/schema"),
        ],
    )
    def test_route_returns_401_json(
        self, unauthed_crud_client: TestClient, method: str, path: str
    ) -> None:
        """Assert each derived route returns a JSON 401 when unauthenticated."""
        response = unauthed_crud_client.request(
            method, f"{_CRUD_BASE_URL}{path}", follow_redirects=False
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")


class TestDeriveCrudRoutesOpenApi:
    """Assert the synthetic app's OpenAPI carries the no-op-preserving shape."""

    @pytest.fixture
    def openapi_spec(self, regular_user: CasdoorUser) -> dict:
        """Return the generated OpenAPI for a fully-featured synthetic CRUD app."""
        tasks_api = _make_tasks_api()
        router = _crud_router(
            create_response_builder=_build_synthetic_create_response,
            update_handler=_synthetic_update_handler,
            delete_handler=_synthetic_delete_handler,
        )
        client = _authed_crud_client(router, tasks_api, regular_user)
        return client.get("/openapi.json").json()

    def test_create_documents_201(self, openapi_spec: dict) -> None:
        """Assert the create operation documents a 201 response."""
        operation = openapi_spec["paths"][f"{_CRUD_BASE_URL}/"]["post"]

        assert "201" in operation["responses"]

    def test_delete_documents_204_under_task_name_path(
        self, openapi_spec: dict
    ) -> None:
        """Assert delete documents 204 and the path keeps the ``task_name`` param."""
        path_item = openapi_spec["paths"][f"{_CRUD_BASE_URL}/{{task_name}}"]

        assert "204" in path_item["delete"]["responses"]

    def test_list_response_serialises_by_alias(self, openapi_spec: dict) -> None:
        """Assert the list/detail response component exposes the aliased wire key."""
        component = next(
            v
            for k, v in openapi_spec["components"]["schemas"].items()
            if k.endswith("_SyntheticTaskResponse")
        )

        assert "displayLabel" in component["properties"]
        assert "display_label" not in component["properties"]
