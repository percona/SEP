"""Define test fixtures."""

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from faker import Faker
from pytest_mock import MockerFixture

from app.core.auth.models import OAuthToken
from app.core.auth.utils import get_user_model
from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.models import CasdoorUser
from app.sep.deps import get_tasks_api
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.main import sep_app
from tests.app.factories import (
    CasdoorUserFactory,
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    OAuthTokenFactory,
)

User = get_user_model()


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
    return "test-client-id"


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
        "exp": round(faker.unix_time(end_datetime="+30d", start_datetime="+7d")),
        "nbf": round(faker.unix_time(end_datetime="-1d", start_datetime="-3d")),
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
def casdoor_mock(
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
    from app.core.config import settings

    return mocker.patch.object(settings, "CASDOOR", settings.CASDOOR)


@pytest.fixture
def admin_user(valid_username: str, faker: Faker) -> CasdoorUser:
    """Create a mock admin user with active status."""
    return CasdoorUserFactory.build(is_admin=True)


@pytest.fixture
def regular_user(valid_username: str, faker: Faker) -> CasdoorUser:
    """Create a mock regular user with active status."""
    return CasdoorUserFactory.build(
        username=valid_username,
        is_admin=False,
    )


@pytest.fixture
def mock_remote_api() -> AsyncMock:
    """Mock a RemoteAPI object."""
    return AsyncMock(spec=RemoteAPI)


@pytest.fixture
def mock_task_api_dep(mock_remote_api: RemoteAPI) -> AsyncMock:
    """Mock the TaskAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_node() -> CreatedNode:
    """Return a fake created node."""
    return CreatedNodeFactory.build(address="localhost")


@pytest.fixture
def created_service(created_node: CreatedNode) -> CreatedService:
    """Return a fake created service."""
    return CreatedServiceFactory.build(node=created_node, type=ServiceTypeEnum.MYSQL)


@pytest.fixture
def created_schema() -> CreatedSchema:
    """Return a fake created Schema."""
    return CreatedSchemaFactory.build()


@pytest.fixture
def created_table() -> CreatedTable:
    """Return a fake created Table."""
    return CreatedTableFactory.build()
