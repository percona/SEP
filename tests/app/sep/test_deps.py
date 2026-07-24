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

"""Define tests for base SEP dependencies."""

from collections import OrderedDict
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.testclient import TestClient
from itsdangerous import BadSignature
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth.exceptions import (
    HTTPForbiddenException,
    HTTPUnauthorizedException,
)
from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.auth.providers.grafana.sdk import GrafanaException
from app.core.exceptions import (
    HTTPConflictException,
    HTTPNotFoundException,
    HTTPRedirectException,
    HTTPServiceUnavailableException,
)
from app.core.pagination import MAX_PAGINATION_LIMIT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.framework.registry import AppRegistry, build_app_registry
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.config import App, sep_settings
from app.sep.crud import AppStateManager
from app.sep.deps import (
    BEARER_REQUIRED_DETAIL,
    check_for_conflicted_running_tasks,
    ExecutorHostsContext,
    get_api_authenticated_admin,
    get_api_authenticated_user,
    get_base_url,
    get_created_entity,
    get_created_node,
    get_created_schema,
    get_current_admin,
    get_current_user,
    get_default_context,
    get_executor_hosts,
    get_executor_hosts_context,
    get_inventory_api,
    get_pmm_api,
    get_task_by_name,
    get_task_history,
    get_tasks_api,
    get_tasks_context,
    get_tasks_index_context,
    get_toggleable_app_key,
    get_username_mapping,
    is_bearer_authenticated,
    PROTECTED_APP_KEYS,
    protected_task_guard,
    reject_if_protected,
    require_app_enabled,
    require_bearer_for_unsafe_methods,
    require_pmm_api,
    resolve_ambient_session_token,
)
from app.sep.exceptions import LoginRedirectException
from app.sep.inventory import CreatedNode, CreatedSchema
from app.sep.models import AppLifecycleEnum, AppState, SyncInventoryEntityTypeEnum
from app.tasks.models import (
    Task,
    TaskHistoryStatusEnum,
)
from tests.app.factories import (
    CasdoorUserFactory,
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    TaskFactory,
)

PENDING_HISTORY_ID = 10
RUNNING_HISTORY_ID = 11
SUCCESS_HISTORY_ID = 12
EXPECTED_NODE_COUNT = 5


def _make_request(method: str = "GET", authorization: str | None = None) -> Request:
    """Build a minimal Request with messages state for testing.

    :param method: HTTP method to set on the request scope.
    :type method: str
    :param authorization: Value for the ``Authorization`` header, if any.
    :type authorization: str | None
    """
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "method": method,
        "client": ("127.0.0.1", "80"),
        "path": "/",
        "app": MagicMock(),
        "router": MagicMock(),
    }
    req = Request(scope)
    req.state.messages = OrderedDict()
    return req


class TestResolveAmbientSessionToken:
    """Test ``resolve_ambient_session_token`` gating and silent-fallback behavior."""

    @staticmethod
    def _request(cookies: dict[str, str] | None = None) -> Request:
        """Build a minimal GET request carrying ``cookies`` in the Cookie header."""
        headers = []
        if cookies:
            joined = "; ".join(f"{name}={value}" for name, value in cookies.items())
            headers.append((b"cookie", joined.encode()))
        return Request(
            {"type": "http", "headers": headers, "method": "GET", "path": "/"}
        )

    @pytest.mark.asyncio
    async def test_none_when_toggle_disabled(self, grafana_mock) -> None:
        """Assert the helper no-ops when the toggle is off, even under Grafana."""
        request = self._request({"grafana_session": "s"})
        assert await resolve_ambient_session_token(request) is None

    @pytest.mark.asyncio
    async def test_none_when_provider_not_grafana(self, mocker) -> None:
        """Assert a non-Grafana active provider yields ``None`` (AC #7)."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        request = self._request({"grafana_session": "s"})
        assert await resolve_ambient_session_token(request) is None

    @pytest.mark.asyncio
    async def test_none_when_cookie_absent(self, grafana_mock, mocker) -> None:
        """Assert an absent session cookie yields ``None``."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        request = self._request()
        assert await resolve_ambient_session_token(request) is None

    @pytest.mark.asyncio
    async def test_returns_token_on_happy_path(
        self, grafana_mock, grafana_user_record, mocker
    ) -> None:
        """Assert a valid ambient session mints a token pair through the real model."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        request = self._request({"grafana_session": "ambient"})

        token = await resolve_ambient_session_token(request)

        assert isinstance(token, OAuthToken)
        assert token.access_token
        assert token.refresh_token
        grafana_mock.get_current_user.assert_awaited_once_with("ambient")

    @pytest.mark.asyncio
    async def test_operational_failure_logs_and_returns_none(
        self, grafana_mock, mocker
    ) -> None:
        """Assert an operational upstream failure logs a warning and falls back to ``None``."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        grafana_mock.get_current_user.side_effect = GrafanaException()
        warning = mocker.patch("app.sep.deps.logger.warning")
        request = self._request({"grafana_session": "s"})

        assert await resolve_ambient_session_token(request) is None
        warning.assert_called_once()


class TestGetBaseUrl:
    """Test get_base_url dependency."""

    def test_returns_setting_when_configured(self) -> None:
        """Assert BASE_URL from settings is returned when set."""
        request = _make_request()
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.BASE_URL = "https://example.com"
            result = get_base_url(request)
        assert result == "https://example.com"


