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

"""Enforce the App framework's contract invariants as pure detector functions.

Each detector takes a single registry input plane — a schema wire payload, a
:class:`~app.sep.plugins.framework.apps.TaskExecutionApp`, the
:class:`~app.sep.plugins.framework.registry.AppRegistry`, or a merged OpenAPI
document — and returns a list of human-readable violation strings (empty when the
invariant holds), so a pytest suite can iterate ``get_app_registry()`` and assert
the framework's invariants mechanically instead of relying on reviewer memory.

The transitional :func:`~app.sep.plugins.framework.form_dsl.check_form_conformance`
drift check is re-exported here so the conformance suite imports every check from
one module; it lives in ``form_dsl`` because it cannot reference
``TaskExecutionApp`` (``apps`` imports ``form_dsl``, so the reverse import would
close an import cycle).
"""

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, TYPE_CHECKING

from app.sep.plugins.framework.form_dsl import (
    check_form_conformance,
    derive_form_sections,
)

if TYPE_CHECKING:
    from app.sep.plugins.framework.apps import TaskExecutionApp
    from app.sep.plugins.framework.base import BaseApp

__all__ = [
    "CAPABILITY_RENDERED_CONTROLS",
    "check_capability_route_consistency",
    "check_form_conformance",
    "check_no_duplicate_capability_control",
    "check_route_collisions",
    "check_routes_documented",
    "check_schema_derivation_succeeds",
    "check_view_fields_reference_real_fields",
]

CAPABILITY_RENDERED_CONTROLS: dict[str, str] = {"alert_on_fail": "alert_on_fail"}
"""Map a schema-side capability flag to the reserved form-field name the FE renders for it."""

_HTTP_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "options", "head", "trace"}
)


