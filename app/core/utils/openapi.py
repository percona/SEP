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

"""Define OpenAPI helpers for predictable operation IDs and spec merging."""

from __future__ import annotations

import copy
import re
from enum import Enum
from typing import Any, TYPE_CHECKING

from fastapi.utils import generate_unique_id as default_generate_unique_id

if TYPE_CHECKING:
    from fastapi.routing import APIRoute

_SCHEMA_REF_PREFIX = "#/components/schemas/"


def generate_tag_prefixed_unique_id(route: APIRoute) -> str:
    """Build a unique OpenAPI operation ID using the first tag plus FastAPI's default.

    Prefix FastAPI's generated ID with a slug from the first ``route.tags`` entry when
    tags exist to avoid collisions between similarly named handlers in different areas
    (for example ``restores_create`` under two plugins). Fall back to the stock
    FastAPI ID when the route has no tags.

    :param route: The FastAPI route being registered.
    :type route: fastapi.routing.APIRoute
    :return: A slug suitable for ``operationId`` in OpenAPI.
    :rtype: str
    """
    base = default_generate_unique_id(route)
    tags = route.tags
    if not tags:
        return base
    first = tags[0]
    label = first.value if isinstance(first, Enum) else str(first)
    prefix = re.sub(r"\W+", "_", label.strip()).strip("_").lower()
    if not prefix:
        return base
    return f"{prefix}_{base}"


def _rewrite_schema_refs(node: Any, rename_map: dict[str, str]) -> None:
    """Walk a JSON-like structure and rewrite ``$ref`` values per ``rename_map``.

    Mutates ``node`` in place. Only rewrites refs pointing at
    ``#/components/schemas/<name>`` where ``<name>`` is in ``rename_map``.

    :param node: Any nested dict/list found in an OpenAPI document.
    :type node: Any
    :param rename_map: Mapping of old schema name → new schema name.
    :type rename_map: dict[str, str]
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_SCHEMA_REF_PREFIX):
            old = ref[len(_SCHEMA_REF_PREFIX) :]
            if old in rename_map:
                node["$ref"] = _SCHEMA_REF_PREFIX + rename_map[old]
        for value in node.values():
            _rewrite_schema_refs(value, rename_map)
    elif isinstance(node, list):
        for item in node:
            _rewrite_schema_refs(item, rename_map)


def _merge_schemas(
    p_schemas: dict[str, Any],
    s_schemas: dict[str, Any],
    rename_map: dict[str, str],
) -> None:
    """Fold ``s_schemas`` into ``p_schemas`` honouring ``rename_map`` collisions."""
    for name, body in s_schemas.items():
        final_name = rename_map.get(name, name)
        if final_name in p_schemas and p_schemas[final_name] == body:
            continue
        p_schemas[final_name] = body


def _build_security_rename_map(
    p_security: dict[str, Any],
    s_security: dict[str, Any],
    secondary_suffix: str,
) -> dict[str, str]:
    """Return rename map for conflicting securityScheme names.

    Identical bodies dedup; differing bodies under the same name are renamed by
    appending ``secondary_suffix`` to the secondary entry. Raises if the renamed
    target collides with an existing name in either spec.
    """
    rename_map: dict[str, str] = {}
    for name, body in s_security.items():
        if name in p_security and p_security[name] != body:
            renamed = f"{name}{secondary_suffix}"
            if renamed in p_security or renamed in s_security:
                raise ValueError(
                    "OpenAPI securityScheme rename collision during merge: "
                    f"cannot rename {name!r} to {renamed!r}; target already exists"
                )
            rename_map[name] = renamed
    return rename_map


def _rewrite_security_refs(node: Any, rename_map: dict[str, str]) -> None:
    """Rewrite security scheme references in a JSON-like structure in place.

    Walks the structure looking for ``security`` keys whose value is a list of
    dicts mapping scheme name → scopes (per the OpenAPI security-requirement
    object). Each dict has its keys renamed per ``rename_map``.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "security" and isinstance(value, list):
                for req in value:
                    if not isinstance(req, dict):
                        continue
                    for old, new in rename_map.items():
                        if old in req:
                            req[new] = req.pop(old)
            else:
                _rewrite_security_refs(value, rename_map)
    elif isinstance(node, list):
        for item in node:
            _rewrite_security_refs(item, rename_map)


def _merge_security_schemes(
    p_components: dict[str, Any],
    s_security: dict[str, Any],
    rename_map: dict[str, str],
) -> None:
    """Fold ``s_security`` into ``p_components['securitySchemes']`` honouring renames."""
    if not s_security:
        return
    p_security = p_components.setdefault("securitySchemes", {})
    for name, body in s_security.items():
        final_name = rename_map.get(name, name)
        if final_name in p_security and p_security[final_name] == body:
            continue
        p_security[final_name] = body


