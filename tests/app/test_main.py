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


def test_sep_openapi_helper_is_hidden_from_core_spec(test_client):
    """The schema-helper route must not appear in the core ``/openapi.json``."""
    core_spec = test_client.get("/openapi.json").json()

    assert "/api/sep/openapi.json" not in core_spec.get("paths", {})
