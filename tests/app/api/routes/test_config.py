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

"""Define tests for the app.api.routes.config module."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """Clear the overrides a test installed, whether or not it passed."""
    yield
    app.dependency_overrides = {}


@pytest.fixture
def test_client():
    """Create a test client for the app."""
    return TestClient(app)


def test_get_alert_config_available(test_client, mocker, regular_user):
    """Report ``available=True`` when at least one alert provider is configured."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    mocker.patch(
        "app.api.routes.config.alert_settings.PROVIDERS",
        new={"any-truthy-provider"},
    )
    response = test_client.get("/api/config/alerts")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"available": True}


def test_get_alert_config_unavailable(test_client, mocker, regular_user):
    """Report ``available=False`` when no alert providers are configured."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    mocker.patch("app.api.routes.config.alert_settings.PROVIDERS", new=set())
    response = test_client.get("/api/config/alerts")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"available": False}


def test_get_alert_config_requires_auth(test_client):
    """Reject anonymous requests so the alerting flag is not leaked."""
    response = test_client.get("/api/config/alerts")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