def _merge_tags(p_tags: list[Any], s_tags: list[Any]) -> list[Any]:
    """Return a deduped list of tags, primary entries winning on name conflicts."""
    seen = {t["name"] for t in p_tags if isinstance(t, dict) and "name" in t}
    merged = list(p_tags)
    for tag in s_tags:
        if isinstance(tag, dict) and tag.get("name") in seen:
            continue
        if isinstance(tag, dict) and "name" in tag:
            seen.add(tag["name"])
        merged.append(tag)
    return merged


def _merge_top_level_security(p: dict[str, Any], s_security: Any) -> None:
    """Union the document-level ``security`` requirement list from secondary into primary."""
    if not s_security:
        return
    merged = list(p.get("security", []))
    for req in s_security:
        if req not in merged:
            merged.append(req)
    p["security"] = merged


def _prune_empty_components(p: dict[str, Any], p_components: dict[str, Any]) -> None:
    """Drop empty ``schemas`` / ``securitySchemes`` / ``components`` entries."""
    if not p_components.get("schemas"):
        p_components.pop("schemas", None)
    if "securitySchemes" in p_components and not p_components["securitySchemes"]:
        p_components.pop("securitySchemes")
    if not p_components:
        p.pop("components", None)


def merge_openapi_documents(
    primary: dict[str, Any],
    secondary: dict[str, Any],
    *,
    secondary_suffix: str = "_sep",
) -> dict[str, Any]:
    """Merge two OpenAPI documents into one, primary winning on conflicts.

    The merge is deterministic and never silently drops content:

    * ``paths`` are unioned; a path key present in both raises ``ValueError``.
    * ``tags`` are unioned, deduped by ``name`` (primary entry wins).
    * ``components.schemas``: identical entries dedup; on name collision with a
      different body, the secondary entry is renamed by appending
      ``secondary_suffix`` and every ``$ref`` in the secondary spec is rewritten
      to point at the renamed schema.
    * ``components.securitySchemes``: identical entries dedup; on name collision
      with a different body, the secondary entry is renamed by appending
      ``secondary_suffix`` and every security requirement in the secondary spec
      (operation-level and document-level ``security`` arrays) is rewritten to
      point at the renamed scheme.
    * Document-level ``security`` requirements from both specs are unioned
      (deduped by equality).
    * Top-level ``openapi`` version and ``info`` come from ``primary``.

    Inputs are deep-copied; neither argument is mutated.

    :param primary: The primary OpenAPI document (its ``info`` and ``openapi``
        version are preserved on the result).
    :type primary: dict[str, Any]
    :param secondary: The secondary OpenAPI document to fold into the primary.
    :type secondary: dict[str, Any]
    :param secondary_suffix: Suffix appended to a secondary schema name on
        collision with a different body. Defaults to ``"_sep"``.
    :type secondary_suffix: str
    :return: A new merged OpenAPI document.
    :rtype: dict[str, Any]
    :raises ValueError: If two paths collide, or if a schema/securityScheme
        rename target already exists in either spec.
    """
    p = copy.deepcopy(primary)
    s = copy.deepcopy(secondary)

    p_paths = p.setdefault("paths", {})
    s_paths = s.get("paths", {})
    collisions = set(p_paths) & set(s_paths)
    if collisions:
        raise ValueError(
            "OpenAPI path collision during merge: " + ", ".join(sorted(collisions))
        )

    # Build schema rename map first so we can rewrite refs in secondary before
    # merging paths/components into primary.
    p_components = p.setdefault("components", {})
    p_schemas = p_components.setdefault("schemas", {})
    s_components = s.get("components", {})
    s_schemas = s_components.get("schemas", {})

    rename_map: dict[str, str] = {}
    for name, body in s_schemas.items():
        if name in p_schemas and p_schemas[name] != body:
            renamed = f"{name}{secondary_suffix}"
            if renamed in p_schemas or renamed in s_schemas:
                raise ValueError(
                    "OpenAPI schema rename collision during merge: "
                    f"cannot rename {name!r} to {renamed!r}; target already exists"
                )
            rename_map[name] = renamed

    if rename_map:
        _rewrite_schema_refs(s_paths, rename_map)
        _rewrite_schema_refs(s_schemas, rename_map)

    s_security = s_components.get("securitySchemes", {})
    p_security = p_components.setdefault("securitySchemes", {}) if s_security else {}
    security_rename_map = _build_security_rename_map(
        p_security, s_security, secondary_suffix
    )
    if security_rename_map:
        _rewrite_security_refs(s_paths, security_rename_map)
        if "security" in s:
            _rewrite_security_refs({"security": s["security"]}, security_rename_map)

    p_paths.update(s_paths)
    _merge_schemas(p_schemas, s_schemas, rename_map)
    _merge_security_schemes(p_components, s_security, security_rename_map)
    _merge_top_level_security(p, s.get("security"))
    _prune_empty_components(p, p_components)

    p_tags = p.get("tags", [])
    s_tags = s.get("tags", [])
    if p_tags or s_tags:
        p["tags"] = _merge_tags(p_tags, s_tags)

    return p
