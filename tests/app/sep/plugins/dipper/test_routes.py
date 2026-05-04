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

"""Tests for the dipper plugin Jinja2 routes."""

from unittest.mock import AsyncMock, patch

from fastapi.responses import HTMLResponse

from app.sep.deps import get_default_context
from app.sep.main import sep_app
from app.sep.plugins.dipper.routes import router as dipper_jinja_router
from app.sep.plugins.framework.deprecation import DeprecatedJinja2Route


class TestDipperRouterDeprecation:
    """The dipper Jinja2 router uses the deprecation route class."""

    def test_router_uses_deprecated_route_class(self):
        """Confirm the router is constructed with ``DeprecatedJinja2Route``."""
        assert dipper_jinja_router.route_class is DeprecatedJinja2Route

    def test_deprecation_header_and_warning_on_index_route(
        self,
        test_client,
        mock_inventory_api_dep,
        mock_task_api_dep,
    ):
        """GET /dipper/ carries ``Deprecation: true`` and emits a WARNING log.

        Exercises the real Jinja2 route through the full dep chain to confirm
        that ``DeprecatedJinja2Route`` sets the RFC 8594 header and logs at
        WARNING level on each hit — verifying the behaviour rather than just
        the class-attribute identity.
        """
        mock_inventory_api_dep.get = AsyncMock(return_value={"items": []})
        mock_task_api_dep.get = AsyncMock(return_value={})
        # Bypass Casdoor/username-mapping so DefaultContext resolves without
        # a live Casdoor instance in CI.
        sep_app.dependency_overrides[get_default_context] = lambda: {
            "user": None,
            "casdoor_url": "",
            "base_uri": "",
            "plugins": [],
            "sync_refresh_time": 30,
            "csrf_token": "",
            "pmm_url": "",
            "footer_text": "",
            "user_id_to_username": {},
        }

        with (
            patch("app.sep.plugins.dipper.routes.templates") as mock_templates,
            patch(
                "app.sep.plugins.framework.deprecation.logger.warning"
            ) as mock_warning,
        ):
            mock_templates.TemplateResponse.return_value = HTMLResponse("<html>ok</html>")
            response = test_client.get("/dipper/")

        assert response.headers.get("Deprecation") == "true"
        assert mock_warning.called
        assert "is deprecated" in mock_warning.call_args.args[0]
