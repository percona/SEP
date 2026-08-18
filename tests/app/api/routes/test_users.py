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

"""Define tests for the app.api.routes.users module."""

from unittest.mock import AsyncMock

import pytest
from faker import Faker
from fastapi import status
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.auth.models import UserRole
from app.core.auth.utils import get_user_model
from app.main import app
from tests.app.factories import CasdoorUserFactory

User = get_user_model()


@pytest.fixture
def test_client():
    """Create a test client for the app."""
    return TestClient(app)


@pytest.fixture
def other_user(faker: Faker):
    """Create a mock user with active status and no admin privileges."""
    return CasdoorUserFactory.build(
        username="other_user",
        role=UserRole.VIEWER,
    )


def test_list_users_admin(test_client, mocker, admin_user):
    """Test listing users as an admin."""
    # Override the dependency to return an admin user
    app.dependency_overrides[get_current_user] = lambda: admin_user
    mocker.patch.object(User, "get_users", new=AsyncMock(return_value=[admin_user]))
    response = test_client.get("/api/users/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1
    app.dependency_overrides = {}


def test_retrieve_current_user(test_client, regular_user):
    """Test retrieving the current authenticated user."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get("/api/users/me")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == str(regular_user.id)
    app.dependency_overrides = {}


def test_retrieve_user_self(test_client, regular_user):
    """Test retrieving the current user's own information."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get(f"/api/users/{regular_user.username}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["username"] == regular_user.username
    app.dependency_overrides = {}


def test_retrieve_user_as_admin(test_client, mocker, admin_user, other_user):
    """Test retrieving another user's information as an admin."""
    app.dependency_overrides[get_current_user] = lambda: admin_user
    mocker.patch.object(User, "get_user", new=AsyncMock(return_value=other_user))
    response = test_client.get(f"/api/users/{other_user.username}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["username"] == other_user.username
    app.dependency_overrides = {}


def test_retrieve_user_non_admin_other_user(test_client, regular_user, other_user):
    """Test retrieving another user's information as a non-admin (should be forbidden)."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get(f"/api/users/{other_user.username}")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert (
        response.json()["detail"] == "You don't have permission to perform this action"
    )
    app.dependency_overrides = {}


class TestUserRoleIsServed:
    """Verify the ordered role reaches clients through a real response.

    ``role`` and ``is_admin`` are only useful once serialized, so each
    ``User``-returning route is asserted at the request level rather than on
    the model.
    """

    def test_current_user_carries_the_role(self, test_client, regular_user):
        """Verify ``/me`` serves the role alongside the derived admin flag."""
        app.dependency_overrides[get_current_user] = lambda: regular_user

        body = test_client.get("/api/users/me").json()

        assert body["role"] == regular_user.role
        assert body["isAdmin"] is False
        app.dependency_overrides = {}

    def test_self_lookup_carries_the_role(self, test_client, admin_user):
        """Verify the by-username self route serves the same key set."""
        app.dependency_overrides[get_current_user] = lambda: admin_user

        body = test_client.get(f"/api/users/{admin_user.username}").json()

        assert body["role"] == UserRole.ADMIN
        assert body["isAdmin"] is True
        app.dependency_overrides = {}

    def test_listing_carries_the_role_on_every_element(
        self, test_client, mocker, admin_user, other_user
    ):
        """Verify the admin listing serves a role for each user."""
        app.dependency_overrides[get_current_user] = lambda: admin_user
        mocker.patch.object(
            User, "get_users", new=AsyncMock(return_value=[admin_user, other_user])
        )

        body = test_client.get("/api/users/").json()

        assert [element["role"] for element in body] == [
            UserRole.ADMIN,
            UserRole.VIEWER,
        ]
        app.dependency_overrides = {}
