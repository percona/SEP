"""Define tests for the app.api.routes.oauth module."""

from unittest.mock import AsyncMock

import pytest
from faker import Faker
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.auth.utils import get_user_model
from app.main import app

User = get_user_model()

HTTP_STATUS_OK = 200
HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_FORBIDDEN = 403


@pytest.fixture
def test_client():
    """Create a test client for the app."""
    return TestClient(app)


def test_create_oauth_token_success(
    test_client, valid_username, oauth_token, mocker, faker: Faker
):
    """Test successful OAuth token creation with valid credentials."""
    # Mock the User.get_oauth_token method
    mocker.patch.object(
        User, "get_oauth_token", new=AsyncMock(return_value=oauth_token)
    )
    mocker.patch.object(
        User,
        "from_jwt",
        new=AsyncMock(
            return_value=User(
                id=faker.uuid4(),
                owner="organization",
                username=valid_username,
                is_active=True,
            )
        ),
    )

    data = {
        "id": faker.uuid4(),
        "username": valid_username,
        "password": "valid_password",
    }
    response = test_client.post("/api/oauth/token", data=data)
    assert response.status_code == HTTP_STATUS_OK
    assert response.json() == oauth_token.model_dump()


def test_create_oauth_token_invalid_credentials(
    test_client,
    valid_username,
    mocker,
):
    """Test OAuth token creation failure with invalid credentials."""
    # Mock the User.get_oauth_token method to raise ValidationError
    mocker.patch.object(
        User,
        "get_oauth_token",
        new=AsyncMock(
            side_effect=ValidationError.from_exception_data(
                title="Validation Error",
                line_errors=[],
            )
        ),
    )
    data = {
        "username": valid_username,
        "password": "invalid_password",
    }

    response = test_client.post("/api/oauth/token", data=data)
    assert response.status_code == HTTP_STATUS_UNAUTHORIZED
    assert response.json()["detail"] == "Incorrect username or password"


def test_create_oauth_token_inactive_user(
    test_client, valid_username, oauth_token, mocker, faker: Faker
):
    """Test OAuth token creation failure when the user is inactive."""
    # Mock the User.get_oauth_token method
    mocker.patch.object(
        User, "get_oauth_token", new=AsyncMock(return_value=oauth_token)
    )
    # Mock User.from_jwt to return an inactive user
    mocker.patch.object(
        User,
        "from_jwt",
        new=AsyncMock(
            return_value=User(
                id=faker.uuid4(),
                owner="organization",
                username=valid_username,
                is_forbidden=True,
            )
        ),
    )

    data = {
        "username": valid_username,
        "password": "valid_password",
    }
    response = test_client.post("/api/oauth/token", data=data)
    assert response.status_code == HTTP_STATUS_FORBIDDEN
    assert response.json()["detail"] == "User is not active"


def test_refresh_token_success(test_client, oauth_token, mocker, faker: Faker):
    """Test successful token refresh with a valid refresh token."""
    # Mock the User.get_oauth_token method
    mocker.patch.object(
        User, "get_oauth_token", new=AsyncMock(return_value=oauth_token)
    )
    mocker.patch.object(
        User,
        "from_jwt",
        new=AsyncMock(
            return_value=User(
                id=faker.uuid4(),
                owner="organization",
                username="valid_username",
                is_active=True,
            )
        ),
    )

    data = {"token": "valid_refresh_token"}
    response = test_client.post(
        "/api/oauth/refresh",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == HTTP_STATUS_OK
    assert response.json() == oauth_token.model_dump()


def test_refresh_token_invalid_token(test_client, mocker):
    """Test token refresh failure with an invalid refresh token."""
    # Mock the User.get_oauth_token method to raise ValidationError
    mocker.patch.object(
        User,
        "get_oauth_token",
        new=AsyncMock(
            side_effect=ValidationError.from_exception_data(
                title="Validation Error", line_errors=[]
            )
        ),
    )
    data = {"token": "invalid_refresh_token"}
    response = test_client.post(
        "/api/oauth/refresh",
        json=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == HTTP_STATUS_UNAUTHORIZED
    assert response.json()["detail"] == "Refresh token is invalid, expired, or revoked"


def test_refresh_token_inactive_user(test_client, oauth_token, mocker, faker: Faker):
    """Test token refresh failure when the user is inactive."""
    # Mock the User.get_oauth_token method
    mocker.patch.object(
        User, "get_oauth_token", new=AsyncMock(return_value=oauth_token)
    )
    # Mock User.from_jwt to return an inactive user
    mocker.patch.object(
        User,
        "from_jwt",
        new=AsyncMock(
            return_value=User(
                id=faker.uuid4(),
                owner="organization",
                username="valid_username",
                is_forbidden=True,
            )
        ),
    )

    data = {"token": "valid_refresh_token"}
    response = test_client.post(
        "/api/oauth/refresh",
        json=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == HTTP_STATUS_FORBIDDEN
    assert response.json()["detail"] == "User is not active"
