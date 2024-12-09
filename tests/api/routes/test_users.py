"""Define tests for the app.api.routes.users module."""

from http import HTTPStatus
from unittest.mock import AsyncMock

import pytest
from faker import Faker
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.auth.utils import get_user_model
from app.main import app

User = get_user_model()


@pytest.fixture
def test_client():
    """Create a test client for the app."""
    return TestClient(app)


@pytest.fixture
def admin_user(valid_username, faker: Faker):
    """Create a mock admin user with active status."""
    return User(
        id=faker.uuid4(),
        username=valid_username,
        owner="organization",
        is_active=True,
        is_admin=True,
    )


@pytest.fixture
def regular_user(valid_username, faker: Faker):
    """Create a mock regular user with active status."""
    return User(
        id=faker.uuid4(),
        username=valid_username,
        owner="organization",
        is_active=True,
        is_admin=False,
    )


@pytest.fixture
def other_user(faker: Faker):
    """Create a mock user with active status and no admin privileges."""
    return User(
        id=faker.uuid4(),
        owner="organization",
        username="other_user",
        is_active=True,
        is_admin=False,
    )


def test_list_users_admin(test_client, mocker, admin_user):
    """Test listing users as an admin."""
    # Override the dependency to return an admin user
    app.dependency_overrides[get_current_user] = lambda: admin_user
    mocker.patch.object(User, "get_users", new=AsyncMock(return_value=[admin_user]))
    response = test_client.get("/api/users/")
    assert response.status_code == HTTPStatus.OK
    assert len(response.json()) == 1
    app.dependency_overrides = {}


def test_retrieve_current_user(test_client, regular_user):
    """Test retrieving the current authenticated user."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get("/api/users/me")
    assert response.status_code == HTTPStatus.OK
    assert response.json()["id"] == str(regular_user.id)
    app.dependency_overrides = {}


def test_retrieve_user_self(test_client, regular_user):
    """Test retrieving the current user's own information."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get(f"/api/users/{regular_user.username}")
    assert response.status_code == HTTPStatus.OK
    assert response.json()["username"] == regular_user.username
    app.dependency_overrides = {}


def test_retrieve_user_as_admin(test_client, mocker, admin_user, other_user):
    """Test retrieving another user's information as an admin."""
    app.dependency_overrides[get_current_user] = lambda: admin_user
    mocker.patch.object(User, "get_user", new=AsyncMock(return_value=other_user))
    response = test_client.get(f"/api/users/{other_user.username}")
    assert response.status_code == HTTPStatus.OK
    assert response.json()["username"] == other_user.username
    app.dependency_overrides = {}


def test_retrieve_user_non_admin_other_user(test_client, regular_user, other_user):
    """Test retrieving another user's information as a non-admin (should be forbidden)."""
    app.dependency_overrides[get_current_user] = lambda: regular_user
    response = test_client.get(f"/api/users/{other_user.username}")
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert (
        response.json()["detail"] == "You don't have permission to perform this action"
    )
    app.dependency_overrides = {}
