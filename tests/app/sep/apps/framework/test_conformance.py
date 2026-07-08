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

"""Test the App framework conformance detectors and the registry conformance suite.

Three layers:

* **Per-detector unit tests** drive each pure detector with small synthetic
  dicts / models, mirroring ``test_form_dsl_conformance.py``.
* **Synthetic ``TaskExecutionApp``** exercises the migrated-only and hard
  detectors against a real definition (clean plus deliberately-broken variants),
  so the logic is covered before any plugin is migrated.
* **Registry suite** iterates ``get_app_registry()`` and asserts the
  framework-contract checks hold over the live registry — the no-duplicate-control
  rule is what catches the duplicate ``alert_on_fail`` form field.
"""

import logging
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import APIRouter, status
from pydantic import BaseModel

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.framework.apps import AppCapabilities, TaskExecutionApp, Views
from app.sep.apps.framework.conformance import (
    CAPABILITY_RENDERED_CONTROLS,
    check_capability_route_consistency,
    check_form_conformance,
    check_no_duplicate_capability_control,
    check_route_collisions,
    check_routes_documented,
    check_schema_derivation_succeeds,
    check_view_fields_reference_real_fields,
)
from app.sep.apps.framework.form_dsl import (
    AppFormModel,
    derive_app_schema,
    FormLayout,
    SectionLayout,
    Ui,
)
from app.sep.apps.framework.form_dsl import (
    check_form_conformance as _form_dsl_check_form_conformance,
)
from app.sep.apps.framework.registry import get_app_registry
from app.sep.apps.framework.schema import (
    Capabilities,
    Column,
    DetailField,
    DetailSection,
    DetailView,
    ListView,
)
from app.sep.apps.framework.spec import ResolvedEntities, RunCommandSpec
from app.tasks.models import TaskHistoryStatusEnum, TaskOwner
from tests.app.sep import snapshot_utils as su
from tests.app.sep.apps.framework.contract_suite import build_contract_client
from tests.app.sep.apps.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    synth_app,
)

_OWNER = TaskOwner.ARCHIVER
_LAYOUT = FormLayout(sections=(SectionLayout(key="main", title="Main"),))
_LIST_VIEW = ListView(columns=[Column(key="name", label="Name")])
_DETAIL_VIEW = DetailView(
    sections=[
        DetailSection(title="Exec", fields=[DetailField(path="status", label="Status")])
    ]
)


class _CleanForm(AppFormModel):
    """Represent a synthetic create model with a task_name and an alert toggle."""

    task_name: Annotated[str, Ui(label="Name", section="main")]
    alert_on_fail: Annotated[bool, Ui(label="Alert", section="main")] = False


class _CleanResponse(BaseModel):
    """Represent the synthetic list/detail response model."""

    name: str
    status: TaskHistoryStatusEnum | None = None


class _DetailResponse(_CleanResponse):
    """Represent a detail response richer than the list response."""

    host: str | None = None


def _detail_builder(task: object, *, status: object = None) -> _DetailResponse:
    """Return a synthetic detail response; the detector never invokes it."""
    return _DetailResponse(name="x")


class _BadSectionForm(AppFormModel):
    """Represent a create model whose field names a section absent from the layout."""

    task_name: Annotated[str, Ui(label="Name", section="ghost")]


def _spec_builder(form: AppFormModel, resolved: ResolvedEntities) -> RunCommandSpec:
    """Return a trivial run-command spec; the detector tests never invoke it."""
    return RunCommandSpec(command="synth-cmd", args="")


def _build_app(**overrides: object) -> TaskExecutionApp:
    """Build a minimal create-model ``TaskExecutionApp`` with sane defaults."""
    kwargs = {
        "name": "synthetic",
        "uri_path": "/synthetic",
        "owner": _OWNER,
        "create_model": _CleanForm,
        "response_model": _CleanResponse,
        "views": Views(layout=_LAYOUT, list_view=_LIST_VIEW, detail_view=_DETAIL_VIEW),
        "task_spec_builder": _spec_builder,
        "capabilities": AppCapabilities(execute=False),
    }
    kwargs.update(overrides)
    return TaskExecutionApp(**kwargs)