class TestGetCurrentUser:
    """Test get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_valid_bearer_returns_user(self) -> None:
        """Assert a valid Bearer path returns the user from the API dependency."""
        request = _make_request(authorization="Bearer bearer-token")
        active_user = CasdoorUserFactory.build(is_forbidden=False)
        mock_oauth2 = AsyncMock(return_value="bearer-token")
        mock_api_user = AsyncMock(return_value=active_user)
        with (
            patch("app.sep.deps.oauth2_scheme", mock_oauth2),
            patch("app.sep.deps.get_current_user_api", mock_api_user),
            patch(
                "app.sep.deps.get_access_token_from_cookie",
                side_effect=AssertionError(
                    "cookie must not be read when Bearer succeeds"
                ),
            ),
        ):
            result = await get_current_user(request)
        assert result is active_user
        mock_oauth2.assert_awaited_once_with(request)
        mock_api_user.assert_awaited_once_with("bearer-token")

    @pytest.mark.asyncio
    async def test_valid_cookie_returns_user(self) -> None:
        """Assert cookie-only auth still returns an active user."""
        request = _make_request()
        active_user = CasdoorUserFactory.build(is_forbidden=False)
        with (
            patch(
                "app.sep.deps.oauth2_scheme",
                AsyncMock(
                    side_effect=AssertionError(
                        "oauth2_scheme must not be called without a Bearer header"
                    )
                ),
            ),
            patch(
                "app.sep.deps.get_access_token_from_cookie", return_value="cookie-token"
            ),
            patch.object(CasdoorUser, "from_jwt", return_value=active_user),
        ):
            result = await get_current_user(request)
        assert result is active_user

    @pytest.mark.asyncio
    async def test_bearer_and_cookie_present_bearer_wins(self) -> None:
        """Assert Authorization Bearer is preferred over session cookie."""
        request = _make_request(authorization="Bearer bearer-token")
        bearer_user = CasdoorUserFactory.build(username="bearer-user")
        cookie_user = CasdoorUserFactory.build(username="cookie-user")
        with (
            patch("app.sep.deps.oauth2_scheme", AsyncMock(return_value="bearer-token")),
            patch(
                "app.sep.deps.get_current_user_api", AsyncMock(return_value=bearer_user)
            ),
            patch(
                "app.sep.deps.get_access_token_from_cookie",
                return_value="cookie-token",
            ),
            patch.object(
                CasdoorUser,
                "from_jwt",
                return_value=cookie_user,
            ),
        ):
            result = await get_current_user(request)
        assert result.username == "bearer-user"

    @pytest.mark.asyncio
    async def test_neither_bearer_nor_cookie_raises_redirect(self) -> None:
        """Assert missing Bearer and missing cookie raises LoginRedirectException."""
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_access_token_from_cookie",
                side_effect=LoginRedirectException(request),
            ),
            pytest.raises(LoginRedirectException),
        ):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_invalid_bearer_raises_unauthorized(self) -> None:
        """Assert invalid JWT via Bearer raises HTTPUnauthorizedException."""
        request = _make_request(authorization="Bearer bad-token")
        with (
            patch("app.sep.deps.oauth2_scheme", AsyncMock(return_value="bad-token")),
            patch(
                "app.sep.deps.get_current_user_api",
                AsyncMock(side_effect=HTTPUnauthorizedException),
            ),
            pytest.raises(HTTPUnauthorizedException),
        ):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_inactive_user_via_bearer_raises_forbidden(self) -> None:
        """Assert inactive user resolved via Bearer raises HTTPForbiddenException."""
        request = _make_request(authorization="Bearer token")
        with (
            patch("app.sep.deps.oauth2_scheme", AsyncMock(return_value="token")),
            patch(
                "app.sep.deps.get_current_user_api",
                AsyncMock(side_effect=HTTPForbiddenException("User is not active")),
            ),
            pytest.raises(HTTPForbiddenException),
        ):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_malformed_bearer_header_does_not_fall_back_to_cookie(self) -> None:
        """Assert a malformed Bearer header surfaces the 401 without cookie fallback."""
        request = _make_request(authorization="Bearer ")
        with (
            patch(
                "app.sep.deps.oauth2_scheme",
                AsyncMock(side_effect=HTTPException(status_code=401)),
            ),
            patch(
                "app.sep.deps.get_access_token_from_cookie",
                side_effect=AssertionError(
                    "cookie must not be read for a Bearer-authenticated request"
                ),
            ),
            pytest.raises(HTTPException),
        ):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_bad_signature_raises_redirect(self) -> None:
        """Assert BadSignature during JWT decode raises LoginRedirectException."""
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_access_token_from_cookie", return_value="fake-token"
            ),
            patch.object(CasdoorUser, "from_jwt", side_effect=BadSignature("bad")),
            pytest.raises(LoginRedirectException),
        ):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_validation_error_raises_redirect(self) -> None:
        """Assert ValidationError during user parsing raises LoginRedirectException."""
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_access_token_from_cookie", return_value="fake-token"
            ),
            patch.object(
                CasdoorUser,
                "from_jwt",
                side_effect=ValidationError.from_exception_data("CasdoorUser", []),
            ),
            pytest.raises(LoginRedirectException),
        ):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_inactive_user_raises_redirect(self) -> None:
        """Assert inactive user raises LoginRedirectException."""
        inactive_user = CasdoorUserFactory.build(is_forbidden=True)
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_access_token_from_cookie", return_value="fake-token"
            ),
            patch.object(CasdoorUser, "from_jwt", return_value=inactive_user),
            pytest.raises(LoginRedirectException),
        ):
            await get_current_user(request)


class TestGetApiAuthenticatedUser:
    """Test get_api_authenticated_user dependency."""

    @pytest.mark.asyncio
    async def test_returns_user_when_authenticated(self) -> None:
        """Assert the authenticated user is returned unchanged."""
        request = _make_request()
        active_user = CasdoorUserFactory.build(is_forbidden=False)
        with patch(
            "app.sep.deps.get_current_user", AsyncMock(return_value=active_user)
        ):
            result = await get_api_authenticated_user(request)
        assert result is active_user

    @pytest.mark.asyncio
    async def test_login_redirect_raises_unauthorized(self) -> None:
        """Assert LoginRedirectException is converted to HTTPUnauthorizedException."""
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_current_user",
                AsyncMock(side_effect=LoginRedirectException(request)),
            ),
            pytest.raises(HTTPUnauthorizedException),
        ):
            await get_api_authenticated_user(request)

    @pytest.mark.asyncio
    async def test_login_redirect_preserves_cookie_clearing_header(self) -> None:
        """Assert the ``set-cookie`` header from ``LoginRedirectException`` is preserved.

        ``LoginRedirectException`` emits a ``set-cookie`` header that clears the
        stale session cookie. When the exception is converted to 401 for API
        callers, that header must ride along so the invalid cookie does not
        linger on the client.
        """
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_current_user",
                AsyncMock(side_effect=LoginRedirectException(request)),
            ),
            pytest.raises(HTTPUnauthorizedException) as exc_info,
        ):
            await get_api_authenticated_user(request)
        assert exc_info.value.headers is not None
        set_cookie = exc_info.value.headers.get("set-cookie")
        assert set_cookie is not None
        assert sep_settings.SESSION.COOKIE_NAME in set_cookie
        assert f"{sep_settings.SESSION.COOKIE_NAME}=" in set_cookie

    @pytest.mark.asyncio
    async def test_http_redirect_raises_unauthorized(self) -> None:
        """Assert a plain HTTPRedirectException is also converted to 401."""
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_current_user",
                AsyncMock(side_effect=HTTPRedirectException("/login")),
            ),
            pytest.raises(HTTPUnauthorizedException),
        ):
            await get_api_authenticated_user(request)

    @pytest.mark.asyncio
    async def test_non_redirect_exception_propagates(self) -> None:
        """Assert non-redirect auth exceptions propagate unchanged."""
        request = _make_request()
        with (
            patch(
                "app.sep.deps.get_current_user",
                AsyncMock(side_effect=HTTPForbiddenException("User is not active")),
            ),
            pytest.raises(HTTPForbiddenException),
        ):
            await get_api_authenticated_user(request)


class TestGetCurrentAdmin:
    """Test get_current_admin dependency."""

    @pytest.mark.asyncio
    async def test_non_admin_raises_forbidden(self) -> None:
        """Assert non-admin user raises HTTPForbiddenException."""
        regular_user = CasdoorUserFactory.build(is_admin=False)
        with pytest.raises(HTTPForbiddenException):
            await get_current_admin(regular_user)

    @pytest.mark.asyncio
    async def test_admin_returns_user(self) -> None:
        """Assert admin user is returned successfully."""
        admin_user = CasdoorUserFactory.build(is_admin=True)
        result = await get_current_admin(admin_user)
        assert result is admin_user


class TestGetApiAuthenticatedAdmin:
    """Test get_api_authenticated_admin dependency."""

    @pytest.mark.asyncio
    async def test_admin_returns_user(self) -> None:
        """Assert an admin user is returned unchanged."""
        admin_user = CasdoorUserFactory.build(is_admin=True)
        result = await get_api_authenticated_admin(admin_user)
        assert result is admin_user

    @pytest.mark.asyncio
    async def test_non_admin_raises_forbidden(self) -> None:
        """Assert an authenticated non-admin gets 403 (not 401)."""
        regular_user = CasdoorUserFactory.build(is_admin=False)
        with pytest.raises(HTTPForbiddenException):
            await get_api_authenticated_admin(regular_user)


class TestGetUsernameMapping:
    """Test get_username_mapping dependency."""

    @pytest.mark.asyncio
    async def test_provider_failure_returns_empty_dict(self) -> None:
        """Assert an auth-provider failure returns an empty dict."""
        with patch(
            "app.sep.deps.User.get_users",
            new=AsyncMock(side_effect=ValueError("connection failed")),
        ):
            result = await get_username_mapping()
        assert result == {}

    @pytest.mark.asyncio
    async def test_http_exception_returns_empty_dict(self) -> None:
        """Assert an HTTPException from the provider returns an empty dict."""
        with patch(
            "app.sep.deps.User.get_users",
            new=AsyncMock(side_effect=HTTPException(status_code=500, detail="fail")),
        ):
            result = await get_username_mapping()
        assert result == {}

    @pytest.mark.asyncio
    async def test_key_error_returns_empty_dict(self) -> None:
        """Assert a KeyError from a malformed response returns an empty dict."""
        with patch(
            "app.sep.deps.User.get_users",
            new=AsyncMock(side_effect=KeyError("missing")),
        ):
            result = await get_username_mapping()
        assert result == {}

    @pytest.mark.asyncio
    async def test_attribute_error_returns_empty_dict(self) -> None:
        """Assert AttributeError (e.g. session not initialized) returns empty dict."""
        with patch(
            "app.sep.deps.User.get_users",
            new=AsyncMock(
                side_effect=AttributeError(
                    "'NoneType' object has no attribute 'request'"
                )
            ),
        ):
            result = await get_username_mapping()
        assert result == {}


class TestGetInventoryApi:
    """Test get_inventory_api context manager."""

    @pytest.mark.asyncio
    async def test_yields_authenticated_client(self) -> None:
        """Assert authenticated API client is yielded and cleaned up."""
        mock_client = MagicMock()
        mock_authenticated = MagicMock()
        mock_client.auth.return_value.__enter__ = MagicMock(
            return_value=mock_authenticated
        )
        mock_client.auth.return_value.__exit__ = MagicMock(return_value=False)
        mock_user = CasdoorUserFactory.build()
        mock_user.access_token = "test-token"

        gen = get_inventory_api(mock_client, mock_user)
        result = await gen.__anext__()
        assert result is mock_authenticated
        mock_client.auth.assert_called_once_with("test-token")


class TestGetTasksApi:
    """Test get_tasks_api context manager."""

    @pytest.mark.asyncio
    async def test_yields_authenticated_client(self) -> None:
        """Assert authenticated API client is yielded and cleaned up."""
        mock_client = MagicMock()
        mock_authenticated = MagicMock()
        mock_client.auth.return_value.__enter__ = MagicMock(
            return_value=mock_authenticated
        )
        mock_client.auth.return_value.__exit__ = MagicMock(return_value=False)
        mock_user = CasdoorUserFactory.build()
        mock_user.access_token = "test-token"

        gen = get_tasks_api(mock_client, mock_user)
        result = await gen.__anext__()
        assert result is mock_authenticated
        mock_client.auth.assert_called_once_with("test-token")


class TestGetPmmApi:
    """Test the ``get_pmm_api`` dependency."""

    @pytest.mark.asyncio
    async def test_returns_none_when_endpoint_not_configured(self):
        """Assert ``None`` is returned when PMM endpoint is not set."""
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.PMM.endpoint = None
            mock_settings.PMM.api_key = None
            result = await get_pmm_api()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_api_key_not_configured(self):
        """Assert ``None`` is returned when PMM API key is not set."""
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.PMM.endpoint = "https://pmm.example.com"
            mock_settings.PMM.api_key = None
            result = await get_pmm_api()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_client_when_configured(self):
        """Assert a ``PMMRemoteAPI`` is returned when PMM is configured."""
        mock_client = AsyncMock(spec=PMMRemoteAPI)
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.PMM.endpoint = "https://pmm.example.com"
            mock_settings.PMM.api_key = "secret-key"
            mock_settings.PMM.verify_ssl = True
            mock_settings.SSL_CAFILE = "/etc/ssl/ca.pem"
            mock_settings.get_remote_api = AsyncMock(return_value=mock_client)
            result = await get_pmm_api()
        assert result is mock_client
        mock_settings.get_remote_api.assert_awaited_once_with(
            PMMRemoteAPI,
            endpoint="https://pmm.example.com",
            api_key="secret-key",
            verify_ssl=True,
            ssl_cafile="/etc/ssl/ca.pem",
        )

    @pytest.mark.asyncio
    async def test_returns_client_when_configured_verify_ssl_false(self) -> None:
        """Assert ``verify_ssl=False`` is threaded through to ``get_remote_api``."""
        mock_client = AsyncMock(spec=PMMRemoteAPI)
        with patch("app.sep.deps.settings") as mock_settings:
            mock_settings.PMM.endpoint = "https://pmm.example.com"
            mock_settings.PMM.api_key = "secret-key"
            mock_settings.PMM.verify_ssl = False
            mock_settings.SSL_CAFILE = "/etc/ssl/ca.pem"
            mock_settings.get_remote_api = AsyncMock(return_value=mock_client)
            result = await get_pmm_api()
        assert result is mock_client
        mock_settings.get_remote_api.assert_awaited_once_with(
            PMMRemoteAPI,
            endpoint="https://pmm.example.com",
            api_key="secret-key",
            verify_ssl=False,
            ssl_cafile="/etc/ssl/ca.pem",
        )


class TestRequirePmmApi:
    """Test the ``require_pmm_api`` dependency."""

    @pytest.mark.asyncio
    async def test_returns_client_when_available(self) -> None:
        """Assert the PMM API client is returned when it is not ``None``."""
        mock_client = AsyncMock(spec=PMMRemoteAPI)
        result = await require_pmm_api(mock_client)
        assert result is mock_client

    @pytest.mark.asyncio
    async def test_raises_service_unavailable_when_none(self) -> None:
        """Assert ``HTTPServiceUnavailableException`` is raised when PMM is ``None``."""
        with pytest.raises(HTTPServiceUnavailableException) as exc:
            await require_pmm_api(None)
        assert exc.value.detail == "PMM is not configured"


class TestGetExecutorHosts:
    """Test get_executor_hosts dependency."""

    @pytest.mark.asyncio
    async def test_api_failure_returns_empty_dict(self) -> None:
        """Assert HTTPException from API returns empty dict and logs error."""
        request = _make_request()
        mock_api = AsyncMock()
        mock_api.get.side_effect = HTTPException(
            status_code=500, detail="Service unavailable"
        )
        result = await get_executor_hosts(request, mock_api)
        assert result == {}


class TestGetCreatedEntity:
    """Test get_created_entity dependency."""

    @pytest.mark.asyncio
    async def test_filter_mismatch_raises_value_error(self) -> None:
        """Assert mismatched filter raises ValueError."""
        node = CreatedNodeFactory.build()
        mock_api = AsyncMock()
        mock_api.get.return_value = node.model_dump()

        with pytest.raises(ValueError, match="address is not valid"):
            await get_created_entity(
                mock_api,
                SyncInventoryEntityTypeEnum.NODE,
                node.id,
                address="wrong-address",
            )


class TestGetCreatedNode:
    """Test get_created_node dependency."""

    @pytest.mark.asyncio
    async def test_delegates_to_get_created_entity(self) -> None:
        """Assert get_created_node fetches node via the correct entity path."""
        node = CreatedNodeFactory.build()
        mock_api = AsyncMock()
        mock_api.get.return_value = node.model_dump()

        result = await get_created_node(mock_api, node.id)
        assert isinstance(result, CreatedNode)
        mock_api.get.assert_called_once_with(f"/nodes/{node.id}")


class TestGetCreatedSchema:
    """Test get_created_schema dependency."""

    @pytest.mark.asyncio
    async def test_loads_node_when_missing(self) -> None:
        """Assert node is fetched when schema has node_id but no node object."""
        node = CreatedNodeFactory.build()
        service = CreatedServiceFactory.build(node_id=node.id, node=None)
        schema = CreatedSchemaFactory.build(service=service)
        mock_api = AsyncMock()

        schema_data = schema.model_dump()
        schema_data["service"]["node"] = None
        schema_data["service"]["node_id"] = node.id

        mock_api.get.side_effect = [
            schema_data,
            node.model_dump(),
        ]

        result = await get_created_schema(mock_api, schema.id)
        assert isinstance(result, CreatedSchema)
        assert result.service.node is not None
        assert result.service.node.id == node.id


class TestGetTaskByName:
    """Test get_task_by_name dependency."""

    @pytest.mark.asyncio
    async def test_validation_error_raises_not_found(self) -> None:
        """Assert ValidationError during model validation raises 404."""
        mock_api = AsyncMock()
        mock_api.get.return_value = {"invalid": "data"}

        with pytest.raises(HTTPNotFoundException):
            await get_task_by_name(mock_api, "test-task")

    @pytest.mark.asyncio
    async def test_owner_mismatch_raises_not_found(self) -> None:
        """Assert wrong owner raises 404."""
        task = TaskFactory.build(owner="BACKUPS")
        mock_api = AsyncMock()
        mock_api.get.return_value = task.model_dump(mode="json")

        with pytest.raises(HTTPNotFoundException):
            await get_task_by_name(mock_api, task.name, owner="ALTERS")

    @pytest.mark.asyncio
    async def test_matching_owner_returns_task(self) -> None:
        """Assert correct owner returns the task."""
        task = TaskFactory.build(owner="BACKUPS")
        mock_api = AsyncMock()
        mock_api.get.return_value = task.model_dump(mode="json")

        result = await get_task_by_name(mock_api, task.name, owner="BACKUPS")
        assert isinstance(result, Task)
        assert result.name == task.name


class TestGetTaskHistory:
    """Test get_task_history dependency."""

    @pytest.mark.asyncio
    async def test_validation_error_raises_not_found(self) -> None:
        """Assert ValidationError during model validation raises 404."""
        mock_api = AsyncMock()
        mock_api.get.return_value = {"invalid": "data"}

        with pytest.raises(HTTPNotFoundException):
            await get_task_history(mock_api, 1)

    @pytest.mark.asyncio
    async def test_owner_mismatch_raises_not_found(self) -> None:
        """Assert wrong owner raises 404."""
        task = TaskFactory.build(owner="BACKUPS")
        history_data = {
            "id": 1,
            "execution_request": {"tracking": {}},
            "status": TaskHistoryStatusEnum.SUCCESS,
            "started_at": None,
            "finished_at": None,
            "anonymize_mask": None,
            "task": task.model_dump(mode="json"),
            "executed_by": None,
        }
        mock_api = AsyncMock()
        mock_api.get.return_value = history_data

        with pytest.raises(HTTPNotFoundException):
            await get_task_history(mock_api, 1, owner="ALTERS")


class TestGetTasksContext:
    """Test get_tasks_context dependency."""

    @pytest.mark.asyncio
    async def test_basic_context(self, created_service, mock_remote_api) -> None:
        """Assert template context is assembled for task-dependent plugins."""
        task_data = {
            "name": "fakeTask",
            "id": 1,
            "created_by": None,
            "last_updated_by": None,
        }
        extra_data = {"success": True, "extra": "extra_data"}
        mock_remote_api.get = AsyncMock(
            side_effect=[
                {
                    "items": [created_service.model_dump()],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
                {"items": [task_data], "total": 1, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                [],
            ]
        )

        def get_task_info(_task):
            return extra_data

        executor_hosts_ctx = ExecutorHostsContext(
            hosts={"host1": "address1", "host2": "address2"},
            display_names={"address1": "DB Primary", "address2": "DB Replica"},
        )
        context = await get_tasks_context(
            mock_remote_api,
            mock_remote_api,
            get_task_info,
            executor_hosts_ctx,
            service_type=ServiceTypeEnum.MYSQL,
        )
        assert context["services"][0]["id"] == created_service.id
        assert context["executor_hosts"] == [
            {"value": "host1", "label": "DB Primary"},
            {"value": "host2", "label": "DB Replica"},
        ]
        assert len(context["tasks"]) == 1
        task = context["tasks"][0]
        assert task == task_data | extra_data

    @pytest.mark.asyncio
    @pytest.mark.parametrize("default_value", [True, False])
    async def test_exposes_connectivity_check_default(
        self, monkeypatch, default_value
    ) -> None:
        """Expose ``sep_settings.CONNECTIVITY_CHECK_DEFAULT`` in the template context."""
        monkeypatch.setattr(sep_settings, "CONNECTIVITY_CHECK_DEFAULT", default_value)
        mock_api = AsyncMock()
        mock_api.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                [],
            ]
        )
        executor_hosts_ctx = ExecutorHostsContext(hosts={}, display_names={})

        context = await get_tasks_context(
            mock_api,
            mock_api,
            lambda _: {},
            executor_hosts_ctx,
            service_type=ServiceTypeEnum.MYSQL,
        )

        assert context["connectivity_check_default"] is default_value

    @pytest.mark.asyncio
    async def test_status_branches(self) -> None:
        """Assert PENDING, RUNNING, and completed histories are categorized correctly."""
        mock_api = AsyncMock()
        task_data = {
            "name": "test-task",
            "id": 1,
            "created_by": None,
            "last_updated_by": None,
        }
        pending_hist = {
            "status": TaskHistoryStatusEnum.PENDING,
            "id": PENDING_HISTORY_ID,
        }
        running_hist = {
            "status": TaskHistoryStatusEnum.RUNNING,
            "id": RUNNING_HISTORY_ID,
        }
        success_hist = {
            "status": TaskHistoryStatusEnum.SUCCESS,
            "id": SUCCESS_HISTORY_ID,
        }

        mock_api.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [task_data], "total": 1, "offset": 0, "limit": 50},
                {
                    "items": [pending_hist, running_hist, success_hist],
                    "total": 3,
                    "offset": 0,
                    "limit": 50,
                },
                [],
            ]
        )

        executor_hosts_ctx = ExecutorHostsContext(hosts={}, display_names={})
        context = await get_tasks_context(
            mock_api,
            mock_api,
            lambda _: {},
            executor_hosts_ctx,
            service_type=ServiceTypeEnum.MYSQL,
        )
        assert len(context["pending_tasks"]) == 1
        assert context["pending_tasks"][0]["id"] == PENDING_HISTORY_ID
        assert len(context["running_tasks"]) == 1
        assert context["running_tasks"][0]["id"] == RUNNING_HISTORY_ID
        assert len(context["history_tasks"]) == 1
        assert context["history_tasks"][0]["id"] == SUCCESS_HISTORY_ID

    @pytest.mark.asyncio
    async def test_service_type_scopes_services_and_owner_filters_tasks(self) -> None:
        """Assert the ``/services/`` fetch scopes by ``service_type``, tasks by owner.

        Exercises AC6's ``get_tasks_context`` clause: a brand-new owner string no
        core module knows still round-trips, with the caller-supplied
        ``service_type`` driving the inventory fetch.
        """
        mock_api = AsyncMock()
        mock_api.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                [],
            ]
        )
        executor_hosts_ctx = ExecutorHostsContext(hosts={}, display_names={})

        await get_tasks_context(
            mock_api,
            mock_api,
            lambda _: {},
            executor_hosts_ctx,
            owner="CONTRACT_NEW_OWNER",
            service_type=ServiceTypeEnum.POSTGRESQL,
        )

        calls = mock_api.get.await_args_list
        services_call = next(call for call in calls if call.args[0] == "/services/")
        assert (
            services_call.kwargs["params"]["service_type"] == ServiceTypeEnum.POSTGRESQL
        )
        tasks_call = next(call for call in calls if call.args[0] == "/")
        assert tasks_call.kwargs["params"]["owner"] == "CONTRACT_NEW_OWNER"


class TestGetTasksIndexContext:
    """Test get_tasks_index_context dependency."""

    @pytest.mark.asyncio
    async def test_assembles_context(self) -> None:
        """Assert all API calls are made and context dict is structured correctly."""
        mock_inv_api = AsyncMock()
        mock_tasks_api = AsyncMock()
        mock_tasks_api.get = AsyncMock(
            side_effect=[
                {
                    "items": [{"id": 1, "status": "running"}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
                {
                    "items": [{"id": 2, "status": "pending"}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
                [{"task": "backup-task", "enabled": True}],
                {
                    "items": [{"name": "backup-task", "owner": "BACKUPS"}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
            ]
        )
        mock_inv_api.get = AsyncMock(
            return_value={"nodes": EXPECTED_NODE_COUNT, "services": 3}
        )

        default_context = {"user": "test"}
        executor_hosts_ctx = ExecutorHostsContext(
            hosts={"host1": "addr1"}, display_names={}
        )

        with patch("app.sep.deps.sep_settings") as mock_sep:
            mock_sep.APPS = []
            context = await get_tasks_index_context(
                mock_inv_api, mock_tasks_api, default_context, executor_hosts_ctx
            )

        assert "running_tasks" in context
        assert "pending_tasks" in context
        assert "periodic_tasks" in context
        assert "is_task_manager_enabled" in context
        assert context["is_task_manager_enabled"] is False
        assert context["nodes"] == EXPECTED_NODE_COUNT
        assert context["periodic_tasks"][0]["owner"] == "BACKUPS"

    @pytest.mark.asyncio
    async def test_task_manager_enabled(self) -> None:
        """Assert is_task_manager_enabled is True when Task Manager plugin has sidebar."""
        mock_inv_api = AsyncMock()
        mock_tasks_api = AsyncMock()
        mock_tasks_api.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                [],
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )
        mock_inv_api.get = AsyncMock(return_value={})

        mock_plugin = MagicMock()
        mock_plugin.name = "Task Manager"
        mock_plugin.sidebar = True

        executor_hosts_ctx = ExecutorHostsContext(hosts={}, display_names={})
        # The Task Manager flag now derives from the already-filtered plugin
        # list carried on the default context, not the raw settings.
        context = await get_tasks_index_context(
            mock_inv_api,
            mock_tasks_api,
            {"plugins": [mock_plugin]},
            executor_hosts_ctx,
        )

        assert context["is_task_manager_enabled"] is True

    @pytest.mark.asyncio
    async def test_task_manager_disabled_when_filtered_out(self) -> None:
        """Report False when Task Manager is absent from the filtered list."""
        mock_inv_api = AsyncMock()
        mock_tasks_api = AsyncMock()
        mock_tasks_api.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                [],
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )
        mock_inv_api.get = AsyncMock(return_value={})

        other_plugin = MagicMock()
        other_plugin.name = "Snippet Manager"
        other_plugin.sidebar = True

        executor_hosts_ctx = ExecutorHostsContext(hosts={}, display_names={})
        context = await get_tasks_index_context(
            mock_inv_api,
            mock_tasks_api,
            {"plugins": [other_plugin]},
            executor_hosts_ctx,
        )

        assert context["is_task_manager_enabled"] is False


class TestCheckForConflictedRunningTasks:
    """Test check_for_conflicted_running_tasks dependency."""

    @pytest.mark.asyncio
    async def test_conflict_raises_409(self) -> None:
        """Assert running task exists raises HTTPConflictException."""
        mock_api = AsyncMock()
        mock_api.get = AsyncMock(
            side_effect=[
                {
                    "items": [{"id": 1, "status": "running"}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )
        with pytest.raises(HTTPConflictException):
            await check_for_conflicted_running_tasks("test-task", mock_api)

    @pytest.mark.asyncio
    async def test_pending_conflict_raises_409(self) -> None:
        """Assert pending task exists raises HTTPConflictException."""
        mock_api = AsyncMock()
        mock_api.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {
                    "items": [{"id": 2, "status": "pending"}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
            ]
        )
        with pytest.raises(HTTPConflictException):
            await check_for_conflicted_running_tasks("test-task", mock_api)

    @pytest.mark.asyncio
    async def test_no_conflict_passes(self) -> None:
        """Assert no running or pending tasks does not raise."""
        mock_api = AsyncMock()
        mock_api.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )
        await check_for_conflicted_running_tasks("test-task", mock_api)


class TestRejectIfProtected:
    """Test the shared reject_if_protected check."""

    def test_protected_task_raises_edit_message(self) -> None:
        """Assert a protected task raises 409 with the default edit message."""
        task = TaskFactory.build(owner="BACKUPS", protected=True)
        with pytest.raises(HTTPConflictException) as exc_info:
            reject_if_protected(task)
        assert exc_info.value.detail == "Cannot edit a protected task."

    def test_protected_task_raises_delete_message(self) -> None:
        """Assert action='delete' yields the delete-specific 409 message."""
        task = TaskFactory.build(owner="ALTERS", protected=True)
        with pytest.raises(HTTPConflictException) as exc_info:
            reject_if_protected(task, action="delete")
        assert exc_info.value.detail == "Cannot delete a protected task."

    def test_unprotected_task_returns_same_task(self) -> None:
        """Assert an unprotected task is returned unchanged."""
        task = TaskFactory.build(owner="BACKUPS", protected=False)
        assert reject_if_protected(task) is task

    def test_protected_none_returns_task(self) -> None:
        """Assert a falsy/None protected flag does not raise."""
        task = TaskFactory.build(owner="BACKUPS")
        task.protected = None
        assert reject_if_protected(task, action="delete") is task


class TestProtectedTaskGuard:
    """Test the protected_task_guard dependency factory.

    These exercise the factory through real FastAPI dependency resolution: the
    built guard is mounted on a probe route so ``Depends(task_dep)`` actually
    resolves the supplied dependency. This validates that the factory is wired
    to ``task_dep`` (the mock is awaited), not just that the inner rejection
    body works.
    """

    @staticmethod
    def _build_client(
        task: Task, *, action: str = "edit"
    ) -> tuple[TestClient, list[bool]]:
        """Mount ``protected_task_guard(task_dep)`` on a probe route.

        Builds a real async ``task_dep`` that records each invocation, so the
        returned ``calls`` list proves FastAPI resolved the guard through
        ``Depends(task_dep)`` rather than the guard reaching the task by another
        path.

        :param task: The task the resolved dependency should return.
        :type task: Task
        :param action: The action verb forwarded to the guard factory.
        :type action: str
        :return: The test client and the per-request invocation record.
        :rtype: tuple[TestClient, list[bool]]
        """
        calls: list[bool] = []

        async def task_dep() -> Task:
            calls.append(True)
            return task

        guard = protected_task_guard(task_dep, action=action)
        app = FastAPI()

        @app.get("/probe")
        async def _probe(resolved: Annotated[Task, Depends(guard)]) -> dict[str, str]:
            return {"name": resolved.name}

        return TestClient(app), calls

    def test_guard_rejects_protected_task(self) -> None:
        """Assert the built dependency resolves task_dep then raises 409."""
        task = TaskFactory.build(owner="BACKUPS", protected=True)
        client, calls = self._build_client(task)
        response = client.get("/probe")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["detail"] == "Cannot edit a protected task."
        assert calls == [True]

    def test_guard_delete_verb(self) -> None:
        """Assert action='delete' propagates to the built dependency message."""
        task = TaskFactory.build(owner="ALTERS", protected=True)
        client, calls = self._build_client(task, action="delete")
        response = client.get("/probe")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["detail"] == "Cannot delete a protected task."
        assert calls == [True]

    def test_guard_passes_unprotected_task(self) -> None:
        """Assert the built dependency returns an unprotected task unchanged."""
        task = TaskFactory.build(owner="BACKUPS", protected=False)
        client, calls = self._build_client(task)
        response = client.get("/probe")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"name": task.name}
        assert calls == [True]


class TestExecutorHostsContext:
    """Test ExecutorHostsContext class."""

    def test_display_name_returns_inventory_name_when_match_exists(self) -> None:
        """Assert inventory name is returned when address matches."""
        hosts = {"nomad-node-1": "10.0.0.1", "nomad-node-2": "10.0.0.2"}
        display_names = {"10.0.0.1": "db-primary", "10.0.0.2": "db-replica"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        assert ctx.display_name("nomad-node-1") == "db-primary"

    def test_display_name_falls_back_to_nomad_name(self) -> None:
        """Assert nomad name is returned when no inventory match exists."""
        hosts = {"nomad-node-1": "10.0.0.1"}
        display_names = {}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        assert ctx.display_name("nomad-node-1") == "nomad-node-1"

    def test_display_name_falls_back_for_unknown_host(self) -> None:
        """Assert unknown host returns itself as display name."""
        ctx = ExecutorHostsContext(hosts={}, display_names={})
        assert ctx.display_name("unknown-host") == "unknown-host"

    def test_as_template_list_returns_sorted_dicts(self) -> None:
        """Assert template list is sorted by value with value/label keys."""
        hosts = {"beta-node": "10.0.0.2", "alpha-node": "10.0.0.1"}
        display_names = {"10.0.0.1": "Alpha DB", "10.0.0.2": "Beta DB"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        result = ctx.as_template_list()
        assert result == [
            {"value": "alpha-node", "label": "Alpha DB"},
            {"value": "beta-node", "label": "Beta DB"},
        ]

    def test_as_template_list_uses_nomad_name_as_fallback_label(self) -> None:
        """Assert nomad name is used as label when no inventory match."""
        hosts = {"nomad-node": "10.0.0.1"}
        display_names = {}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        result = ctx.as_template_list()
        assert result == [{"value": "nomad-node", "label": "nomad-node"}]

    def test_as_form_hosts_returns_frozenset_of_tuples(self) -> None:
        """Assert form hosts returns frozenset of (value, label) tuples."""
        hosts = {"nomad-node": "10.0.0.1"}
        display_names = {"10.0.0.1": "My DB"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        result = ctx.as_form_hosts()
        assert result == frozenset({("nomad-node", "My DB")})

    def test_as_host_metrics_returns_sorted_display_name_address_tuples(self) -> None:
        """Assert host metrics returns sorted (display_name, address) tuples."""
        hosts = {"beta-node": "10.0.0.2", "alpha-node": "10.0.0.1"}
        display_names = {"10.0.0.1": "Alpha DB", "10.0.0.2": "Beta DB"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        result = ctx.as_host_metrics()
        assert result == [("Alpha DB", "10.0.0.1"), ("Beta DB", "10.0.0.2")]

    def test_as_host_metrics_falls_back_to_nomad_name(self) -> None:
        """Assert host metrics uses nomad name when no inventory match."""
        hosts = {"nomad-node": "10.0.0.1"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names={})
        result = ctx.as_host_metrics()
        assert result == [("nomad-node", "10.0.0.1")]

    def test_with_host_adds_new_host(self) -> None:
        """Assert with_host returns new context with the additional host."""
        hosts = {"nomad-node": "10.0.0.1"}
        display_names = {"10.0.0.1": "My DB"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names=display_names)
        new_ctx = ctx.with_host("extra-host")
        result = new_ctx.as_template_list()
        values = [item["value"] for item in result]
        assert "extra-host" in values
        assert "nomad-node" in values

    def test_with_host_returns_same_when_host_exists(self) -> None:
        """Assert with_host returns same context when host already present."""
        hosts = {"nomad-node": "10.0.0.1"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names={})
        new_ctx = ctx.with_host("nomad-node")
        assert new_ctx is ctx

    def test_hosts_property_returns_raw_dict(self) -> None:
        """Assert hosts property returns the raw hosts dictionary."""
        hosts = {"node-1": "10.0.0.1"}
        ctx = ExecutorHostsContext(hosts=hosts, display_names={})
        assert ctx.hosts == hosts


class TestGetExecutorHostsContext:
    """Test get_executor_hosts_context dependency."""

    @pytest.mark.asyncio
    async def test_returns_enriched_context_when_inventory_succeeds(self) -> None:
        """Assert inventory node names are used as display names."""
        executor_hosts = {"nomad-1": "10.0.0.1", "nomad-2": "10.0.0.2"}
        inventory_nodes = {
            "items": [
                {"name": "db-primary", "address": "10.0.0.1"},
                {"name": "db-replica", "address": "10.0.0.2"},
            ],
            "total": 2,
            "offset": 0,
            "limit": 50,
        }
        mock_inventory_api = AsyncMock()
        mock_inventory_api.get = AsyncMock(return_value=inventory_nodes)

        ctx = await get_executor_hosts_context(executor_hosts, mock_inventory_api)
        assert ctx.display_name("nomad-1") == "db-primary"
        assert ctx.display_name("nomad-2") == "db-replica"
        mock_inventory_api.get.assert_called_once_with(
            "/nodes/", params={"offset": 0, "limit": MAX_PAGINATION_LIMIT}
        )

    @pytest.mark.asyncio
    async def test_returns_fallback_when_inventory_raises(self) -> None:
        """Assert fallback to nomad names when inventory API fails."""
        executor_hosts = {"nomad-1": "10.0.0.1"}
        mock_inventory_api = AsyncMock()
        mock_inventory_api.get = AsyncMock(
            side_effect=HTTPException(status_code=500, detail="unavailable")
        )

        ctx = await get_executor_hosts_context(executor_hosts, mock_inventory_api)
        assert ctx.display_name("nomad-1") == "nomad-1"
        assert ctx.hosts == executor_hosts

    @pytest.mark.asyncio
    async def test_matches_by_address(self) -> None:
        """Assert matching is done by address, not by node name."""
        executor_hosts = {"nomad-1": "10.0.0.1", "nomad-2": "10.0.0.2"}
        inventory_nodes = {
            "items": [{"name": "db-primary", "address": "10.0.0.1"}],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        mock_inventory_api = AsyncMock()
        mock_inventory_api.get = AsyncMock(return_value=inventory_nodes)

        ctx = await get_executor_hosts_context(executor_hosts, mock_inventory_api)
        assert ctx.display_name("nomad-1") == "db-primary"
        assert ctx.display_name("nomad-2") == "nomad-2"


class TestRequireBearerForUnsafeMethods:
    """Exercise the ``require_bearer_for_unsafe_methods`` dependency."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    async def test_safe_methods_pass_without_bearer(self, method: str) -> None:
        """Safe HTTP methods do not require a Bearer header."""
        request = _make_request(method=method)
        assert await require_bearer_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    async def test_unsafe_methods_without_bearer_raise_401(self, method: str) -> None:
        """Mutating methods without an Authorization header raise 401."""
        request = _make_request(method=method)
        with pytest.raises(HTTPUnauthorizedException) as exc_info:
            await require_bearer_for_unsafe_methods(request)
        assert "Bearer" in exc_info.value.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    async def test_unsafe_methods_with_bearer_pass(self, method: str) -> None:
        """Mutating methods with a Bearer header pass through."""
        request = _make_request(method=method, authorization="Bearer abc")
        assert await require_bearer_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_lowercase_bearer_scheme_passes(self) -> None:
        """Bearer detection is case-insensitive (existing helper contract)."""
        request = _make_request(method="POST", authorization="bearer abc")
        assert await require_bearer_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_basic_scheme_raises(self) -> None:
        """Non-Bearer Authorization schemes still raise 401 on mutating methods."""
        request = _make_request(method="POST", authorization="Basic abc")
        with pytest.raises(HTTPUnauthorizedException):
            await require_bearer_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_bearer_without_trailing_space_raises(self) -> None:
        """The helper requires ``Bearer `` (trailing space) to match."""
        request = _make_request(method="POST", authorization="Bearer")
        with pytest.raises(HTTPUnauthorizedException):
            await require_bearer_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_empty_authorization_header_raises(self) -> None:
        """An empty Authorization header is not a valid Bearer credential."""
        request = _make_request(method="POST", authorization="")
        with pytest.raises(HTTPUnauthorizedException):
            await require_bearer_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_bearer_with_empty_token_passes_gate(self) -> None:
        """``Bearer `` (trailing space, no token) passes the prefix-only gate.

        Token validation happens downstream in ``get_current_user``; the gate
        is intentionally a routing signal, not an auth check.
        """
        request = _make_request(method="POST", authorization="Bearer ")
        assert await require_bearer_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_safe_method_with_invalid_authorization_still_passes(self) -> None:
        """Safe methods bypass the gate regardless of Authorization contents."""
        request = _make_request(method="GET", authorization="garbage")
        assert await require_bearer_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_lowercase_method_treated_as_unsafe(self) -> None:
        """Method matching is case-sensitive; ``post`` is not in the safe set."""
        request = _make_request(method="post")
        with pytest.raises(HTTPUnauthorizedException):
            await require_bearer_for_unsafe_methods(request)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["TRACE", "CONNECT"])
    async def test_exotic_methods_are_unsafe(self, method: str) -> None:
        """Exotic HTTP methods (``TRACE``, ``CONNECT``) are not in the safe whitelist.

        Regression guard: the safe set is an explicit allow-list (GET/HEAD/OPTIONS).
        ASGI servers can route obscure verbs and a permissive deny-list would
        leak protocol-level metadata under cookie-only credentials.
        """
        request = _make_request(method=method)
        with pytest.raises(HTTPUnauthorizedException) as exc_info:
            await require_bearer_for_unsafe_methods(request)
        assert exc_info.value.detail == BEARER_REQUIRED_DETAIL

    @pytest.mark.asyncio
    async def test_empty_method_string_raises(self) -> None:
        """An empty method string is treated as unsafe.

        ASGI guarantees a non-empty method, but the gate must not silently
        accept an empty string if a future helper path bypasses Starlette.
        """
        request = _make_request(method="")
        with pytest.raises(HTTPUnauthorizedException):
            await require_bearer_for_unsafe_methods(request)


