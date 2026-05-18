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

"""Define tests for the plugin discovery endpoint helpers (``/schema`` and ``/capabilities``)."""

from dataclasses import dataclass

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.inventory.models import ServiceTypeEnum
from app.models import CasdoorUser
from app.sep.deps import get_api_authenticated_user, IsApiAuthenticated
from app.sep.plugins.framework.api import capabilities_endpoint, schema_endpoint
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


def _build_composed_app(schema: PluginSchema, plugin_prefix: str) -> FastAPI:
    """Build a fresh FastAPI app whose composition mirrors production.

    Mirror ``app/sep/api/router.py`` exactly: plugin router → plugins router
    (``/plugins``) → api router (``/api`` with ``IsApiAuthenticated``) →
    ``FastAPI``. Return a fresh instance on every call so tests never touch
    the real ``sep_app``.

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
    plugins_router = APIRouter(prefix="/plugins")
    plugins_router.include_router(plugin_router, prefix=plugin_prefix)
    api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
    api_router.include_router(plugins_router)
    app = FastAPI()
    app.include_router(api_router)
    _register_login_placeholder(app)
    return app


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
    plugins_router = APIRouter(prefix="/plugins")
    plugins_router.include_router(plugin_router, prefix=plugin_prefix)
    api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
    api_router.include_router(plugins_router)
    app = FastAPI()
    app.include_router(api_router)
    _register_login_placeholder(app)
    return app


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
        handle. Async / DB-backed providers are explicitly out of scope
        for SEP-1133; the guard prevents the silent-500-at-first-request
        footgun and keeps the contract fail-fast.
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
        from fastapi import Depends

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