def _post_root_router() -> APIRouter:
    """Return an extra router that reintroduces a ``POST /`` create route."""
    router = APIRouter()

    @router.post("/")
    async def _create() -> dict:
        return {}

    return router


def _derived_payload(*, capabilities: Capabilities) -> dict:
    """Return the wire payload of a schema derived from ``_CleanForm``."""
    schema = derive_app_schema(
        _CleanForm,
        _LAYOUT,
        name="synthetic",
        display_name="Synthetic",
        capabilities=capabilities,
        list_view=_LIST_VIEW,
    )
    return schema.model_dump(mode="json", by_alias=True, exclude_none=True)


# --- check_no_duplicate_capability_control ------------------------------------


def test_no_duplicate_control_silent_when_capability_off():
    """Assert the rule stays silent when the rendered capability is disabled."""
    payload = {
        "capabilities": {"alert_on_fail": False},
        "forms": [{"fields": [{"name": "alert_on_fail"}]}],
    }
    assert check_no_duplicate_capability_control(payload) == []


def test_no_duplicate_control_silent_when_field_absent():
    """Assert the rule stays silent when no matching form field exists."""
    payload = {
        "capabilities": {"alert_on_fail": True},
        "forms": [{"fields": [{"name": "other"}]}],
    }
    assert check_no_duplicate_capability_control(payload) == []


def test_no_duplicate_control_fires_on_capability_plus_field():
    """Assert the rule fires when an enabled capability duplicates a form field."""
    payload = {
        "capabilities": {"alert_on_fail": True},
        "forms": [{"fields": [{"name": "alert_on_fail"}]}],
    }
    assert any(
        "alert_on_fail" in w for w in check_no_duplicate_capability_control(payload)
    )


def test_no_duplicate_control_treats_missing_capabilities_as_empty():
    """Assert an absent ``capabilities`` key yields no violations."""
    payload = {"forms": [{"fields": [{"name": "alert_on_fail"}]}]}
    assert check_no_duplicate_capability_control(payload) == []


def test_no_duplicate_control_traverses_entity_forms():
    """Assert the field scan spans ``entities[].forms[].fields[]``."""
    payload = {
        "capabilities": {"alert_on_fail": True},
        "entities": [{"forms": [{"fields": [{"name": "alert_on_fail"}]}]}],
    }
    assert any(
        "alert_on_fail" in w for w in check_no_duplicate_capability_control(payload)
    )


def test_no_duplicate_control_silent_for_unrelated_entity_field():
    """Assert an entity form without the reserved field yields no violations."""
    payload = {
        "capabilities": {"alert_on_fail": True},
        "entities": [{"forms": [{"fields": [{"name": "x"}]}]}],
    }
    assert check_no_duplicate_capability_control(payload) == []


def test_no_duplicate_control_fires_on_real_derived_schema():
    """Assert a real derived schema with the capability + field trips the rule."""
    payload = _derived_payload(capabilities=Capabilities(alert_on_fail=True))
    assert check_no_duplicate_capability_control(payload) != []


def test_no_duplicate_control_silent_on_real_derived_schema_without_capability():
    """Assert the same form is clean when the capability is off."""
    payload = _derived_payload(capabilities=Capabilities(alert_on_fail=False))
    assert check_no_duplicate_capability_control(payload) == []


class _HiddenControlForm(AppFormModel):
    """Represent a create model that inherits the excluded capability-rendered control."""

    task_name: Annotated[str, Ui(label="Name", section="main")]


def test_no_duplicate_control_silent_when_control_excluded_from_schema():
    """Assert excluding the capability-rendered field clears the duplicate violation."""
    schema = derive_app_schema(
        _HiddenControlForm,
        _LAYOUT,
        name="synthetic",
        display_name="Synthetic",
        capabilities=Capabilities(alert_on_fail=True),
        list_view=_LIST_VIEW,
    )
    payload = schema.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert check_no_duplicate_capability_control(payload) == []