class TestMakeRequestHelper:
    """Pin invariants of the ``_make_request`` helper so the merge refactor is safe."""

    def test_default_method_is_get(self) -> None:
        """Calls without ``method`` produce a GET request (existing call-site contract)."""
        assert _make_request().method == "GET"

    @pytest.mark.parametrize(
        "method",
        ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    def test_explicit_method_set(self, method: str) -> None:
        """Explicit ``method`` flows through to ``request.method`` verbatim."""
        assert _make_request(method=method).method == method

    def test_authorization_header_omitted_when_none(self) -> None:
        """``authorization=None`` produces a request without an Authorization header."""
        assert "authorization" not in _make_request().headers

    def test_authorization_header_set_when_provided(self) -> None:
        """``authorization`` value is written verbatim into the header."""
        assert (
            _make_request(authorization="Bearer abc").headers["authorization"]
            == "Bearer abc"
        )

    def test_empty_string_authorization_set_literally(self) -> None:
        """``authorization=""`` produces a present-but-empty Authorization header.

        Several existing call sites rely on this boundary to exercise the empty-token
        rejection path; pin it explicitly.
        """
        assert _make_request(authorization="").headers["authorization"] == ""

    def test_state_messages_initialized(self) -> None:
        """``request.state.messages`` is initialized to an OrderedDict.

        Many call sites consume this state; the refactor must preserve it.
        """
        assert isinstance(_make_request().state.messages, OrderedDict)


class TestBearerHeaderEdgeCases:
    """Cover header-parsing edges for ``is_bearer_authenticated`` and the gates that wrap it.

    These tests pin the *current* permissive-prefix contract: the gate is a
    routing signal, not a credential check. Any future tightening (token shape,
    DoS bounds) should fail these tests visibly so it can't slip in silently.
    """

    def test_tab_separator_does_not_match(self) -> None:
        r"""``Bearer\ttoken`` does not match; the prefix requires a literal space."""
        request = _make_request(authorization="Bearer\ttoken")
        assert is_bearer_authenticated(request) is False

    def test_double_space_after_bearer_matches(self) -> None:
        """``Bearer  token`` (two spaces) still satisfies the prefix check.

        Documents the lenient prefix contract: anything after ``Bearer `` is the
        token payload — downstream validators (``oauth2_scheme``,
        ``get_current_user_api``) are responsible for token shape.
        """
        request = _make_request(authorization="Bearer  token")
        assert is_bearer_authenticated(request) is True

    def test_leading_whitespace_in_header_does_not_match(self) -> None:
        """`` Bearer token`` (leading space) is not a Bearer credential.

        Starlette does not strip leading whitespace from header values; the
        gate's ``startswith`` check is byte-faithful, so a leading space rejects.
        """
        request = _make_request(authorization=" Bearer token")
        assert is_bearer_authenticated(request) is False

    def test_mixed_case_scheme_matches(self) -> None:
        """The scheme match is case-insensitive (``BeArEr token`` is valid)."""
        request = _make_request(authorization="BeArEr token")
        assert is_bearer_authenticated(request) is True

    def test_very_long_header_does_not_crash(self) -> None:
        """A 64 KiB Authorization header is parsed without raising or hanging.

        DoS sanity check: the gate is a single ``str.startswith`` — adding token
        length validation later would need a different shape, so a regression
        introducing a quadratic scan would fail here.
        """
        long_token = "a" * (64 * 1024)
        request = _make_request(authorization=f"Bearer {long_token}")
        assert is_bearer_authenticated(request) is True

    def test_null_byte_in_token_passes_gate(self) -> None:
        r"""``Bearer \x00abc`` passes the gate; null-byte filtering is a downstream concern.

        Pinning permissive behaviour: the routing-signal gate is intentionally
        thin, so any future "block control characters" change is visible here
        rather than a silent behaviour shift.
        """
        request = _make_request(authorization="Bearer \x00abc")
        assert is_bearer_authenticated(request) is True

    def test_unicode_nbsp_separator_does_not_match(self) -> None:
        r"""``Bearer<NBSP>token`` does not match the ASCII prefix.

        Prevents a unicode-confusable bypass: a client crafting
        ``Bearer<NBSP>...`` cannot trick the gate into accepting a request that
        Starlette will then route to the safe codepath.
        """
        request = _make_request(authorization="Bearer\u00a0token")
        assert is_bearer_authenticated(request) is False

    def test_only_scheme_no_separator_does_not_match(self) -> None:
        """``Bearer`` alone (no trailing space) is not a Bearer credential."""
        request = _make_request(authorization="Bearer")
        assert is_bearer_authenticated(request) is False

    @pytest.mark.asyncio
    async def test_unsafe_methods_gate_propagates_nbsp_rejection(self) -> None:
        """End-to-end: NBSP-spoofed header on POST still 401s through the gate."""
        request = _make_request(method="POST", authorization="Bearer\u00a0token")
        with pytest.raises(HTTPUnauthorizedException) as exc_info:
            await require_bearer_for_unsafe_methods(request)
        assert exc_info.value.detail == BEARER_REQUIRED_DETAIL


class TestRequireAppEnabled:
    """Test the per-router app-state guard factory."""

    @pytest.mark.asyncio
    async def test_gate_passes_when_enabled(self, session) -> None:
        """Assert the gate returns ``None`` when the app is ``ENABLED``."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.ENABLED)
        )
        await session.commit()
        gate = require_app_enabled("snippets")
        assert await gate(session) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state",
        [
            AppLifecycleEnum.DISABLED,
            AppLifecycleEnum.DISABLING,
            AppLifecycleEnum.ENABLING,
        ],
    )
    async def test_gate_raises_503_for_non_enabled_states(self, session, state) -> None:
        """Assert the gate raises 503 whenever the app is not ``ENABLED``."""
        session.add(AppState(app_key="snippets", lifecycle_state=state))
        await session.commit()
        gate = require_app_enabled("snippets")
        with pytest.raises(HTTPServiceUnavailableException) as exc_info:
            await gate(session)
        assert "snippets" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_gate_passes_when_missing(self, session) -> None:
        """A missing row is treated as enabled (active until explicitly disabled)."""
        gate = require_app_enabled("snippets")
        assert await gate(session) is None

    def test_inventory_is_protected(self) -> None:
        """``inventory`` is the protected key the mount loops must skip."""
        assert "inventory" in PROTECTED_APP_KEYS

    @staticmethod
    def _dependent_registry() -> AppRegistry:
        """Build a two-app registry where ``dependent`` requires ``dep``."""
        return AppRegistry(
            [
                BaseApp(
                    key="dependent",
                    name="dependent",
                    display_name="dependent",
                    uri_path="/dependent",
                    requires_apps=("dep",),
                ),
                BaseApp(
                    key="dep",
                    name="dep",
                    display_name="dep",
                    uri_path="/dep",
                ),
            ]
        )

    @pytest.mark.asyncio
    async def test_gate_503_when_dependency_disabled(self, session) -> None:
        """Assert the gate 503s on the dependent's key when a required app is disabled."""
        session.add(AppState(app_key="dep", lifecycle_state=AppLifecycleEnum.DISABLED))
        await session.commit()
        with patch(
            "app.sep.apps.framework.registry.get_app_registry",
            return_value=self._dependent_registry(),
        ):
            gate = require_app_enabled("dependent")
            with pytest.raises(HTTPServiceUnavailableException) as exc_info:
                await gate(session)
        assert "dependent" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_gate_passes_when_dependency_enabled(self, session) -> None:
        """Assert the gate passes when both the app and its dependency are enabled."""
        with patch(
            "app.sep.apps.framework.registry.get_app_registry",
            return_value=self._dependent_registry(),
        ):
            gate = require_app_enabled("dependent")
            assert await gate(session) is None

    @pytest.mark.asyncio
    async def test_gate_fail_open_on_db_error(self, session) -> None:
        """Assert a DB read failure degrades to allowing the request (fail-open)."""
        with patch.object(
            AppStateManager,
            "all_lifecycle_states",
            side_effect=SQLAlchemyError("db down"),
        ):
            gate = require_app_enabled("snippets")
            assert await gate(session) is None


class TestGetToggleableAppKey:
    """Test app-key resolver used by the app-state toggle endpoint."""

    def test_returns_key_for_toggleable_configured_app(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A configured, non-protected key resolves to itself."""
        monkeypatch.setattr(
            "app.sep.apps.framework.registry.get_app_registry",
            lambda: build_app_registry(
                [
                    App(name="Inventory", module_name="inventory"),
                    App(name="Snippet Manager", module_name="snippets"),
                ]
            ),
        )
        assert get_toggleable_app_key("snippets") == "snippets"

    def test_protected_key_raises_conflict(self) -> None:
        """A protected key raises 409 -- it can never be toggled."""
        with pytest.raises(HTTPConflictException):
            get_toggleable_app_key("inventory")

    def test_unknown_key_raises_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unconfigured key raises 404."""
        monkeypatch.setattr(
            "app.sep.apps.framework.registry.get_app_registry",
            lambda: build_app_registry(
                [App(name="Snippet Manager", module_name="snippets")]
            ),
        )
        with pytest.raises(HTTPNotFoundException):
            get_toggleable_app_key("unknown")


class TestGetDefaultContextPluginFiltering:
    """Test that ``get_default_context`` filters the sidebar by app state."""

    @staticmethod
    def _plugins() -> list[App]:
        """Build a representative inventory + two non-protected plugins."""
        return [
            App(name="Inventory", module_name="inventory"),
            App(name="Snippet Manager", module_name="snippets"),
            App(name="Checksums", module_name="checksums"),
        ]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("mock_get_username_mapping")
    @pytest.mark.parametrize(
        "excluded_state",
        [
            AppLifecycleEnum.DISABLED,
            AppLifecycleEnum.DISABLING,
            AppLifecycleEnum.ENABLING,
        ],
    )
    async def test_enabled_plugin_included_non_enabled_excluded(
        self, session, dummy_request, regular_user, excluded_state
    ) -> None:
        """Only protected apps plus ``ENABLED`` non-protected apps reach the sidebar."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.ENABLED)
        )
        session.add(AppState(app_key="checksums", lifecycle_state=excluded_state))
        await session.commit()

        with (
            patch(
                "app.sep.apps.framework.registry.get_app_registry",
                return_value=build_app_registry(self._plugins()),
            ),
            patch("app.sep.deps.settings"),
        ):
            context = await get_default_context(
                dummy_request, regular_user, None, session
            )

        keys = {p.key for p in context["plugins"]}
        assert keys == {"inventory", "snippets"}

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("mock_get_username_mapping")
    async def test_inventory_always_present_even_when_row_disabled(
        self, session, dummy_request, regular_user
    ) -> None:
        """A protected app stays in the sidebar regardless of any DB row."""
        session.add(
            AppState(app_key="inventory", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()

        with (
            patch(
                "app.sep.apps.framework.registry.get_app_registry",
                return_value=build_app_registry(self._plugins()),
            ),
            patch("app.sep.deps.settings"),
        ):
            context = await get_default_context(
                dummy_request, regular_user, None, session
            )

        keys = {p.key for p in context["plugins"]}
        assert "inventory" in keys

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("mock_get_username_mapping")
    async def test_missing_row_includes_plugin(
        self, session, dummy_request, regular_user
    ) -> None:
        """A configured plugin with no DB row is shown (missing -> enabled)."""
        with (
            patch(
                "app.sep.apps.framework.registry.get_app_registry",
                return_value=build_app_registry(self._plugins()),
            ),
            patch("app.sep.deps.settings"),
        ):
            context = await get_default_context(
                dummy_request, regular_user, None, session
            )

        keys = {p.key for p in context["plugins"]}
        assert keys == {"inventory", "snippets", "checksums"}

    @staticmethod
    def _dependent_registry() -> AppRegistry:
        """Build a registry where ``dependent`` requires ``snippets``."""
        return AppRegistry(
            [
                BaseApp(
                    key="inventory",
                    name="inventory",
                    display_name="Inventory",
                    uri_path="/inventory",
                ),
                BaseApp(
                    key="snippets",
                    name="snippets",
                    display_name="Snippets",
                    uri_path="/snippets",
                ),
                BaseApp(
                    key="dependent",
                    name="dependent",
                    display_name="Dependent",
                    uri_path="/dependent",
                    requires_apps=("snippets",),
                ),
            ]
        )

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("mock_get_username_mapping")
    async def test_app_hidden_when_dependency_disabled(
        self, session, dummy_request, regular_user
    ) -> None:
        """Assert an app is dropped from the sidebar when a required app is disabled."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()
        with (
            patch(
                "app.sep.apps.framework.registry.get_app_registry",
                return_value=self._dependent_registry(),
            ),
            patch("app.sep.deps.settings"),
        ):
            context = await get_default_context(
                dummy_request, regular_user, None, session
            )

        keys = {p.key for p in context["plugins"]}
        assert "dependent" not in keys
        assert "snippets" not in keys
        assert "inventory" in keys

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("mock_get_username_mapping")
    async def test_app_shown_when_dependency_enabled(
        self, session, dummy_request, regular_user
    ) -> None:
        """Assert an app stays in the sidebar when its dependency is enabled (missing row)."""
        with (
            patch(
                "app.sep.apps.framework.registry.get_app_registry",
                return_value=self._dependent_registry(),
            ),
            patch("app.sep.deps.settings"),
        ):
            context = await get_default_context(
                dummy_request, regular_user, None, session
            )

        keys = {p.key for p in context["plugins"]}
        assert {"inventory", "snippets", "dependent"} <= keys

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("mock_get_username_mapping")
    async def test_alert_troubleshooting_hidden_when_snippets_disabled(
        self, session, dummy_request, regular_user
    ) -> None:
        """Drop Alert Troubleshooting from the sidebar when snippets is disabled."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()

        with patch("app.sep.deps.settings"):
            context = await get_default_context(
                dummy_request, regular_user, None, session
            )

        keys = {p.key for p in context["plugins"]}
        assert "alert_troubleshooting" not in keys
        assert "snippets" not in keys

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("mock_get_username_mapping")
    async def test_db_failure_degrades_to_showing_all_apps(
        self, session, dummy_request, regular_user
    ) -> None:
        """Assert a DB read failure shows every app so the page (and error pages) render."""
        with (
            patch(
                "app.sep.apps.framework.registry.get_app_registry",
                return_value=build_app_registry(self._plugins()),
            ),
            patch("app.sep.deps.settings"),
            patch.object(
                AppStateManager,
                "all_lifecycle_states",
                side_effect=SQLAlchemyError("db down"),
            ),
        ):
            context = await get_default_context(
                dummy_request, regular_user, None, session
            )

        keys = {p.key for p in context["plugins"]}
        assert keys == {"inventory", "snippets", "checksums"}
