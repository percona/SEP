"""Define test fixtures."""

from typing import Any
from unittest.mock import Mock

import pytest
from faker import Faker
from pytest_mock import MockerFixture

from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor import CasdoorSDK
from app.core.config import settings
from app.tests.factories import CasdoorSDKFactory, OAuthTokenFactory


@pytest.fixture(scope="session")
def faker() -> Faker:
    """Provide a Faker instance for generating fake data."""
    return Faker()


@pytest.fixture
def casdoor_allowed_issuer() -> str:
    """Provide a Casdoor allowed issuer URL."""
    return "https://allowed-issuer.com"


@pytest.fixture
def casdoor_disallowed_issuer() -> str:
    """Provide a Casdoor disallowed issuer URL."""
    return "https://disallowed-issuer.com"


@pytest.fixture
def casdoor_client_id() -> str:
    """Provide a fake Casdoor client ID."""
    return "fakeClientId"


@pytest.fixture
def valid_username() -> str:
    """Provide a valid username for testing."""
    return "valid-username"


@pytest.fixture
def casdoor_token_payload_data(
    casdoor_allowed_issuer: str,
    casdoor_client_id: str,
    valid_username: str,
    faker: Faker,
) -> dict[str, Any]:
    """Provide mock data for a Casdoor token payload."""
    return {
        "iss": casdoor_allowed_issuer,
        "sub": faker.pystr(),
        "aud": [casdoor_client_id],
        "exp": faker.future_datetime().isoformat(),
        "nbf": faker.past_datetime().isoformat(),
        "jti": faker.pystr(),
        "username": valid_username,
        "active": True,
    }


@pytest.fixture
def casdoor_user_data(valid_username: str, faker: Faker) -> dict[str, Any]:
    """Provide mock data for a Casdoor user."""
    return {
        "id": faker.uuid4(),
        "username": valid_username,
        "email": faker.email(),
        "first_name": faker.first_name(),
        "last_name": faker.last_name(),
        "is_admin": False,
        "created_time": faker.date_time().isoformat(),
        "updated_time": "",
        "owner": "organization",
        "is_forbidden": False,
        "is_deleted": False,
    }


@pytest.fixture(scope="class")
def oauth_token() -> OAuthToken:
    """Provide a mock OAuthToken instance."""
    return OAuthTokenFactory.build()


@pytest.fixture
def refresh_token() -> str:
    """Provide a mock refresh token."""
    return "test_refresh_token"


@pytest.fixture
def casdoor_settings(casdoor_allowed_issuer: str, casdoor_client_id: str) -> CasdoorSDK:
    """Provide a configured CasdoorSDK instance."""
    return CasdoorSDKFactory.build(
        allowed_issuers=[casdoor_allowed_issuer],
        client_id=casdoor_client_id,
        front_endpoint=casdoor_allowed_issuer,
    )


@pytest.fixture
def casdoor_mock(
    casdoor_settings: CasdoorSDK,
    casdoor_token_payload_data: dict[str, Any],
    oauth_token: OAuthToken,
    refresh_token: str,
    casdoor_user_data: dict[str, Any],
    mocker: MockerFixture,
) -> Mock:
    """Mock CasdoorSDK methods to simulate Casdoor service interactions."""
    mocker.patch(
        "app.core.auth.providers.casdoor.CasdoorSDK.introspect_token",
        new=mocker.AsyncMock(return_value=casdoor_token_payload_data),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.CasdoorSDK.get_access_token",
        new=mocker.AsyncMock(return_value=oauth_token.model_dump()),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.CasdoorSDK.refresh_token_request",
        new=mocker.AsyncMock(return_value=oauth_token.model_dump()),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.CasdoorSDK.get_token",
        new=mocker.AsyncMock(return_value={"data": {"refreshToken": refresh_token}}),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.CasdoorSDK.get_user",
        new=mocker.AsyncMock(return_value=casdoor_user_data),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.CasdoorSDK.get_users",
        new=mocker.AsyncMock(return_value=[casdoor_user_data]),
    )
    return mocker.patch.object(settings, "CASDOOR", casdoor_settings)