def test_capability_rendered_controls_maps_alert_on_fail():
    """Assert the registry only reserves the ``alert_on_fail`` control today."""
    assert CAPABILITY_RENDERED_CONTROLS == {"alert_on_fail": "alert_on_fail"}
    assert set(CAPABILITY_RENDERED_CONTROLS) <= set(Capabilities.model_fields)


def test_no_duplicate_control_silent_with_response_extras_builder(
    regular_user: CasdoorUser,
) -> None:
    """Assert a response_builder injecting extras never reintroduces a form control.

    The synth app's response_builder injects response-plane fields (``service_type``,
    a remapped ``created_by``) — a plane independent of the schema's form fields.
    With the ``alert_on_fail`` capability enabled and its control excluded from the
    form, the served schema must still carry no duplicate control.
    """
    app_def = synth_app()
    client = build_contract_client(
        app_def,
        user=regular_user,
        tasks_api=MockTaskAPI(),
        inventory_api=MockInventoryAPI(),
    )

    payload = client.get(f"/api/apps{app_def.uri_path}/schema").json()

    assert app_def.response_builder is not None
    assert check_no_duplicate_capability_control(payload) == []


class _ExecuteWrite(BaseModel):
    """Represent a synthetic execute request body."""


class _ExecuteResponse(BaseModel):
    """Represent a synthetic execute response keyed by task name and id."""

    task_name: str
    task_id: int


async def _get_by_cluster(cluster_name: str) -> object:
    """Resolve a task by a non-default ``cluster_name`` detail path parameter."""
    raise NotImplementedError


# --- check_capability_route_consistency ---------------------------------------


def test_capability_route_consistency_clean_app():
    """Assert a well-formed app's routes match its capability flags."""
    assert check_capability_route_consistency(_build_app()) == []


def test_capability_route_consistency_allows_custom_extra_route():
    """Assert a custom ``extra_routes`` route for a disabled flag is exempt.

    A hybrid app keeps a verb custom (capability off, route mounted via
    ``extra_routes``); that explicit escape hatch is not a violation — only a
    leaked *derived* route would be.
    """
    app = _build_app(
        capabilities=AppCapabilities(create=False, execute=False),
        extra_routes=(_post_root_router(),),
    )
    assert check_capability_route_consistency(app) == []


def test_capability_route_consistency_flags_leak_alongside_custom():
    """Assert a leaked derived route is caught even beside a custom handler.

    A disabled verb with a legitimate custom ``extra_routes`` handler is exempt,
    but a derived route that leaks onto the same ``(method, path)`` must still be
    reported. The detector compares route counts, so the extra ``POST /``
    occurrence in ``api_router`` beyond the ``extra_routes`` count surfaces
    rather than being masked by set membership.
    """
    app = _build_app(
        capabilities=AppCapabilities(create=False, execute=False),
        extra_routes=(_post_root_router(),),
    )
    app.api_router.routes.extend(_post_root_router().routes)
    violations = check_capability_route_consistency(app)
    assert any("create" in v and "POST" in v for v in violations)


def test_capability_route_consistency_execute_ignores_custom_detail_path_param():
    """Assert execute matches /{task_name}/execute under a custom detail path param.

    The CRUD detail/update/delete routes adopt ``detail_path_param``, but the
    derived execute route is always ``POST /{task_name}/execute``; the detector
    must not report a false absence when the two path parameters diverge.
    """
    app = _build_app(
        detail_path_param="cluster_name",
        get_task=_get_by_cluster,
        capabilities=AppCapabilities(execute=True),
        execute_write_model=_ExecuteWrite,
        execute_response_model=_ExecuteResponse,
    )
    assert check_capability_route_consistency(app) == []


# --- check_view_fields_reference_real_fields ----------------------------------


def test_view_fields_clean_app():
    """Assert columns and detail fields that resolve to real fields pass."""
    assert check_view_fields_reference_real_fields(_build_app()) == []


