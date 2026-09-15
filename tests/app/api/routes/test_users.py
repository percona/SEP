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
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.users import retrieve_user
from app.core.auth.models import BaseUser, UserRole
from app.core.auth.providers.grafana.models import GrafanaUser
from app.core.auth.utils import get_user_model
from app.main import app
from tests.app.factories import CasdoorUserFactory

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """Clear the overrides a test installed, whether or not it passed."""
    yield
    app.dependency_overrides = {}


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


def test_retrieve_current_user(test_client, regular_user):
    """Test retrieving the current authenticated user."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get("/api/users/me")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == str(regular_user.id)


def test_retrieve_user_self(test_client, regular_user):
    """Test retrieving the current user's own information."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get(f"/api/users/{regular_user.username}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["username"] == regular_user.username


def test_retrieve_user_as_admin(test_client, mocker, admin_user, other_user):
    """Test retrieving another user's information as an admin."""
    app.dependency_overrides[get_current_user] = lambda: admin_user
    mocker.patch.object(User, "get_user", new=AsyncMock(return_value=other_user))
    response = test_client.get(f"/api/users/{other_user.username}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["username"] == other_user.username


def test_retrieve_user_non_admin_other_user(test_client, regular_user, other_user):
    """Test retrieving another user's information as a non-admin (should be forbidden)."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get(f"/api/users/{other_user.username}")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert (
        response.json()["detail"] == "You don't have permission to perform this action"
    )


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

        assert body["role"] == regular_user.role.value
        assert body["isAdmin"] is False

    def test_self_lookup_carries_the_role(self, test_client, admin_user):
        """Verify the by-username self route serves the same key set."""
        app.dependency_overrides[get_current_user] = lambda: admin_user

        body = test_client.get(f"/api/users/{admin_user.username}").json()

        assert body["role"] == UserRole.ADMIN.value
        assert body["isAdmin"] is True

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
            UserRole.ADMIN.value,
            UserRole.VIEWER.value,
        ]


class TestRetrieveUnderAnOrgScopedGrafanaAccount:
    """Verify the by-username route resolves when the lookup endpoint is refused.

    Requests run against an app mounting the real route function under a
    Grafana-shaped response model. The application under test binds that model at
    import to the configured provider's, which requires ``owner``, a field a
    Grafana record does not carry, so a Grafana user cannot pass validation on
    the route as mounted there.
    """

    @staticmethod
    def _client(current_user: BaseUser) -> TestClient:
        """Return a client for the route served under the Grafana user model."""
        grafana_app = FastAPI()
        grafana_app.add_api_route(
            "/api/users/{username}", retrieve_user, response_model=GrafanaUser
        )
        grafana_app.dependency_overrides[get_current_user] = lambda: current_user
        return TestClient(grafana_app)

    @pytest.fixture(autouse=True)
    def _refuse_the_lookup(self, mocker, grafana_mock):
        """Resolve the route through a provider whose lookup endpoint refuses."""
        mocker.patch("app.api.routes.users.User", GrafanaUser)
        grafana_mock.lookup_user.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions needed: users:read",
        )

    def test_admin_retrieves_another_user(
        self, admin_user, grafana_org_users, valid_username
    ):
        """Verify the admin branch serves the record from the org listing."""
        response = self._client(admin_user).get(f"/api/users/{valid_username}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["username"] == valid_username
        assert body["email"] == grafana_org_users[0]["email"]
        assert body["role"] == UserRole.VIEWER.value
        assert body["isAdmin"] is False

    def test_a_roleless_membership_is_served_rather_than_refused(
        self, admin_user, grafana_mock, grafana_org_users, valid_username
    ):
        """Verify a user Grafana grants no org role reaches the client as none."""
        grafana_mock.get_org_users.return_value = [
            {**grafana_org_users[0], "role": "None"}
        ]

        response = self._client(admin_user).get(f"/api/users/{valid_username}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["role"] == UserRole.NONE.value

    def test_a_miss_is_not_found(self, admin_user):
        """Verify an absent user reads as not found, carrying no upstream detail."""
        response = self._client(admin_user).get("/api/users/nobody")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "users:read" not in response.text

    def test_non_admin_is_refused_before_any_upstream_call(
        self, regular_user, grafana_mock, other_user
    ):
        """Verify the route gate still runs ahead of the provider."""
        response = self._client(regular_user).get(f"/api/users/{other_user.username}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        grafana_mock.lookup_user.assert_not_awaited()
        grafana_mock.get_org_users.assert_not_awaited()


class TestProviderFieldsSurviveTheResponseModel:
    """Cover the fields only the configured provider's user class declares.

    These routes annotate the static ``BaseUser`` and name the concrete class in
    an explicit ``response_model=``. Without that kwarg FastAPI would derive the
    response model from the return annotation and filter every provider-specific
    field out of both the body and the published schema.

    The expected set is derived rather than hardcoded, so it names whatever the
    configured provider adds over ``BaseUser``. Each case asserts that set is
    non-empty first: only Casdoor — the provider the suite runs under — adds
    any, and without that control the subset assertions would pass vacuously
    against a provider that adds none.
    """

    @staticmethod
    def _provider_only_fields() -> set[str]:
        """Return the serialized names the user class adds over ``BaseUser``.

        Named by alias, since the provider models generate camelCase ones and
        both the response body and the schema are keyed on those.
        """
        return {
            field.alias or name
            for name, field in User.model_fields.items()
            if name not in BaseUser.model_fields
        }

    def test_listing_carries_them_on_every_element(
        self, test_client, mocker, admin_user
    ):
        """Verify a listed user keeps the provider's own fields."""
        app.dependency_overrides[get_current_user] = lambda: admin_user
        mocker.patch.object(User, "get_users", new=AsyncMock(return_value=[admin_user]))

        response = test_client.get("/api/users/")

        assert response.status_code == status.HTTP_200_OK
        assert self._provider_only_fields()
        for item in response.json():
            assert self._provider_only_fields() <= item.keys()

    def test_current_user_carries_them(self, test_client, regular_user):
        """Verify the self endpoint keeps the provider's own fields."""
        app.dependency_overrides[get_current_user] = lambda: regular_user

        response = test_client.get("/api/users/me")

        assert response.status_code == status.HTTP_200_OK
        assert self._provider_only_fields()
        assert self._provider_only_fields() <= response.json().keys()

    def test_lookup_carries_them(self, test_client, mocker, admin_user, other_user):
        """Verify the by-username endpoint keeps the provider's own fields."""
        app.dependency_overrides[get_current_user] = lambda: admin_user
        mocker.patch.object(User, "get_user", new=AsyncMock(return_value=other_user))

        response = test_client.get(f"/api/users/{other_user.username}")

        assert response.status_code == status.HTTP_200_OK
        assert self._provider_only_fields()
        assert self._provider_only_fields() <= response.json().keys()

    def test_published_schema_still_declares_them(self, test_client):
        """Verify the fields survive in the OpenAPI schema, not just in a body.

        A body assertion alone passes when a fixture happens to leave the field
        unset, so the schema is the half that has to be checked separately.
        """
        schema = test_client.get("/openapi.json").json()
        assert self._provider_only_fields()

        for path, method in (
            ("/api/users/", "get"),
            ("/api/users/me", "get"),
            ("/api/users/{username}", "get"),
        ):
            content = schema["paths"][path][method]["responses"]["200"]["content"]
            body_schema = content["application/json"]["schema"]
            ref = body_schema.get("$ref") or body_schema["items"]["$ref"]
            component = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]

            assert self._provider_only_fields() <= component["properties"].keys(), (
                f"{method.upper()} {path} dropped provider fields from its schema"
            )
