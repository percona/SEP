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

"""Define tests for the top-level app.main module."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def test_client():
    """Create a test client for the top-level combined app."""
    return TestClient(app)


def test_sep_openapi_json_endpoint_returns_valid_schema(test_client):
    """``GET /api/sep/openapi.json`` returns the SEP sub-app's OpenAPI document.

    The endpoint is a schema-helper route — it is intentionally hidden from the core
    ``/openapi.json`` via ``include_in_schema=False`` but remains callable so the
    frontend codegen can pull each mounted app's spec independently.
    """
    response = test_client.get("/api/sep/openapi.json")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert {"openapi", "info", "paths"} <= body.keys()
    assert body["info"].get("title")


def test_sep_mounted_at_the_root_is_unaffected_by_the_prefix_parameter(test_client):
    """Serve the mounted SEP app from ``/`` while no URL prefix is configured.

    ``FastAPI.__call__`` overwrites the scope ``root_path`` a ``Mount`` sets, so
    only an unset prefix keeps the composite app's URLs anchored where it mounts
    SEP. The side-car runs ``app.sep.main`` directly and is the only deployment
    that configures one.
    """
    assert test_client.get("/health").status_code == status.HTTP_200_OK


def test_sep_openapi_helper_is_hidden_from_core_spec(test_client):
    """The schema-helper route must not appear in the core ``/openapi.json``."""
    core_spec = test_client.get("/openapi.json").json()

    assert "/api/sep/openapi.json" not in core_spec.get("paths", {})


def test_api_openapi_json_merges_core_and_sep(test_client):
    """``GET /api/openapi.json`` returns a merged spec containing core + sep paths."""
    response = test_client.get("/api/openapi.json")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert {"openapi", "info", "paths"} <= body.keys()
    paths = body["paths"]

    core_spec = test_client.get("/openapi.json").json()
    sep_spec = test_client.get("/api/sep/openapi.json").json()
    core_paths = set(core_spec.get("paths", {}))
    sep_paths = set(sep_spec.get("paths", {}))
    merged_paths = set(paths)

    assert core_paths, "core spec should expose at least one path"
    assert sep_paths, "sep spec should expose at least one path"
    assert core_paths & merged_paths, "merged spec missing core paths"
    assert sep_paths & merged_paths, "merged spec missing sep_app paths"


def test_api_docs_serves_swagger_ui(test_client):
    """``GET /api/docs`` returns Swagger UI HTML wired to ``/api/openapi.json``."""
    response = test_client.get("/api/docs")

    assert response.status_code == status.HTTP_200_OK
    assert "text/html" in response.headers.get("content-type", "")
    body = response.text
    assert "/api/openapi.json" in body
    assert "swagger-ui" in body.lower()


def test_top_level_docs_disabled(test_client):
    """The auto-generated ``/docs`` and ``/redoc`` pages are disabled."""
    assert test_client.get("/docs").status_code == status.HTTP_404_NOT_FOUND
    assert test_client.get("/redoc").status_code == status.HTTP_404_NOT_FOUND


def test_existing_core_openapi_json_unchanged(test_client):
    """``GET /openapi.json`` keeps its core-only shape."""
    response = test_client.get("/openapi.json")

    assert response.status_code == status.HTTP_200_OK
    spec = response.json()
    assert {"openapi", "info", "paths"} <= spec.keys()
    paths = spec.get("paths", {})
    assert "/api/openapi.json" not in paths
    assert "/api/docs" not in paths
    assert "/api/sep/openapi.json" not in paths


def test_existing_sep_openapi_json_unchanged(test_client):
    """``GET /api/sep/openapi.json`` still returns the sep_app spec."""
    response = test_client.get("/api/sep/openapi.json")

    assert response.status_code == status.HTTP_200_OK
    spec = response.json()
    assert {"openapi", "info", "paths"} <= spec.keys()
    assert spec.get("paths"), "sep_app spec should expose paths"


def test_api_openapi_json_is_cached(test_client, monkeypatch):
    """Repeated ``GET /api/openapi.json`` calls reuse the cached merged document."""
    from app import main as main_module

    # Warm the cache.
    test_client.get("/api/openapi.json")

    calls = {"n": 0}
    original = main_module.merge_openapi_documents

    def counting_merge(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(main_module, "merge_openapi_documents", counting_merge)

    for _ in range(3):
        response = test_client.get("/api/openapi.json")
        assert response.status_code == status.HTTP_200_OK

    assert calls["n"] == 0, "merge_openapi_documents should be cached after first call"