def test_view_fields_exempts_data_detail_paths():
    """Assert a detail path rooted at the opaque ``data`` dict is exempt.

    List-column keys are enforced at ``TaskExecutionApp`` construction now; the
    detector only checks detail-view paths and leaves ``data.*`` sub-paths
    free-form because ``data`` is an opaque task-payload dict.
    """
    app = _build_app(
        views=Views(
            layout=_LAYOUT,
            list_view=_LIST_VIEW,
            detail_view=DetailView(
                sections=[
                    DetailSection(
                        title="X",
                        fields=[DetailField(path="data.meta.command", label="C")],
                    )
                ]
            ),
        )
    )
    assert check_view_fields_reference_real_fields(app) == []


def test_view_fields_flags_unknown_detail_path():
    """Assert a detail path whose root segment is not a response field fires."""
    app = _build_app(
        views=Views(
            layout=_LAYOUT,
            list_view=_LIST_VIEW,
            detail_view=DetailView(
                sections=[
                    DetailSection(
                        title="X", fields=[DetailField(path="ghost.sub", label="G")]
                    )
                ]
            ),
        )
    )
    assert any("ghost" in w for w in check_view_fields_reference_real_fields(app))


def test_view_fields_validates_root_segment_only():
    """Assert a dotted path resolves on its root segment, not the full path."""
    app = _build_app(
        views=Views(
            layout=_LAYOUT,
            list_view=_LIST_VIEW,
            detail_view=DetailView(
                sections=[
                    DetailSection(
                        title="X", fields=[DetailField(path="status.sub", label="S")]
                    )
                ]
            ),
        )
    )
    assert check_view_fields_reference_real_fields(app) == []


def test_view_fields_resolve_against_detail_response_model():
    """Resolve a detail-only field against the richer detail model."""
    app = _build_app(
        detail_response_builder=_detail_builder,
        detail_response_model=_DetailResponse,
        views=Views(
            layout=_LAYOUT,
            list_view=_LIST_VIEW,
            detail_view=DetailView(
                sections=[
                    DetailSection(
                        title="X", fields=[DetailField(path="host", label="H")]
                    )
                ]
            ),
        ),
    )

    assert check_view_fields_reference_real_fields(app) == []


# --- check_schema_derivation_succeeds -----------------------------------------


def test_schema_derivation_succeeds_clean_app():
    """Assert a derivable create model yields no violation."""
    assert check_schema_derivation_succeeds(_build_app()) == []


def test_schema_derivation_flags_a_raise():
    """Assert a derivation error becomes a violation instead of propagating."""
    stub = SimpleNamespace(
        create_model=_BadSectionForm, views=SimpleNamespace(layout=_LAYOUT)
    )
    warnings = check_schema_derivation_succeeds(stub)
    assert warnings
    assert "deriv" in warnings[0].lower()


def test_schema_derivation_skips_passthrough_app():
    """Assert a ``schema=`` passthrough app (no create model) is skipped."""
    stub = SimpleNamespace(create_model=None, views=SimpleNamespace(layout=None))
    assert check_schema_derivation_succeeds(stub) == []


# --- check_route_collisions ---------------------------------------------------


def test_route_collisions_flags_same_key_and_path():
    """Assert two apps sharing a key collide on every shared route."""
    apps = [
        _build_app().model_copy(update={"key": "dup"}),
        _build_app().model_copy(update={"key": "dup"}),
    ]
    assert check_route_collisions(apps) != []


def test_route_collisions_silent_across_distinct_keys():
    """Assert apps mounted under distinct keys never collide."""
    apps = [
        _build_app().model_copy(update={"key": "a"}),
        _build_app().model_copy(update={"key": "b"}),
    ]
    assert check_route_collisions(apps) == []


# --- check_routes_documented --------------------------------------------------


def test_routes_documented_flags_bare_operation():
    """Assert an operation with neither summary nor description is flagged."""
    assert check_routes_documented({"paths": {"/x": {"get": {}}}}) != []


