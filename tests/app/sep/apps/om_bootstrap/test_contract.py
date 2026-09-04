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

"""Smoke-test the API-first surface of the OpenManager Bootstrap app.

A ``BaseApp`` exposes a declared ``api_router`` rather than the derived task
contract, so this mounts that router behind the production auth guard and asserts
``GET /schema`` and the sample list route both answer.
"""

from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.om_bootstrap.app import app as om_bootstrap_app
from app.sep.deps import get_current_user, IsApiAuthenticated

_BASE = "/api/apps/om_bootstrap"


def _client(user: CasdoorUser) -> TestClient:
    """Mount the app's API router behind the production auth guard."""
    apps_router = APIRouter(prefix="/apps")
    apps_router.include_router(
        om_bootstrap_app.api_router, prefix=om_bootstrap_app.uri_path
    )
    api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
    api_router.include_router(apps_router)
    fastapi_app = FastAPI()
    fastapi_app.include_router(api_router)
    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(fastapi_app, raise_server_exceptions=False)


def test_schema_200(regular_user: CasdoorUser) -> None:
    """Serve the plugin schema at ``GET /schema``."""
    response = _client(regular_user).get(f"{_BASE}/schema")

    assert response.status_code == status.HTTP_200_OK


def test_list_200(regular_user: CasdoorUser) -> None:
    """Return 200 from the sample ``GET /`` list route."""
    response = _client(regular_user).get(f"{_BASE}/")

    assert response.status_code == status.HTTP_200_OK
