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

"""Share the scaffolding every om_bootstrap API test module needs."""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.requests import RemoteAPI
from app.extensions.apps.om_bootstrap.app import app as om_bootstrap_app
from app.extensions.deps import (
    get_current_user,
    get_session,
    get_tasks_client,
    IsApiAuthenticated,
)

#: The app's mount point, which every route in these tests hangs off.
BASE = "/api/apps/om_bootstrap"


def api_client(
    user: CasdoorUser,
    session: AsyncSession | None = None,
    tasks_client: RemoteAPI | None = None,
) -> TestClient:
    """Mount the app's API router behind the production auth guard.

    :param user: The authenticated user.
    :param session: The database session the routes should use; left to the
        real dependency when ``None``.
    :param tasks_client: The Tasks API client the routes should use; left to
        the real dependency when ``None``.
    :return: The client.
    """
    apps_router = APIRouter(prefix="/apps")
    apps_router.include_router(
        om_bootstrap_app.api_router, prefix=om_bootstrap_app.uri_path
    )
    api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
    api_router.include_router(apps_router)
    fastapi_app = FastAPI()
    fastapi_app.include_router(api_router)
    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    if session is not None:
        fastapi_app.dependency_overrides[get_session] = lambda: session
    if tasks_client is not None:
        fastapi_app.dependency_overrides[get_tasks_client] = lambda: tasks_client
    return TestClient(fastapi_app, raise_server_exceptions=False)