def test_routes_documented_silent_with_summary():
    """Assert a summary-only operation passes the floor."""
    assert (
        check_routes_documented({"paths": {"/x": {"get": {"summary": "Do X"}}}}) == []
    )


def test_routes_documented_silent_with_description():
    """Assert a description-only operation passes the floor."""
    assert (
        check_routes_documented({"paths": {"/x": {"get": {"description": "Does X"}}}})
        == []
    )


def test_routes_documented_ignores_non_operation_keys():
    """Assert path-level keys (``parameters``) are not treated as operations."""
    openapi = {"paths": {"/x": {"parameters": [], "get": {"summary": "ok"}}}}
    assert check_routes_documented(openapi) == []


# --- transitional re-export ---------------------------------------------------


def test_check_form_conformance_is_reexported():
    """Assert the transitional drift check is reused, not reimplemented."""
    assert check_form_conformance is _form_dsl_check_form_conformance


# --- registry suite -----------------------------------------------------------

OPENAPI = su.build_plugins_openapi()
_SCHEMA_PATHS = set(su.discover_schema_paths(OPENAPI, set(su.configured_plugin_keys())))
_REGISTRY = get_app_registry()
_APPS = list(_REGISTRY)


def _schema_payload(app, test_client) -> dict | None:
    """Return the app's schema wire payload, or ``None`` when it exposes none."""
    if app.app_schema is not None:
        return app.app_schema.model_dump(mode="json", by_alias=True, exclude_none=True)
    path = f"{su.PLUGIN_PREFIX}/{app.key}/schema"
    if path in _SCHEMA_PATHS:
        response = test_client.get(path)
        assert response.status_code == status.HTTP_200_OK
        return response.json()
    return None


@pytest.mark.parametrize("registry_app", _APPS, ids=lambda app: app.key)
def test_registry_app_has_no_duplicate_capability_control(registry_app, test_client):
    """Assert no registry app declares a form field a capability already renders."""
    payload = _schema_payload(registry_app, test_client)
    if payload is None:
        pytest.skip(f"{registry_app.key} exposes no schema payload")
    assert check_no_duplicate_capability_control(payload) == []


@pytest.mark.parametrize("registry_app", _APPS, ids=lambda app: app.key)
def test_registry_migrated_app_structural_checks(registry_app):
    """Assert each migrated ``TaskExecutionApp`` satisfies the structural checks."""
    if not isinstance(registry_app, TaskExecutionApp):
        pytest.skip(f"{registry_app.key} is not a migrated TaskExecutionApp")
    assert check_capability_route_consistency(registry_app) == []
    assert check_view_fields_reference_real_fields(registry_app) == []
    assert check_schema_derivation_succeeds(registry_app) == []


def test_registry_has_no_route_collisions():
    """Assert no two registry routes share a ``(path, method)`` signature."""
    assert check_route_collisions(_REGISTRY) == []


def test_registry_openapi_builds():
    """Assert the merged plugin OpenAPI document builds with paths."""
    assert OPENAPI.get("paths")


def test_registry_routes_are_documented():
    """Assert every plugin operation carries a summary or description floor."""
    assert check_routes_documented(OPENAPI) == []


def test_registry_transitional_check_runs_at_warning_level(caplog):
    """Run the reused drift check over any app exposing both a model and a schema.

    Warning-level: drift is logged, never failed. Dormant over today's all-legacy
    registry (no app carries a discoverable create model alongside a hand-written
    schema), and auto-activates when a migrated app first exposes both — at which
    point the dormancy assertion trips so the wiring gets a deliberate review.
    """
    activated = []
    with caplog.at_level(logging.WARNING):
        for app in _APPS:
            model = getattr(app, "create_model", None)
            if model is None or app.app_schema is None:
                continue
            activated.append(app.key)
            for warning in check_form_conformance(model, app.app_schema):
                logging.getLogger(__name__).warning(
                    "transitional drift in %s: %s", app.key, warning
                )
    assert activated == []
