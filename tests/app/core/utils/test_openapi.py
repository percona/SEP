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

"""Define tests for the app.core.utils.openapi module."""

from enum import Enum
from types import SimpleNamespace

import pytest

from app.core.utils.openapi import (
    generate_tag_prefixed_unique_id,
    merge_openapi_documents,
)


def _make_route(name, path, tags):
    """Build a minimal stand-in for a FastAPI ``APIRoute`` for ID generation.

    ``generate_unique_id`` only reads ``name``, ``path_format``, ``tags``, and
    ``methods`` — a ``SimpleNamespace`` with those attributes is enough and
    keeps the test free of a full FastAPI app setup.
    """
    return SimpleNamespace(
        name=name,
        path_format=path,
        tags=tags,
        methods={"GET"},
        operation_id=None,
    )


def test_untagged_route_falls_back_to_default_id():
    """Routes without tags get FastAPI's default operation ID."""
    route = _make_route("list_things", "/things", [])
    assert generate_tag_prefixed_unique_id(route) == "list_things_things_get"


def test_string_tag_is_prefixed():
    """A plain string tag is slugified and prefixed to the base ID."""
    route = _make_route("list_things", "/things", ["inventory"])
    assert generate_tag_prefixed_unique_id(route) == "inventory_list_things_things_get"


def test_enum_tag_uses_enum_value():
    """``Enum`` tags use their ``.value``, not ``repr``."""

    class TagEnum(str, Enum):
        SEP = "sep"

    route = _make_route("list_things", "/things", [TagEnum.SEP])
    assert generate_tag_prefixed_unique_id(route) == "sep_list_things_things_get"


def test_non_alphanumeric_tag_collapses_to_underscores():
    """Spaces, slashes, and punctuation in a tag collapse to a single ``_``."""
    route = _make_route("list_things", "/things", ["Periodic Tasks / jobs"])
    assert (
        generate_tag_prefixed_unique_id(route)
        == "periodic_tasks_jobs_list_things_things_get"
    )


def test_pure_punctuation_tag_falls_back_to_default():
    """A tag whose slug is empty after sanitization falls back to the default ID."""
    route = _make_route("list_things", "/things", ["---"])
    assert generate_tag_prefixed_unique_id(route) == "list_things_things_get"


def _spec(
    *,
    paths=None,
    tags=None,
    schemas=None,
    security_schemes=None,
    info=None,
    openapi_version="3.1.0",
):
    """Build a minimal OpenAPI document dict for merge tests."""
    components = {}
    if schemas is not None:
        components["schemas"] = schemas
    if security_schemes is not None:
        components["securitySchemes"] = security_schemes
    doc = {
        "openapi": openapi_version,
        "info": info or {"title": "primary", "version": "1.0.0"},
        "paths": paths or {},
    }
    if tags is not None:
        doc["tags"] = tags
    if components:
        doc["components"] = components
    return doc


def test_merge_disjoint_paths():
    """Two specs with no path overlap merge to the union of paths."""
    primary = _spec(paths={"/a": {"get": {"summary": "a"}}})
    secondary = _spec(paths={"/b": {"get": {"summary": "b"}}})
    merged = merge_openapi_documents(primary, secondary)
    assert set(merged["paths"]) == {"/a", "/b"}


def test_merge_tags_dedup_by_name():
    """Duplicate tag names are kept once, primary description wins."""
    primary = _spec(tags=[{"name": "shared", "description": "from primary"}])
    secondary = _spec(
        tags=[
            {"name": "shared", "description": "from secondary"},
            {"name": "extra"},
        ]
    )
    merged = merge_openapi_documents(primary, secondary)
    names = [t["name"] for t in merged["tags"]]
    assert names.count("shared") == 1
    assert "extra" in names
    shared = next(t for t in merged["tags"] if t["name"] == "shared")
    assert shared["description"] == "from primary"


def test_merge_schemas_identical_dedup():
    """Identical schemas under the same name are kept once, no rename."""
    same = {"type": "object", "properties": {"x": {"type": "integer"}}}
    primary = _spec(schemas={"Item": same})
    secondary = _spec(
        paths={
            "/b": {"get": {"responses": {"200": {"$ref": "#/components/schemas/Item"}}}}
        },
        schemas={"Item": same},
    )
    merged = merge_openapi_documents(primary, secondary)
    assert set(merged["components"]["schemas"]) == {"Item"}
    # secondary $ref untouched
    ref = merged["paths"]["/b"]["get"]["responses"]["200"]["$ref"]
    assert ref == "#/components/schemas/Item"


