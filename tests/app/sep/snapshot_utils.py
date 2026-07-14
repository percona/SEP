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

"""Provide shared helpers for the plugin OpenAPI and schema snapshot tests."""

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.utils.openapi import (
    generate_tag_prefixed_unique_id,
    namespaced_openapi,
)
from app.sep.api.router import api_router
from app.sep.apps.framework.registry import get_app_registry

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
PLUGIN_PREFIX = "/api/apps"
SCHEMA_REF_PREFIX = "#/components/schemas/"
UPDATE = os.environ.get("SEP_UPDATE_SNAPSHOTS") not in (None, "", "0", "false", "False")


def canonical_json(doc: Any) -> str:
    """Return deterministic JSON for ``doc``: sorted keys, 2-space indent, trailing newline.

    ``sort_keys`` neutralizes dict-key-order nondeterminism so the rendered
    bytes are stable across runs and Python versions.

    :param doc: The JSON-serializable object to render.
    :type doc: Any
    :return: Canonical UTF-8 JSON text with a single trailing newline.
    :rtype: str
    """
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def collect_schema_refs(node: Any, found: set[str]) -> None:
    """Collect schema names referenced via ``$ref`` under ``node`` into ``found``.

    Descend through dict values and list items, adding the bare schema name
    (the segment after ``#/components/schemas/``) of every matching ``$ref``
    to ``found``. ``found`` is mutated in place.

    :param node: An OpenAPI fragment (dict, list, or scalar) to scan.
    :type node: Any
    :param found: The accumulator set that collected schema names are added to.
    :type found: set[str]
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(SCHEMA_REF_PREFIX):
            found.add(ref[len(SCHEMA_REF_PREFIX) :])
        for value in node.values():
            collect_schema_refs(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_schema_refs(item, found)


def slice_openapi_subtree(
    openapi: dict[str, Any], prefix: str, child_prefixes: Iterable[str] = ()
) -> dict[str, Any]:
    """Return the ``{paths, components.schemas}`` subtree for one plugin ``prefix``.

    Select every path equal to ``prefix`` or nested under ``prefix + "/"``,
    then transitively resolve the schema ``$ref`` closure so the subtree's
    schema set is self-contained. The ``resolved`` set keeps the walk
    cycle-safe for self-referential or mutually-recursive models.

    Exclude any path owned by a more-specific nested sub-app listed in
    ``child_prefixes`` so a parent app whose URL prefix is a prefix of a scoped
    sub-app's does not over-capture it (``/api/apps/mysql_backups`` must not
    absorb the ``/api/apps/mysql_backups/restore/…`` routes that belong to
    the separately keyed ``mysql_backups/restore`` app).

    :param openapi: The full OpenAPI document to slice.
    :type openapi: dict[str, Any]
    :param prefix: The ``/api/apps/{key}`` path prefix to select.
    :type prefix: str
    :param child_prefixes: ``/api/apps/{key}`` prefixes of nested sub-apps to
        exclude from this slice.
    :type child_prefixes: Iterable[str]
    :return: A subtree holding the selected ``paths`` and their referenced schemas.
    :rtype: dict[str, Any]
    """
    children = tuple(child_prefixes)
    paths = {
        path: item
        for path, item in openapi.get("paths", {}).items()
        if (path == prefix or path.startswith(prefix + "/"))
        and not any(path == c or path.startswith(c + "/") for c in children)
    }
    all_schemas = openapi.get("components", {}).get("schemas", {})
    needed = set[str]()
    collect_schema_refs(paths, needed)
    resolved = set[str]()
    while needed - resolved:
        name = (needed - resolved).pop()
        resolved.add(name)
        if name in all_schemas:
            collect_schema_refs(all_schemas[name], needed)
    schemas = {
        name: all_schemas[name] for name in sorted(resolved) if name in all_schemas
    }
    return {"paths": paths, "components": {"schemas": schemas}}


def configured_plugin_keys() -> list[str]:
    """Return registry keys for plugins that expose a JSON API router, sorted.

    Read from the cached :func:`get_app_registry` (built once from
    ``sep_settings.APPS`` and never mutated) rather than ``sep_settings``
    directly, so a definition-based app whose JSON router is the derived
    ``api_router`` (no ``api_router_path``) is counted alongside legacy
    ``api_router_path`` plugins. Reading the registry keeps the inventory
    independent of sibling conftests that inject extra routers into the
    process-global ``sep_app``.

    :return: The sorted list of plugin keys exposing an API router.
    :rtype: list[str]
    """
    return sorted(app.key for app in get_app_registry() if app.api_router is not None)


def build_plugins_openapi() -> dict[str, Any]:
    """Build the OpenAPI document for the configured ``/api/apps`` surface.

    Mount the config-built ``api_router`` on a throwaway ``FastAPI`` app rather
    than reading the process-global ``sep_app``. Sibling conftests mutate
    ``sep_app`` at import time (``backup_pg`` injects routers), which both
    freezes ``sep_app``'s cached schema for other tests and perturbs shared
    ``components/schemas`` names — so a snapshot taken from it would depend on
    test-suite composition. ``api_router`` is built once from
    ``sep_settings.APPS`` and never mutated, so its schema is deterministic.
    ``generate_tag_prefixed_unique_id`` matches the ``operationId`` scheme that
    ``create_app`` installs on ``sep_app``.

    :return: The OpenAPI document for exactly the configured API routers.
    :rtype: dict[str, Any]
    """
    app = FastAPI(generate_unique_id_function=generate_tag_prefixed_unique_id)
    app.include_router(api_router)
    return namespaced_openapi(app)


def discover_schema_paths(openapi: dict[str, Any], allowed_keys: set[str]) -> list[str]:
    """Return parameterless ``GET …/schema`` paths under a configured plugin prefix.

    Restrict matches to ``allowed_keys`` so routers injected into the global
    app by sibling conftests are ignored, and require the ``get`` operation to
    declare no parameters — that excludes parameterized, data-dependent schema
    routes (snippets' per-snippet ``/snippet/schema``) and leaves only the
    ``schema_endpoint``-registered discovery routes.

    :param openapi: The full OpenAPI document to scan.
    :type openapi: dict[str, Any]
    :param allowed_keys: The configured plugin keys whose schema routes are eligible.
    :type allowed_keys: set[str]
    :return: The sorted list of matching schema paths.
    :rtype: list[str]
    """
    paths = []
    for path, item in openapi.get("paths", {}).items():
        if not (path.startswith(PLUGIN_PREFIX + "/") and path.endswith("/schema")):
            continue
        key = path[len(PLUGIN_PREFIX) + 1 :].split("/", 1)[0]
        get_op = item.get("get")
        if key in allowed_keys and get_op is not None and not get_op.get("parameters"):
            paths.append(path)
    return sorted(paths)


def schema_path_to_slug(path: str) -> str:
    """Return the golden-file slug for a schema ``path``.

    Strip the ``/api/apps/`` prefix and ``/schema`` suffix, then replace
    inner slashes with ``__`` so a nested route maps to a flat filename
    (``/api/apps/backup_mongo/restore/schema`` -> ``backup_mongo__restore``).

    :param path: The discovered ``…/schema`` path.
    :type path: str
    :return: The filesystem-safe slug for the path's golden file.
    :rtype: str
    """
    inner = path[len(PLUGIN_PREFIX) + 1 : -len("/schema")]
    return inner.replace("/", "__")


def assert_or_update(golden: Path, content: str) -> None:
    """Compare ``content`` to ``golden`` byte-for-byte, or rewrite it in update mode.

    In update mode (``SEP_UPDATE_SNAPSHOTS`` set to a truthy value) write
    ``content`` to ``golden`` and skip the test; otherwise assert the golden
    exists and matches ``content``, pointing the reader at the regeneration
    command on failure.

    :param golden: The golden file path to compare against or rewrite.
    :type golden: Path
    :param content: The freshly serialized snapshot text.
    :type content: str
    :raises AssertionError: When ``content`` differs from the committed golden,
        or the golden is missing in compare mode.
    """
    if UPDATE:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(content, encoding="utf-8")
        pytest.skip(f"snapshot updated: {golden.relative_to(SNAPSHOTS_DIR.parent)}")
    if not golden.exists():
        raise AssertionError(
            f"missing golden {golden}; regenerate with `make regen-specs`"
        )
    if content != golden.read_text(encoding="utf-8"):
        raise AssertionError(
            f"OpenAPI/schema drift vs {golden.name}; if intentional, regenerate "
            f"with `make regen-specs` and review the diff in the PR"
        )


def assert_golden_set_matches(subdir: str, expected_slugs: set[str]) -> None:
    """Assert the committed goldens under ``snapshots/<subdir>`` match the expected set.

    Compare the on-disk golden stems to ``expected_slugs`` and fail with the
    missing/orphaned difference so an added or removed endpoint surfaces as a
    completeness failure rather than silent drift.

    :param subdir: The snapshots subdirectory to inspect (``openapi`` or ``schema``).
    :type subdir: str
    :param expected_slugs: The slugs that should have a committed golden.
    :type expected_slugs: set[str]
    :raises AssertionError: When the on-disk golden set differs from ``expected_slugs``.
    """
    on_disk = {p.stem for p in (SNAPSHOTS_DIR / subdir).glob("*.json")}
    if on_disk != expected_slugs:
        raise AssertionError(
            f"snapshot set drift in snapshots/{subdir}: "
            f"missing={expected_slugs - on_disk}, orphaned={on_disk - expected_slugs}; "
            f"regenerate with SEP_UPDATE_SNAPSHOTS=1"
        )
