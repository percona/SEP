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

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.testclient import TestClient

from app.sep.apps.framework.deprecation import DeprecatedJinja2Route


def _build_app() -> FastAPI:
    router = APIRouter(route_class=DeprecatedJinja2Route)

    @router.get("/legacy")
    def legacy_endpoint() -> dict:
        return {"ok": True}

    @router.post("/legacy/action")
    def legacy_action() -> dict:
        return {"ok": True}

    @router.get("/legacy/html", response_class=HTMLResponse)
    def legacy_html() -> HTMLResponse:
        return HTMLResponse("<p>hi</p>")

    @router.get("/legacy/redirect")
    def legacy_redirect() -> RedirectResponse:
        return RedirectResponse("/legacy", status_code=status.HTTP_303_SEE_OTHER)

    app = FastAPI()
    app.include_router(router)
    return app


def test_deprecation_header_set_on_dict_response():
    """Every GET response under the router carries Deprecation: true."""
    response = TestClient(_build_app()).get("/legacy")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("Deprecation") == "true"


def test_deprecation_header_set_on_html_response():
    """Regression: header is set even when the endpoint returns HTMLResponse directly."""
    response = TestClient(_build_app()).get("/legacy/html")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("Deprecation") == "true"


def test_deprecation_header_set_on_redirect_response():
    """Regression: header is set even when the endpoint returns RedirectResponse directly."""
    client = TestClient(_build_app(), follow_redirects=False)

    response = client.get("/legacy/redirect")

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers.get("Deprecation") == "true"


def test_deprecation_header_set_on_post_response():
    """POST responses under the router also carry Deprecation: true."""
    response = TestClient(_build_app()).post("/legacy/action")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("Deprecation") == "true"


def test_deprecation_emits_warning_log():
    """A WARNING log records the deprecated path on each hit."""
    with patch(
        "app.sep.apps.framework.deprecation.logger.warning",
    ) as mock_warning:
        TestClient(_build_app()).get("/legacy")

    assert mock_warning.called
    args = mock_warning.call_args.args
    assert "Jinja2 plugin route /legacy is deprecated" in args[0]


def test_deprecation_emits_deprecationwarning():
    """Each deprecated route hit triggers a ``DeprecationWarning``."""
    with pytest.warns(DeprecationWarning, match="Jinja2 plugin route /legacy"):
        response = TestClient(_build_app()).get("/legacy")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("Deprecation") == "true"


def test_deprecated_routes_omitted_from_openapi():
    """Verify legacy Jinja routes using ``DeprecatedJinja2Route`` are omitted from the OpenAPI schema."""
    app = _build_app()
    spec = app.openapi()

    for path in ("/legacy", "/legacy/action", "/legacy/html", "/legacy/redirect"):
        assert path not in spec.get("paths", {}), (
            f"{path} should be omitted from OpenAPI schema"
        )
