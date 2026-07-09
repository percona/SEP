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

"""Tests for the SEP app-info JSON API route at ``/api/sep/app-info/``."""

from string import Template

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app import __summary__, __version__
from app.sep.config import sep_settings
from app.sep.deps import render_footer_text
from app.sep.main import sep_app


class TestRenderFooterText:
    """Tests for the shared :func:`render_footer_text` helper."""

    def test_matches_legacy_substitution(self) -> None:
        """Render the identical value the legacy Jinja context produced."""
        assert render_footer_text() == sep_settings.FOOTER_TEMPLATE.safe_substitute(
            version=__version__, summary=__summary__
        )

    def test_reads_setting_per_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read ``FOOTER_TEMPLATE`` per call so hot overrides apply live."""
        monkeypatch.setattr(
            sep_settings, "FOOTER_TEMPLATE", Template("v$version / $summary")
        )
        assert render_footer_text() == f"v{__version__} / {__summary__}"


class TestAppInfoEndpoint:
    """Tests for ``GET /api/sep/app-info/`` rendering and live overrides."""

    def test_returns_default_footer_text(self, test_client: TestClient) -> None:
        """Return the footer text rendered from the default ``FOOTER_TEMPLATE``."""
        response = test_client.get("/api/sep/app-info/")
        assert response.status_code == status.HTTP_200_OK
        expected = sep_settings.FOOTER_TEMPLATE.safe_substitute(
            version=__version__, summary=__summary__
        )
        assert response.json() == {"footer_text": expected}

    def test_reflects_live_override(
        self, test_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reflect a live ``FOOTER_TEMPLATE`` override without a restart."""
        monkeypatch.setattr(
            sep_settings,
            "FOOTER_TEMPLATE",
            Template("Custom footer $version"),
        )
        response = test_client.get("/api/sep/app-info/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"footer_text": f"Custom footer {__version__}"}


class TestAppInfoAuth:
    """Tests for ``/api/sep/app-info/`` authentication enforcement."""

    @pytest.fixture
    def unauthenticated_client(self) -> TestClient:
        """Yield a TestClient with no auth dependency overrides applied."""
        previous = sep_app.dependency_overrides
        sep_app.dependency_overrides = {}
        try:
            yield TestClient(sep_app, raise_server_exceptions=False)
        finally:
            sep_app.dependency_overrides = previous

    def test_unauthenticated_returns_json_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Reject anonymous requests with a JSON 401 response."""
        response = unauthenticated_client.get(
            "/api/sep/app-info/", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()
