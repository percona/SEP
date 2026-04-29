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

"""Tests for the framework's Jinja2 route deprecation marker."""

from unittest.mock import patch

from fastapi import APIRouter, Depends, FastAPI, status
from fastapi.testclient import TestClient

from app.sep.plugins.framework.deprecation import mark_jinja2_route_deprecated


def _build_app_with_deprecated_router() -> FastAPI:
    router = APIRouter(dependencies=[Depends(mark_jinja2_route_deprecated)])

    @router.get("/legacy")
    def legacy_endpoint() -> dict:
        return {"ok": True}

    @router.post("/legacy/action")
    def legacy_action() -> dict:
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    return app


def test_deprecation_header_set_on_get_response():
    """Every GET response under the router carries Deprecation: true."""
    client = TestClient(_build_app_with_deprecated_router())

    response = client.get("/legacy")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("Deprecation") == "true"


def test_deprecation_header_set_on_post_response():
    """POST responses under the router also carry Deprecation: true."""
    client = TestClient(_build_app_with_deprecated_router())

    response = client.post("/legacy/action")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("Deprecation") == "true"


def test_deprecation_emits_warning_log():
    """A WARNING log records the deprecated path on each hit."""
    with patch(
        "app.sep.plugins.framework.deprecation.logger.warning",
    ) as mock_warning:
        client = TestClient(_build_app_with_deprecated_router())
        client.get("/legacy")

    assert mock_warning.called
    args = mock_warning.call_args.args
    assert args[0].startswith("Jinja2 plugin route %s is deprecated")
    assert args[1] == "/legacy"
