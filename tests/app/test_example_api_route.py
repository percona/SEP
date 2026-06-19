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

"""Reference integration test for the Testing Trophy Integration layer.

Demonstrates the canonical pattern for integration tests in SEP:

- Uses ``fastapi.testclient.TestClient`` against the top-level composed
  application (``app.main:app``) so the mount points of the three sub-apps
  (``inventory_app``, ``tasks_app``, ``sep_app``) participate in the test.
- Verifies the seam between the mounted apps and the schema-helper routes —
  that is, the kind of contract the unit layer cannot see because it does
  not wire the routers together.
- No external services hit: Casdoor, Nomad, and PMM are mocked via the
  canonical stubs in ``tests/_stubs/`` (milestone M4 consolidates the
  existing per-plugin stubs there).

The ``integration`` marker is applied automatically by
``tests/app/conftest.py`` — no decoration on this file is required.

See ``docs/qa-architecture.md`` and ``docs/testing-guidelines.md`` for the
full layer contract.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Return a :class:`TestClient` for the composed top-level application."""
    return TestClient(app)


@pytest.mark.parametrize(
    "openapi_path",
    [
        "/api/sep/openapi.json",
        "/api/tasks/openapi.json",
        "/api/inventory/openapi.json",
    ],
)
def test_each_mounted_app_exposes_its_openapi_document(
    client: TestClient,
    openapi_path: str,
) -> None:
    """Every mounted sub-app must expose its own ``openapi.json``.

    This is the kind of property that only an integration test can defend:
    each sub-app declares the helper route independently, and the mount
    routing in ``app.main`` is what makes the three paths resolvable at the
    composed level.
    """
    response = client.get(openapi_path)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert {"openapi", "info", "paths"} <= body.keys()
    assert body["info"].get("title")