def _iter_form_fields(schema_payload: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """Yield every create-form field dict across root and entity forms.

    :param schema_payload: A plugin schema's wire payload.
    :yield: Each field dict from ``forms[].fields[]`` and
        ``entities[].forms[].fields[]``.
    """
    for section in schema_payload.get("forms") or ():
        yield from section.get("fields") or ()
    for entity in schema_payload.get("entities") or ():
        for section in entity.get("forms") or ():
            yield from section.get("fields") or ()


def check_no_duplicate_capability_control(
    schema_payload: Mapping[str, Any],
) -> list[str]:
    """Return violations where a capability-rendered control is also a form field.

    For each ``(capability, field)`` in :data:`CAPABILITY_RENDERED_CONTROLS`, flag
    the schema when the capability is enabled and a form field of that name also
    appears — the framework already renders the control from the capability, so
    the explicit field is a duplicate.

    :param schema_payload: A plugin schema's wire payload (the ``GET /schema``
        body, or ``app_schema.model_dump(by_alias=True, exclude_none=True)``).
    :return: One message per duplicated control; empty when none are found.
    """
    capabilities = schema_payload.get("capabilities") or {}
    field_names = {
        name
        for field in _iter_form_fields(schema_payload)
        if (name := field.get("name")) is not None
    }
    return [
        f"capability {cap!r} renders the {field!r} control, but the schema also "
        f"declares an explicit {field!r} form field (duplicate control)"
        for cap, field in CAPABILITY_RENDERED_CONTROLS.items()
        if capabilities.get(cap) and field in field_names
    ]


def check_capability_route_consistency(app: "TaskExecutionApp") -> list[str]:
    """Return violations where derived routes disagree with the capability flags.

    Assert each verb toggle on ``app.capabilities`` matches the presence of its
    route: ``create`` ↔ ``POST /``, ``execute`` ↔ ``POST /{param}/execute``,
    ``update`` ↔ ``PUT /{param}``, ``delete`` ↔ ``DELETE /{param}`` (``param`` is
    ``app.detail_path_param``). Catches an ``extra_routes`` override that
    reintroduces a route a disabled flag forbids.

    :param app: The migrated app whose derived router is inspected.
    :return: One message per flag/route disagreement; empty when consistent.
    """
    detail = f"/{{{app.detail_path_param}}}"
    expected = {
        "create": ("POST", "/"),
        "execute": ("POST", f"{detail}/execute"),
        "update": ("PUT", detail),
        "delete": ("DELETE", detail),
    }
    routes = app.api_router.routes if app.api_router is not None else []
    present = {
        (method, getattr(route, "path", ""))
        for route in routes
        for method in getattr(route, "methods", None) or ()
    }
    violations = []
    for verb, signature in expected.items():
        enabled = getattr(app.capabilities, verb)
        if enabled and signature not in present:
            violations.append(
                f"capability {verb!r} is enabled but route {signature[0]} "
                f"{signature[1]} is absent"
            )
        elif not enabled and signature in present:
            violations.append(
                f"capability {verb!r} is disabled but route {signature[0]} "
                f"{signature[1]} is present"
            )
    return violations


def _root_segment(path: str) -> str:
    """Return the leading field name of a dotted/indexed view path.

    :param path: A list-view column key or detail-view field path (for example
        ``"target.service"`` or ``"data.meta[0]"``).
    :return: The path's first segment, stripped of any ``[N]`` index.
    """
    return path.split(".", 1)[0].split("[", 1)[0]


def check_view_fields_reference_real_fields(app: "TaskExecutionApp") -> list[str]:
    """Return violations where a view path's root is not a response-model field.

    Validate the root segment (before the first ``.``, stripped of any ``[N]``) of
    every ``list_view`` column key and ``detail_view`` field path against
    ``app.response_model.model_fields``.

    :param app: The migrated app whose views are checked against its response model.
    :return: One message per unknown root segment; empty when all resolve.
    """
    response_fields = set(app.response_model.model_fields)
    views = app.views
    refs = []
    if views.list_view is not None:
        refs.extend(
            ("list_view column", column.key) for column in views.list_view.columns
        )
    if views.detail_view is not None:
        refs.extend(
            ("detail_view field", field.path)
            for section in views.detail_view.sections
            for field in section.fields
        )
    return [
        f"{kind} {ref!r} references {_root_segment(ref)!r}, absent from "
        f"{app.response_model.__name__}"
        for kind, ref in refs
        if _root_segment(ref) not in response_fields
    ]


def check_schema_derivation_succeeds(app: "TaskExecutionApp") -> list[str]:
    """Return a violation when the app's create model fails to derive a schema.

    Skip ``schema=`` passthrough apps (no create model). Otherwise derive the form
    sections and flag the app when derivation raises or yields no sections; a raise
    is converted to a message rather than propagated, so one broken definition
    cannot abort the whole conformance run.

    :param app: The migrated app whose ``create_model`` derivation is exercised.
    :return: A single-element list on failure; empty on success or skip.
    """
    if app.create_model is None:
        return []
    try:
        sections = derive_form_sections(app.create_model, app.views.layout)
    except Exception as exc:  # noqa: BLE001 - conformance must report, never raise
        return [f"schema derivation raised: {exc!r}"]
    if not sections:
        return ["schema derivation yielded no sections"]
    return []


def _iter_route_signatures(registry: Iterable["BaseApp"]) -> Iterator[tuple[str, str]]:
    """Yield the ``(mounted_path, method)`` signature of every registry route.

    :param registry: The apps to walk (the ``AppRegistry`` is one such iterable).
    :yield: Each ``("/api/plugins/{key}{path}", method)`` pair.
    """
    for app in registry:
        router = app.api_router
        if router is None:
            continue
        for route in router.routes:
            path = getattr(route, "path", None)
            if path is None:
                continue
            for method in getattr(route, "methods", None) or ():
                yield (f"/api/plugins/{app.key}{path}", method)


def check_route_collisions(registry: Iterable["BaseApp"]) -> list[str]:
    """Return violations where two registry routes share a ``(path, method)``.

    :param registry: The apps whose mounted route signatures are tallied (the
        ``AppRegistry`` is one such iterable).
    :return: One message per duplicated signature; empty when all are unique.
    """
    counts = Counter(_iter_route_signatures(registry))
    return [
        f"route collision: {method} {path} appears {count} times across the registry"
        for (path, method), count in sorted(counts.items())
        if count > 1
    ]


def check_routes_documented(openapi: Mapping[str, Any]) -> list[str]:
    """Return violations for operations carrying neither a summary nor a description.

    A floor, not an authored-docs gate: FastAPI auto-derives a ``summary`` from the
    route name, so this only flags the pathological operation that has neither.

    :param openapi: The merged plugin OpenAPI document.
    :return: One message per undocumented operation; empty when all carry one.
    """
    return [
        f"operation {method.upper()} {path} carries neither summary nor description"
        for path, item in (openapi.get("paths") or {}).items()
        for method, operation in item.items()
        if method in _HTTP_METHODS
        and isinstance(operation, Mapping)
        and not (operation.get("summary") or operation.get("description"))
    ]