def test_merge_schemas_collision_renamed_and_refs_rewritten():
    """Same schema name + different bodies → second renamed, $refs rewritten."""
    primary = _spec(
        schemas={"Item": {"type": "object", "properties": {"x": {"type": "integer"}}}}
    )
    secondary = _spec(
        paths={
            "/b": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Item"}
                                }
                            }
                        }
                    }
                }
            }
        },
        schemas={
            "Item": {"type": "object", "properties": {"y": {"type": "string"}}},
            "Wrapper": {
                "type": "object",
                "properties": {"item": {"$ref": "#/components/schemas/Item"}},
            },
        },
    )
    merged = merge_openapi_documents(primary, secondary)
    schemas = merged["components"]["schemas"]
    assert "Item" in schemas
    assert "Item_sep" in schemas
    # primary kept
    assert schemas["Item"] == {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
    }
    # secondary path ref rewritten
    new_ref = merged["paths"]["/b"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert new_ref == "#/components/schemas/Item_sep"
    # secondary component internal ref rewritten
    assert (
        schemas["Wrapper"]["properties"]["item"]["$ref"]
        == "#/components/schemas/Item_sep"
    )


def test_merge_security_schemes_union():
    """Non-overlapping security schemes union; identical entries dedup."""
    common = {"type": "http", "scheme": "bearer"}
    primary = _spec(
        security_schemes={
            "Bearer": common,
            "ApiKey": {"type": "apiKey", "in": "header", "name": "X-A"},
        }
    )
    secondary = _spec(
        security_schemes={"Bearer": common, "OAuth2": {"type": "oauth2", "flows": {}}}
    )
    merged = merge_openapi_documents(primary, secondary)
    assert set(merged["components"]["securitySchemes"]) == {
        "Bearer",
        "ApiKey",
        "OAuth2",
    }


def test_merge_security_schemes_collision_renamed_and_refs_rewritten():
    """Conflicting securityScheme bodies → secondary renamed; refs rewritten."""
    primary = _spec(
        security_schemes={"Bearer": {"type": "http", "scheme": "bearer"}},
    )
    secondary_doc = _spec(
        paths={
            "/secured": {
                "get": {
                    "security": [{"Bearer": []}],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        security_schemes={
            "Bearer": {"type": "apiKey", "in": "header", "name": "X-A"},
        },
    )
    secondary_doc["security"] = [{"Bearer": []}]

    merged = merge_openapi_documents(primary, secondary_doc)

    schemes = merged["components"]["securitySchemes"]
    assert set(schemes) == {"Bearer", "Bearer_sep"}
    assert schemes["Bearer"] == {"type": "http", "scheme": "bearer"}
    assert schemes["Bearer_sep"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-A",
    }
    # Operation-level security on secondary path rewritten.
    op_sec = merged["paths"]["/secured"]["get"]["security"]
    assert op_sec == [{"Bearer_sep": []}]
    # Document-level security from secondary rewritten and merged.
    assert {"Bearer_sep": []} in merged.get("security", [])


def test_merge_security_schemes_rename_target_in_secondary_raises():
    """Secondary having both colliding ``Bearer`` and pre-existing ``Bearer_sep`` raises."""
    primary = _spec(security_schemes={"Bearer": {"type": "http", "scheme": "bearer"}})
    secondary = _spec(
        security_schemes={
            "Bearer": {"type": "apiKey", "in": "header", "name": "X-A"},
            "Bearer_sep": {"type": "oauth2", "flows": {}},
        }
    )
    with pytest.raises(ValueError, match="Bearer_sep"):
        merge_openapi_documents(primary, secondary)


def test_merge_security_schemes_rename_target_in_primary_raises():
    """Primary already having ``Bearer_sep`` when secondary's ``Bearer`` collides raises."""
    primary = _spec(
        security_schemes={
            "Bearer": {"type": "http", "scheme": "bearer"},
            "Bearer_sep": {"type": "oauth2", "flows": {}},
        }
    )
    secondary = _spec(
        security_schemes={"Bearer": {"type": "apiKey", "in": "header", "name": "X-A"}}
    )
    with pytest.raises(ValueError, match="Bearer_sep"):
        merge_openapi_documents(primary, secondary)


def test_merge_preserves_info_from_primary():
    """Top-level info and openapi version come from the primary spec."""
    primary = _spec(info={"title": "P", "version": "9.9"}, openapi_version="3.1.0")
    secondary = _spec(info={"title": "S", "version": "1.0"}, openapi_version="3.0.3")
    merged = merge_openapi_documents(primary, secondary)
    assert merged["info"] == {"title": "P", "version": "9.9"}
    assert merged["openapi"] == "3.1.0"


def test_merge_path_collision_raises():
    """Path collisions are errors — out of scope to rename paths."""
    primary = _spec(paths={"/x": {"get": {}}})
    secondary = _spec(paths={"/x": {"post": {}}})
    with pytest.raises(ValueError, match="/x"):
        merge_openapi_documents(primary, secondary)


def test_merge_schema_rename_target_in_secondary_raises():
    """Secondary having both colliding ``Item`` and pre-existing ``Item_sep`` raises."""
    primary = _spec(schemas={"Item": {"type": "string"}})
    secondary = _spec(
        schemas={
            "Item": {"type": "integer"},
            "Item_sep": {"type": "boolean"},
        }
    )
    with pytest.raises(ValueError, match="Item_sep"):
        merge_openapi_documents(primary, secondary)


def test_merge_schema_rename_target_in_primary_raises():
    """Primary already having ``Item_sep`` when secondary's ``Item`` needs rename raises."""
    primary = _spec(
        schemas={
            "Item": {"type": "string"},
            "Item_sep": {"type": "number"},
        }
    )
    secondary = _spec(schemas={"Item": {"type": "integer"}})
    with pytest.raises(ValueError, match="Item_sep"):
        merge_openapi_documents(primary, secondary)


def test_merge_does_not_mutate_inputs():
    """Inputs are deep-copied; merging does not change them."""
    primary = _spec(paths={"/a": {"get": {}}}, schemas={"S": {"type": "string"}})
    secondary = _spec(paths={"/b": {"get": {}}}, schemas={"S": {"type": "integer"}})
    p_snapshot = {
        "paths": dict(primary["paths"]),
        "schemas": dict(primary["components"]["schemas"]),
    }
    s_snapshot = {
        "paths": dict(secondary["paths"]),
        "schemas": dict(secondary["components"]["schemas"]),
    }
    merge_openapi_documents(primary, secondary)
    assert primary["paths"] == p_snapshot["paths"]
    assert primary["components"]["schemas"] == p_snapshot["schemas"]
    assert secondary["paths"] == s_snapshot["paths"]
    assert secondary["components"]["schemas"] == s_snapshot["schemas"]
