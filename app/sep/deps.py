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

"""Define SEP dependencies."""

import hmac
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from typing import Annotated, Any
from zoneinfo import available_timezones

import aiohttp
from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from app import __summary__, __version__
from app.api.deps import get_current_user as get_current_user_api
from app.api.deps import oauth2_scheme
from app.core.alerts.config import alert_settings
from app.core.auth import config as auth_config
from app.core.auth.base import BaseAuthProvider
from app.core.auth.exceptions import HTTPForbiddenException, HTTPUnauthorizedException
from app.core.auth.models import OAuthToken, SessionExchangeTokenResponse
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPNotFoundException,
    HTTPRedirectException,
    HTTPServiceUnavailableException,
)
from app.core.log import set_log_context
from app.core.pagination import fetch_all_dict_items
from app.core.requests import RemoteAPI
from app.core.security import crypto_timestamp_serializer
from app.core.utils.fields import URL
from app.inventory.config import inventory_settings
from app.inventory.models import ServiceTypeEnum
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.config import sep_settings
from app.sep.connectivity import (
    annotate_tasks_with_connectivity,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
    CONNECTIVITY_TARGET_KEY,
    get_check_connectivity_flag,
)
from app.sep.crud import AppStateManager
from app.sep.db import get_async_session_maker
from app.sep.exceptions import LoginRedirectException
from app.sep.inventory import (
    CreatedEntity,
    CreatedNode,
    CreatedSchema,
    CreatedService,
    CreatedTable,
    ENTITY_MAPPING,
)
from app.sep.middleware import messages
from app.sep.middleware.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_FORM_FIELD,
    request_has_bearer_authorization,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.config import tasks_settings
from app.tasks.models import (
    Task,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
)

logger = logging.getLogger(__name__)
User = get_user_model()
AVAILABLE_TIMEZONES = sorted(available_timezones())


def get_base_url(request: Request) -> URL:
    """Return the application's base URL.

    If the `BASE_URL` setting is defined, returns it. Otherwise, the function extracts
    the base URL from an incoming request by removing the path.

    :param request: The HTTP request object from which the base URL is derived.
    :type request: Request
    :return: The base URL with the path removed.
    :rtype: Any
    """
    if settings.BASE_URL is not None:
        return settings.BASE_URL
    return request.url.replace(path="", query="", fragment="")


BaseURL = Annotated[URL, Depends(get_base_url)]


def get_access_token_from_cookie(
    request: Request,
) -> str:
    """Retrieve and verify the access token from a session cookie.

    Extracts the signed access token from the request cookies, verifies it, and
    returns the unsigned token. If verification fails, raises a login
    redirect exception.

    :param request: The HTTP request containing the session cookie.
    :type request: Request
    :return: The verified and unsigned access token.
    :rtype: str
    :raises LoginRedirectException: If the token is invalid or cannot be
        verified due to a `BadSignature`.
    """
    signed_access_token = request.cookies.get(sep_settings.SESSION.COOKIE_NAME, "")
    try:
        return crypto_timestamp_serializer.loads(
            signed_access_token,
            max_age=sep_settings.SESSION.MAX_AGE.total_seconds(),
        )
    except BadSignature:
        logger.debug("Failed to unsign token")
        raise LoginRedirectException(request) from None


AccessTokenCookie = Annotated[str, Depends(get_access_token_from_cookie)]


async def get_current_user_from_cookie(request: Request) -> User:
    """Return the authenticated user from the signed session cookie.

    Loads and verifies the session cookie, decodes the JWT into a user, and
    rejects inactive accounts with a login redirect (legacy Jinja2 behavior).

    :param request: The incoming HTTP request.
    :type request: Request
    :return: The authenticated user.
    :rtype: User
    :raises LoginRedirectException: If the cookie or JWT is invalid or the user
        is inactive.
    """
    token = get_access_token_from_cookie(request)
    try:
        user = await User.from_jwt(token)
    except (BadSignature, ValidationError) as exc:
        logger.debug("Failed to authenticate user: %s", exc, exc_info=True)
        raise LoginRedirectException(request) from None
    if not user.is_active:
        logger.debug("User %s is not active", user.username)
        # TODO: Message on inactive  # noqa: TD002, TD003
        raise LoginRedirectException(request)
    set_log_context(user=user.username)
    return user


def is_bearer_authenticated(request: Request) -> bool:
    """Return whether the request carries an ``Authorization: Bearer`` header.

    Inspects only the ``Authorization`` header prefix — the token itself is not
    validated. Intended as a routing signal to pick between Bearer and cookie
    authentication, and to render API-style error responses for SPA clients.

    :param request: The incoming HTTP request.
    :type request: Request
    :return: ``True`` when the header starts with ``Bearer ``, ``False`` otherwise.
    :rtype: bool
    """
    return request.headers.get("authorization", "").lower().startswith("bearer ")


async def get_current_user(
    request: Request,
) -> User:
    """Return the authenticated user from a Bearer token or session cookie.

    The ``Authorization: Bearer`` header is tried first (React SPA) and, when
    present, failures from :func:`app.api.deps.get_current_user` are raised as
    HTTP API errors (401/403) rather than converted into a login redirect —
    including the case of a malformed/empty Bearer token. When the header is
    absent, authentication falls back to the signed session cookie (legacy
    Jinja2).

    :param request: The incoming HTTP request.
    :type request: Request
    :return: The authenticated user.
    :rtype: User
    :raises HTTPUnauthorizedException: If a Bearer token is present but invalid.
    :raises HTTPForbiddenException: If the user resolved from Bearer is inactive.
    :raises LoginRedirectException: If cookie-based auth fails or the cookie user
        is inactive.
    """
    if is_bearer_authenticated(request):
        bearer_token = await oauth2_scheme(request)
        return await get_current_user_api(bearer_token)

    return await get_current_user_from_cookie(request)


IsAuthenticated = Depends(get_current_user)
CurrentUser = Annotated[User, IsAuthenticated]


async def get_api_authenticated_user(request: Request) -> User:
    """Return the authenticated user for API surfaces.

    Wrap :func:`get_current_user` so cookie-based API callers receive an
    ``HTTPUnauthorizedException`` (401) instead of the
    ``LoginRedirectException`` (303) used by Jinja pages. The
    ``set-cookie`` header that ``LoginRedirectException`` uses to clear a
    stale session cookie is preserved on the 401 response so the invalid
    cookie does not linger on the client. Bearer-token failures from
    :func:`get_current_user` (``HTTPUnauthorizedException`` /
    ``HTTPForbiddenException``) propagate unchanged.

    :param request: The incoming HTTP request.
    :type request: Request
    :return: The authenticated user.
    :rtype: User
    :raises HTTPUnauthorizedException: If cookie-based authentication fails
        (converted from :class:`LoginRedirectException`), or if a Bearer
        token is missing or invalid.
    :raises HTTPForbiddenException: If the user resolved from the Bearer
        token is inactive.
    """
    try:
        return await get_current_user(request)
    except HTTPRedirectException as exc:
        unauthorized = HTTPUnauthorizedException()
        if "set-cookie" in exc.headers:
            unauthorized.headers = {"set-cookie": exc.headers["set-cookie"]}
        raise unauthorized from None


IsApiAuthenticated = Depends(get_api_authenticated_user)
ApiCurrentUser = Annotated[User, IsApiAuthenticated]


BEARER_REQUIRED_DETAIL = "Bearer authentication required for state-changing requests."


async def require_bearer_for_unsafe_methods(request: Request) -> None:
    """Require a Bearer Authorization header on mutating HTTP methods.

    Cookie-authenticated mutations would bypass CSRF protection because
    :func:`validate_csrf` operates on form-body fields and JSON requests
    carry no form body. Browsers never attach an ``Authorization`` header
    automatically, so requiring a Bearer token on mutating routes blocks
    cross-site JSON POSTs from a malicious origin. ``GET``, ``HEAD`` and
    ``OPTIONS`` pass through (cookie-authenticated SSR reads and CORS
    preflights are unaffected). ``POST``, ``PUT``, ``PATCH`` and ``DELETE``
    require ``Authorization: Bearer ...``; cookie-authenticated cross-site
    JSON mutations are rejected with ``401`` before any business logic runs.

    Intended to be attached at router level to ``/api/apps/*`` so every
    plugin's JSON mutation routes inherit the guard uniformly.

    :param request: The incoming HTTP request.
    :type request: Request
    :raises HTTPUnauthorizedException: When the method is unsafe and the
        request lacks an ``Authorization: Bearer`` header.
    """
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not is_bearer_authenticated(request):
        raise HTTPUnauthorizedException(detail=BEARER_REQUIRED_DETAIL)


RequireBearerForUnsafeMethods = Depends(require_bearer_for_unsafe_methods)


async def get_current_admin(current_user: CurrentUser) -> User:
    """Return the authenticated admin.

    :param current_user: The current logged-in user.
    :type current_user: CurrentUser
    :return: The authenticated admin user.
    :rtype: User
    :raises HTTPForbiddenException: If the user is not an admin.
    """
    if not current_user.is_admin:
        raise HTTPForbiddenException
    return current_user


IsAdminDep = Depends(get_current_admin)
AdminUser = Annotated[User, IsAdminDep]


async def get_api_authenticated_admin(api_user: ApiCurrentUser) -> User:
    """Return the authenticated API admin user.

    Mirror :func:`get_current_admin` but ride on the API auth path
    (:func:`get_api_authenticated_user`) so failures surface as 401 / 403
    JSON responses rather than the cookie-based 303 redirect to the login
    page.

    :param api_user: The current API-authenticated user.
    :type api_user: ApiCurrentUser
    :return: The authenticated admin user.
    :rtype: User
    :raises HTTPForbiddenException: If the user is not an admin.
    """
    if not api_user.is_admin:
        raise HTTPForbiddenException
    return api_user


IsApiAdmin = Depends(get_api_authenticated_admin)
ApiAdminUser = Annotated[User, IsApiAdmin]


async def redirect_if_user_is_authenticated(request: Request) -> None:
    """Redirect authenticated users to homepage.

    This dependency function checks if the session cookie is set in the request and,
    if so, redirects the authenticated user to the homepage.

    :param request: The HTTP request object.
    :type request: Request
    :raises HTTPRedirectException: If the session cookie is set.
    """
    if request.cookies.get(sep_settings.SESSION.COOKIE_NAME):
        raise HTTPRedirectException("/", status_code=status.HTTP_303_SEE_OTHER)


IsNotAuthenticated = Depends(redirect_if_user_is_authenticated)


def _ambient_session_provider() -> BaseAuthProvider | None:
    """Return the active auth provider when ambient-session auth is available.

    :return: The active provider, or ``None`` when ambient SSO is disabled or the
        provider carries no ambient session.
    """
    if not sep_settings.AMBIENT_SESSION_SSO_ENABLED:
        return None
    provider = auth_config.get_active_auth_provider()
    return provider if provider.supports_ambient_session else None


async def resolve_ambient_session_token(request: Request) -> OAuthToken | None:
    """Resolve an ambient provider session on the request into a SEP token pair.

    A no-op (``None``) unless ambient SSO is enabled and the active auth provider
    supports ambient sessions. Operational or upstream failures are logged and
    swallowed so auto-login degrades silently to the login form; a rejected
    session (upstream 401) likewise resolves to ``None`` in the provider.

    :param request: The incoming request, whose provider session cookie carries
        the ambient session.
    :return: A minted ``OAuthToken`` on a valid ambient session, else ``None``.
    """
    provider = _ambient_session_provider()
    if provider is None:
        return None
    try:
        return await provider.resolve_ambient_session(request.cookies)
    except HTTPException:
        logger.warning(
            "Ambient auto-login failed (upstream/operational); "
            "falling back to the login form.",
            exc_info=True,
        )
        return None


async def resolve_ambient_exchange_token(
    request: Request,
) -> SessionExchangeTokenResponse | None:
    """Resolve an ambient provider session on the request into a short-lived bearer.

    Gate on the same ambient-session availability as
    :func:`resolve_ambient_session_token`, and swallow upstream failures the same
    way, so an absent session, a rejected session, and a provider outage are
    indistinguishable to the caller and all deny.

    :param request: The incoming request, whose provider session cookie carries
        the ambient session.
    :return: The minted bearer on a valid ambient session, else ``None``.
    """
    provider = _ambient_session_provider()
    if provider is None:
        return None
    try:
        return await provider.exchange_ambient_session(request.cookies)
    except HTTPException:
        logger.warning(
            "Ambient session exchange failed (upstream/operational); denying.",
            exc_info=True,
        )
        return None


async def validate_csrf(request: Request) -> None:
    """Validate the CSRF token submitted in the request form data.

    Requests with ``Authorization: Bearer ...`` that do *not* also carry a
    session cookie skip CSRF validation; Bearer tokens are not sent
    automatically by browsers, so CSRF protection is not required for that
    path (authentication is enforced separately).  When a session cookie is
    also present the request is treated as cookie-authenticated and CSRF
    validation is enforced normally, regardless of any Bearer header.

    For authenticated requests (session cookie present), verify the HMAC
    signature using the session cookie as salt.  For unauthenticated requests
    (login page), verify using a double-submit cookie comparison plus
    signature verification.

    :param request: The HTTP request object.
    :type request: Request
    :raises HTTPBadRequestException: If the CSRF token is missing from the
        form data.
    :raises HTTPForbiddenException: If the CSRF token fails validation.
    """
    session_cookie = request.cookies.get(sep_settings.SESSION.COOKIE_NAME)
    if request_has_bearer_authorization(request) and not session_cookie:
        return

    form_data = await request.form()
    form_token = str(form_data.get(CSRF_FORM_FIELD, ""))
    if not form_token:
        raise HTTPBadRequestException(detail="Missing CSRF token.")

    max_age = int(sep_settings.SESSION.MAX_AGE.total_seconds())

    if session_cookie:
        try:
            crypto_timestamp_serializer.loads(
                form_token, salt=session_cookie, max_age=max_age
            )
        except BadSignature:
            raise HTTPForbiddenException(detail="CSRF validation failed.") from None
    else:
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        if not csrf_cookie or not hmac.compare_digest(form_token, csrf_cookie):
            raise HTTPForbiddenException(detail="CSRF validation failed.")
        try:
            crypto_timestamp_serializer.loads(form_token, max_age=max_age)
        except BadSignature:
            raise HTTPForbiddenException(detail="CSRF validation failed.") from None


IsCsrfValidated = Depends(validate_csrf)


async def get_username_mapping() -> dict[str, str]:
    """Create a mapping from user ID to username using the active auth provider.

    Fetch all users from the active provider and map each user's ID to their
    username. Caching should be implemented in the provider's SDK to avoid
    repeated API calls.

    :return: A dictionary mapping user IDs to usernames.
    """
    try:
        users = await User.get_users()
        return {str(user.id): user.username for user in users}
    except (
        AttributeError,
        TimeoutError,
        ValueError,
        KeyError,
        HTTPException,
        aiohttp.ClientError,
    ):
        logger.exception("Failed to get username mapping from the auth provider")
        return {}


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an asynchronous database session for FastAPI routes.

    This function provides a dependency for FastAPI routes that yields an ``AsyncSession``
    for interacting with the database. The session is properly closed after use.

    :yield: An asynchronous session for database operations.
    :rtype: AsyncSession
    """
    async_session_maker = get_async_session_maker()
    async with async_session_maker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


PROTECTED_APP_KEYS: frozenset[str] = frozenset({"inventory"})
"""Apps that cannot be disabled at runtime.

These are foundational to SEP and are excluded from every plugin-state
mechanism: never seeded, never guarded, always present in the sidebar, and the
toggle endpoint returns 409 for them. The frozenset is the single source of
truth -- the seed, both mount loops, the default-context filter, and both
admin endpoints all consult it.

The parallel exclusion category is a **child app** (``parent_key`` set): it too
is never seeded and cannot be toggled independently (the toggle endpoint returns
409), but -- unlike a protected app -- its runtime state is not forced on; it
*derives* from its parent's ``AppState`` via :attr:`BaseApp.state_key`, so its
mount gate, sidebar visibility, and admin lifecycle all follow the parent. Every
consumer that special-cases a protected key also carries a ``parent_key`` branch.
"""


def require_app_enabled(app_key: str) -> Callable[[AsyncSession], Awaitable[None]]:
    """Build a route-level dependency that gates requests by app state.

    Used as ``dependencies=[Depends(require_app_enabled(<key>))]`` on each
    non-protected app's router at mount time. Raises
    :class:`app.core.exceptions.HTTPServiceUnavailableException` (HTTP 503) when
    the app is not *effectively* enabled -- that is, when its own
    :class:`app.sep.models.AppState` is disabled **or** any app it declares in
    ``requires_apps`` is disabled. Resolution is delegated to
    :meth:`AppRegistry.resolve_effective_enabled`, the single source of truth
    shared with the sidebar filter and the ``GET /api/apps`` projection, so the
    gate is passed the app's ``key`` (not ``state_key``) to resolve dependencies.

    The factory closure-captures ``app_key`` at router-mount time; the returned
    coroutine is invoked per request and queries the DB via the standard
    :data:`SessionDep` dependency. Callers must not invoke this factory for keys
    in :data:`PROTECTED_APP_KEYS` -- the mount loops enforce that skip.

    A failed app-state read degrades to ENABLED rather than failing the request:
    a configured plugin stays reachable when the DB is unreachable (or the
    ``appstate`` table is missing), mirroring :func:`get_default_context`. This
    is fail-open by design -- the gate is an operator convenience, not a security
    boundary, so a transient DB fault must not 500 every guarded route.

    :param app_key: The plugin module key to gate on.
    :type app_key: str
    :return: A FastAPI dependency coroutine that raises 503 when disabled.
    :rtype: Callable[[AsyncSession], Awaitable[None]]
    """

    async def _gate(session: SessionDep) -> None:
        # Deferred: the framework package __init__ imports back into this module,
        # so a top-level import here would cycle.
        from app.sep.apps.framework.registry import get_app_registry

        try:
            states = await AppStateManager.all_lifecycle_states(session)
        except SQLAlchemyError:
            logger.warning(
                "Could not read app state for '%s'; allowing the request.",
                app_key,
                exc_info=True,
            )
            return
        if not get_app_registry().resolve_effective_enabled(app_key, states):
            raise HTTPServiceUnavailableException(
                detail=f"App '{app_key}' is currently disabled.",
            )

    return _gate


def get_toggleable_app_key(app_key: str) -> str:
    """Resolve a toggleable, configured app key.

    :param app_key: The plugin key from the path parameter.
    :return: The validated app key.
    :raises HTTPConflictException: If the key is protected, or a child app whose
        state is managed by its parent -- neither can be toggled independently.
    :raises HTTPNotFoundException: If the key is not in configured plugins.
    """
    if app_key in PROTECTED_APP_KEYS:
        raise HTTPConflictException(
            detail=f"App '{app_key}' is protected and cannot be disabled.",
        )
    # Deferred: the framework package __init__ imports back into this module,
    # so a top-level import here would cycle.
    from app.sep.apps.framework.registry import get_app_registry

    app = get_app_registry().get(app_key)
    if app is None:
        raise HTTPNotFoundException(detail="App not found")
    if app.parent_key is not None:
        raise HTTPConflictException(
            detail=f"App '{app_key}' is managed by its parent "
            f"'{app.parent_key}' and cannot be toggled independently.",
        )
    return app_key


ToggleableAppKeyDep = Annotated[str, Depends(get_toggleable_app_key)]


def render_footer_text() -> str:
    """Render the sidebar footer text from the live ``FOOTER_TEMPLATE`` setting.

    Read :attr:`sep_settings.FOOTER_TEMPLATE` per call (it is a hot,
    materializer-backed setting) so a live ``SEP__FOOTER_TEMPLATE`` override is
    reflected without restarting the application. This is the single source of
    truth shared by the Jinja default context and the JSON app-info endpoint so
    the two frontends cannot drift.

    :return: The rendered footer text (application summary and version by default).
    """
    return sep_settings.FOOTER_TEMPLATE.safe_substitute(
        version=__version__, summary=__summary__
    )


async def get_default_context(
    request: Request,
    user: CurrentUser,
    base_uri: BaseURL,
    session: SessionDep,
) -> dict[str, Any]:
    """Return the default context for templates.

    The sidebar ``plugins`` list is filtered by *effective* app state via
    :meth:`AppRegistry.resolve_effective_enabled`: protected apps always pass
    through; every other app is shown only when its own
    :class:`app.sep.models.AppState` row is ``ENABLED`` (a missing row is treated
    as enabled) **and** every app it declares in ``requires_apps`` is itself
    effectively enabled. A child app owns no row, so it resolves through its
    parent via :attr:`~app.sep.apps.framework.base.BaseApp.state_key`. This
    shares the one resolver used by the mount gate and the JSON app listing.

    :param request: The HTTP request object.
    :param user: The authenticated user.
    :param base_uri: The base URI of the application.
    :param session: The database session used to read app state.
    :return: The default context.
    """
    try:
        states = await AppStateManager.all_lifecycle_states(session)
    except SQLAlchemyError:
        # Error pages rebuild this context from a fresh session; keep them
        # renderable when the DB is down.
        logger.warning(
            "Could not read app state; rendering all apps in the sidebar.",
            exc_info=True,
        )
        states = {}
    # Deferred: the framework package __init__ imports back into this module,
    # so a top-level import here would cycle.
    from app.sep.apps.framework.registry import get_app_registry

    registry = get_app_registry()
    memo: dict[str, bool] = {}
    plugins = [
        app
        for app in registry
        if registry.resolve_effective_enabled(app.key, states, memo)
    ]
    return {
        "user": user,
        "base_uri": base_uri,
        "plugins": plugins,
        "sync_refresh_time": sep_settings.SYNC_REFRESH_TIME,
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "pmm_url": settings.PMM.frontend,
        "footer_text": render_footer_text(),
        "user_id_to_username": await get_username_mapping(),
    }


DefaultContext = Annotated[dict[str, Any], Depends(get_default_context)]

CheckConnectivityFlag = Annotated[bool, Depends(get_check_connectivity_flag)]


async def get_inventory_client(request: Request) -> RemoteAPI:
    """Construct a `RemoteAPI` instance for interacting with the Inventory API.

    :param request: The HTTP request object.
    :type request: Request
    :return: An instance of `RemoteAPI` configured for the Inventory service, including
        the endpoint, API key, and SSL settings.
    :rtype: RemoteAPI
    """
    return getattr(
        request.app.state, "inventory_api", None
    ) or await settings.get_remote_api(
        endpoint=sep_settings.INVENTORY_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
        logger_name="inventory_api",
    )


InventoryClient = Annotated[RemoteAPI, Depends(get_inventory_client)]


# TODO(yan): Proper SDK
# SEP-130
async def get_inventory_api(
    inventory_client: InventoryClient, user: CurrentUser
) -> AsyncGenerator[RemoteAPI]:
    """Construct a `RemoteAPI` instance for interacting with the Inventory API.

    :param inventory_client: The Inventory API client.
    :type inventory_client: RemoteAPI
    :param user: The current authenticated user, from which the access token is
        extracted.
    :type user: User
    :return: An instance of `RemoteAPI` configured for the Inventory service, including
        the endpoint, API key, and SSL settings.
    :rtype: RemoteAPI
    """
    with inventory_client.auth(user.access_token) as authenticated_api:
        yield authenticated_api


InventoryAPI = Annotated[RemoteAPI, Depends(get_inventory_api)]


async def get_tasks_client(request: Request) -> RemoteAPI:
    """Construct a `RemoteAPI` instance for interacting with the Tasks API.

    :param request: The HTTP request object.
    :type request: Request
    :return: An instance of `RemoteAPI` configured for the Tasks service, including
        the endpoint, API key, and SSL settings.
    :rtype: RemoteAPI
    """
    return getattr(
        request.app.state, "tasks_api", None
    ) or await settings.get_remote_api(
        endpoint=sep_settings.TASKS_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
        logger_name="tasks_api",
    )


TasksClient = Annotated[RemoteAPI, Depends(get_tasks_client)]


async def get_tasks_api(
    tasks_client: TasksClient, user: CurrentUser
) -> AsyncGenerator[RemoteAPI]:
    """Construct a `RemoteAPI` instance for interacting with the Tasks API.

    :param tasks_client: The Tasks API client.
    :type tasks_client: RemoteAPI
    :param user: The current authenticated user, from which the access token is
        extracted.
    :type user: User
    :return: An instance of `RemoteAPI` configured for the Tasks service, including
        the endpoint, API key, and SSL settings.
    :rtype: RemoteAPI
    """
    with tasks_client.auth(user.access_token) as authenticated_api:
        yield authenticated_api


TaskAPI = Annotated[RemoteAPI, Depends(get_tasks_api)]


async def get_pmm_api() -> PMMRemoteAPI | None:
    """Return a ``PMMRemoteAPI`` client, or ``None`` when PMM is not configured.

    Construct the SEP-wide PMM client from settings, sitting alongside the
    sibling Inventory / Tasks client deps so core SEP code never reaches into a
    plugin for it.

    :return: The PMM API client, or ``None`` if endpoint or API key is missing.
    :rtype: PMMRemoteAPI | None
    """
    if not settings.PMM.endpoint or not settings.PMM.api_key:
        return None
    return await settings.get_remote_api(
        PMMRemoteAPI,
        endpoint=settings.PMM.endpoint,
        api_key=settings.PMM.api_key,
        verify_ssl=settings.PMM.verify_ssl,
        ssl_cafile=settings.SSL_CAFILE,
    )


PMMAPIDep = Annotated[PMMRemoteAPI | None, Depends(get_pmm_api)]


async def require_pmm_api(pmm_api: PMMAPIDep) -> PMMRemoteAPI:
    """Return the PMM API client or raise if PMM is not configured.

    :param pmm_api: The PMM API client dependency, or ``None`` if PMM is not
        configured.
    :return: The PMM API client.
    :raises HTTPServiceUnavailableException: If PMM is not configured.
    """
    if pmm_api is None:
        raise HTTPServiceUnavailableException(detail="PMM is not configured")
    return pmm_api


RequiredPMMAPIDep = Annotated[PMMRemoteAPI, Depends(require_pmm_api)]


async def get_created_entity(
    inventory_api: InventoryAPI,
    entity_type: SyncInventoryEntityTypeEnum,
    entity_id: int,
    **filters: Any,
) -> CreatedEntity:
    """Retrieve a created entity instance based on the given entity type and ID.

    Fetches the entity data from the Inventory API and validates it into a
    `CreatedEntityBase` model. Additional filters might be passed for extra validation.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: InventoryAPI
    :param entity_type: The type of the entity to retrieve.
    :type entity_type: SyncInventoryEntityTypeEnum
    :param entity_id: The ID of the entity to retrieve.
    :type entity_id: int
    :param filters: Fields filters to check for the retrieved entity.
    :type filters: Any
    :return: The validated `CreatedEntity` instance.
    :rtype: CreatedEntity
    :raises ValueError: If one of the optional filters fail.
    """
    entity_path, entity_model = ENTITY_MAPPING[entity_type]
    entity_data = await inventory_api.get(f"{entity_path}/{entity_id}")
    entity = entity_model.model_validate(entity_data)
    for field, expected_value in filters.items():
        if (value := entity_data.get(field)) != expected_value:
            raise ValueError(
                f"{field} is not valid for {entity_type.name.lower()} {entity_id} ({value})"
            )
    return entity


async def get_created_node(inventory_api: InventoryAPI, node_id: int) -> CreatedNode:
    """Retrieve a CreatedNode instance based on the given node ID.

    Fetches the node data from the Inventory API and validates it into a `CreatedNode`
    model.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: InventoryAPI
    :param node_id: The ID of the node to retrieve.
    :type node_id: int
    :return: The validated `CreatedNode` instance.
    :rtype: CreatedNode
    """
    return await get_created_entity(
        inventory_api, SyncInventoryEntityTypeEnum.NODE, node_id
    )


CreatedNodeDep = Annotated[CreatedNode, Depends(get_created_node)]


async def get_created_service(
    inventory_api: InventoryAPI,
    service_id: int,
) -> CreatedService:
    """Retrieve a CreatedService instance based on the given service ID.

    Fetches the service data from the Inventory API and validates it into a
    `CreatedService` model.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: InventoryAPI
    :param service_id: The ID of the service to retrieve.
    :type service_id: int
    :return: The validated `CreatedService` instance.
    :rtype: CreatedService
    """
    return await get_created_entity(
        inventory_api, SyncInventoryEntityTypeEnum.SERVICE, service_id
    )


CreatedServiceDep = Annotated[CreatedService, Depends(get_created_service)]


async def get_created_schema(
    inventory_api: InventoryAPI,
    schema_id: int,
) -> CreatedSchema:
    """Retrieve a CreatedSchema instance based on the given schema ID.

    Fetches the schema data from the Inventory API and validates it into a
    `CreatedSchema` model.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: InventoryAPI
    :param schema_id: The ID of the schema to retrieve.
    :type schema_id: int
    :return: The validated `CreatedSchema` instance.
    :rtype: CreatedSchema
    """
    schema = await get_created_entity(
        inventory_api, SyncInventoryEntityTypeEnum.SCHEMA, schema_id
    )

    if schema.service and schema.service.node_id and not schema.service.node:
        node = await get_created_entity(
            inventory_api, SyncInventoryEntityTypeEnum.NODE, schema.service.node_id
        )
        schema.service.node = node
    return schema


CreatedSchemaDep = Annotated[CreatedSchema, Depends(get_created_schema)]


async def get_created_table(inventory_api: InventoryAPI, table_id: int) -> CreatedTable:
    """Retrieve a CreatedTable instance based on the given table ID.

    Fetches the table data from the Inventory API and validates it into a `CreatedTable`
    model.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: InventoryAPI
    :param table_id: The ID of the table to retrieve.
    :type table_id: int
    :return: The validated `CreatedTable` instance.
    :rtype: CreatedTable
    """
    return await get_created_entity(
        inventory_api, SyncInventoryEntityTypeEnum.TABLE, table_id
    )


CreatedTableDep = Annotated[CreatedTable, Depends(get_created_table)]


class ExecutorHostsContext:
    """Wrap executor hosts with inventory-based display name mapping.

    :param hosts: Raw executor hosts dictionary mapping nomad names to addresses.
    :type hosts: dict[str, str]
    :param display_names: Mapping from addresses to inventory node names.
    :type display_names: dict[str, str]
    """

    def __init__(self, hosts: dict[str, str], display_names: dict[str, str]) -> None:
        self._hosts = hosts
        self._display_names = display_names

    @property
    def hosts(self) -> dict[str, str]:
        """Return the raw hosts dictionary.

        :return: Dictionary mapping nomad names to addresses.
        :rtype: dict[str, str]
        """
        return self._hosts

    def display_name(self, nomad_name: str) -> str:
        """Return the inventory display name for a nomad host, with fallback.

        :param nomad_name: The nomad node name to look up.
        :type nomad_name: str
        :return: The inventory node name if found, otherwise the nomad name.
        :rtype: str
        """
        address = self._hosts.get(nomad_name)
        if address and address in self._display_names:
            return self._display_names[address]
        return nomad_name

    def as_template_list(self) -> list[dict[str, str]]:
        """Return a sorted list of value/label dicts for template rendering.

        :return: List of dicts with `value` and `label` keys, sorted by value.
        :rtype: list[dict[str, str]]
        """
        return sorted(
            ({"value": name, "label": self.display_name(name)} for name in self._hosts),
            key=lambda item: item["value"],
        )

    def as_form_hosts(self) -> frozenset[tuple[str, str]]:
        """Return a frozenset of (value, label) tuples for cached snippet forms.

        :return: Frozenset of tuples suitable for snippet form caching.
        :rtype: frozenset[tuple[str, str]]
        """
        return frozenset((name, self.display_name(name)) for name in self._hosts)

    def as_host_metrics(self) -> list[tuple[str, str]]:
        """Return a sorted list of (display_name, address) tuples for host metrics.

        :return: List of tuples with display name and address, sorted by display name.
        :rtype: list[tuple[str, str]]
        """
        return sorted(
            (self.display_name(name), address) for name, address in self._hosts.items()
        )

    def with_host(self, hostname: str) -> "ExecutorHostsContext":
        """Return a new context with the additional host included.

        :param hostname: The hostname to add to the context.
        :type hostname: str
        :return: A new context with the host added, or self if already present.
        :rtype: ExecutorHostsContext
        """
        if hostname in self._hosts:
            return self
        new_hosts = {**self._hosts, hostname: ""}
        return ExecutorHostsContext(hosts=new_hosts, display_names=self._display_names)


async def get_executor_hosts_context(
    executor_hosts: "ExecutorHosts",
    inventory_api: InventoryAPI,
) -> ExecutorHostsContext:
    """Build an enriched executor hosts context with inventory display names.

    :param executor_hosts: The raw executor hosts dictionary.
    :type executor_hosts: dict[str, str]
    :param inventory_api: The Inventory API client.
    :type inventory_api: RemoteAPI
    :return: An executor hosts context with display name mapping.
    :rtype: ExecutorHostsContext
    """
    try:
        nodes = await fetch_all_dict_items(
            lambda pagination: inventory_api.get(
                "/nodes/", params=pagination.model_dump()
            )
        )
        display_names = {node["address"]: node["name"] for node in nodes}
    except (HTTPException, TypeError, KeyError, OSError):
        logger.warning(
            "Failed to fetch inventory nodes for display names", exc_info=True
        )
        display_names = {}
    return ExecutorHostsContext(hosts=executor_hosts, display_names=display_names)


ExecutorHostsCtx = Annotated[ExecutorHostsContext, Depends(get_executor_hosts_context)]


async def get_executor_hosts(request: Request, tasks_api: TaskAPI) -> dict[str, str]:
    """Retrieve executor hosts from the Tasks API.

    :param request: The HTTP request object.
    :type request: Request
    :param tasks_api: The API client used to interact with the tasks service.
    :type tasks_api: TaskAPI
    :return: A dictionary of executor hosts.
    :rtype: dict[str, str]
    """
    try:
        return await tasks_api.get("/hosts/")
    except HTTPException as exc:
        messages.error(request, exc.detail)
    return {}


ExecutorHosts = Annotated[dict[str, str], Depends(get_executor_hosts)]


async def get_tasks_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    get_task_info_func: Callable[[dict[str, Any]], dict[str, Any]],
    executor_hosts_ctx: ExecutorHostsCtx,
    default_context: DefaultContext | None = None,
    owner: str | None = None,
    *,
    service_type: ServiceTypeEnum,
    alert_on_fail_default: bool = False,
) -> dict[str, Any]:
    """Assemble the template context for task-dependent plugins.

    This function retrieves inventory services (scoped by ``service_type``),
    tasks (filtered by ``owner``), and their histories from the Inventory and
    Tasks APIs. It organizes tasks based on their status and integrates them
    into the provided context.

    :param inventory_api: The API client used to interact with the inventory service.
    :param tasks_api: The API client used to interact with the tasks service.
    :param get_task_info_func: A callable that receives a task and returns
        the processed task information.
    :param executor_hosts_ctx: The enriched executor hosts context with display names.
    :param default_context: The base context dictionary to update. If None (default),
        initializes an empty dictionary.
    :param owner: The owner filter for retrieving tasks. Defaults to ``None``.
    :param service_type: The inventory service type whose services scope the
        ``/services/`` fetch.
    :param alert_on_fail_default: Default value for the alert on failure setting.
    :return: The assembled context dictionary containing tasks and services
        information, including ``connectivity_check_default`` sourced from
        ``sep_settings.CONNECTIVITY_CHECK_DEFAULT``.
    """
    services = await fetch_all_dict_items(
        lambda pagination: inventory_api.get(
            "/services/",
            params={"service_type": service_type, **pagination.model_dump()},
        )
    )

    tasks = []
    history_tasks = []
    scheduled_tasks = []
    running_tasks = []
    tasks_response = await tasks_api.get("/", params={"owner": owner})
    for task in tasks_response["items"]:
        task_info = {
            "name": task["name"],
            "id": task["id"],
            "created_by": task.get("created_by"),
            "last_updated_by": task.get("last_updated_by"),
        }
        task_info |= get_task_info_func(task)
        meta = task.get("data", {}).get("meta", {})
        if CONNECTIVITY_META_SERVICE_TYPE_KEY in meta:
            task_info[CONNECTIVITY_TARGET_KEY] = meta.get("target", "")
            task_info[CONNECTIVITY_META_SERVICE_TYPE_KEY] = meta[
                CONNECTIVITY_META_SERVICE_TYPE_KEY
            ]
        tasks.append(task_info)
        response = await tasks_api.get(f"/{task['name']}/history/")
        for hist in response["items"]:
            match TaskHistoryStatusEnum(hist["status"]):
                case TaskHistoryStatusEnum.PENDING:
                    scheduled_tasks.append(hist)
                case TaskHistoryStatusEnum.RUNNING:
                    running_tasks.append(hist)
                case _:
                    history_tasks.append(hist)
    annotate_tasks_with_connectivity(tasks)
    periodic_tasks = await tasks_api.get("/periodic/", params={"owner": owner})

    alert_on_fail_available = bool(alert_settings.PROVIDERS)
    context = default_context or {}
    context.update(
        {
            "executor_hosts": executor_hosts_ctx.as_template_list(),
            "services": services,
            "tasks": tasks,
            "pending_tasks": scheduled_tasks,
            "running_tasks": running_tasks,
            "history_tasks": history_tasks,
            "periodic_tasks": periodic_tasks,
            "chainable_tasks": tasks,
            "AVAILABLE_TIMEZONES": AVAILABLE_TIMEZONES,
            "alert_on_fail_default": alert_on_fail_available and alert_on_fail_default,
            "alert_on_fail_available": alert_on_fail_available,
            "connectivity_check_default": sep_settings.CONNECTIVITY_CHECK_DEFAULT,
        }
    )
    return context


async def get_chainable_tasks(
    tasks_api: RemoteAPI,
    owner: str,
    target: str,
    exclude_task_name: str,
) -> list[dict[str, Any]]:
    """Fetch tasks that can be chained after a given task.

    Return tasks matching the same owner and target, excluding the current task.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param owner: The task owner to filter by.
    :type owner: str
    :param target: The execution target to filter by.
    :type target: str
    :param exclude_task_name: The current task name to exclude from results.
    :type exclude_task_name: str
    :return: A list of chainable task dicts.
    :rtype: list[dict[str, Any]]
    """
    response = await tasks_api.get("/", params={"owner": owner, "target": target})
    return [t for t in response["items"] if t["name"] != exclude_task_name]


async def get_tasks_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    default_context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Homepage.

    Retrieve services and associated tasks, organizing them based on their
    execution status. Integrate this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param default_context: The default context to be updated with Alters-specific information.
    :type default_context: DefaultContext
    :param executor_hosts_ctx: The enriched executor hosts context with display names.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: An updated context dictionary containing tasks' data.
    :rtype: dict[str, Any]
    """
    response = await tasks_api.get(
        "/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    running_tasks = response["items"]
    response = await tasks_api.get(
        "/history/", params={"status": TaskHistoryStatusEnum.PENDING}
    )
    scheduled_tasks = response["items"]
    periodic_tasks = await tasks_api.get("/periodic/", params={"enabled": "True"})
    response = await tasks_api.get("/")
    task_owner_mapping = {task["name"]: task["owner"] for task in response["items"]}
    for periodic_task in periodic_tasks:
        task_name = periodic_task.get("task")
        periodic_task["owner"] = task_owner_mapping.get(task_name)
    inventories = await inventory_api.get("/summary/")
    # Derive from the already-filtered plugin list so a disabled Task Manager
    # does not leave the homepage rendering links into 503-returning routes.
    plugins = default_context.get("plugins", [])
    is_task_manager_enabled = any(
        p.name == "Task Manager" and p.sidebar for p in plugins
    )
    context = default_context
    context.update(
        {
            **inventories,
            "running_tasks": running_tasks,
            "pending_tasks": scheduled_tasks,
            "periodic_tasks": periodic_tasks,
            "executor_hosts": executor_hosts_ctx.as_host_metrics(),
            "is_task_manager_enabled": is_task_manager_enabled,
        },
    )
    return context


# TODO(yan): Put get_task in a proper TasksAPI SDK class
# SEP-130
async def get_task_by_name(
    tasks_api: TaskAPI, task_name: str, owner: str | None = None
) -> Task:
    """Fetch and validate a task by name.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the specified owner (if any). If the task does not exist or is
    not owned by the specified owner, it raises a 404 HTTP exception.

    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :param task_name: The name of the task to retrieve.
    :param owner: The owner filter for retrieving tasks. Defaults to ``None``, meaning
        no filter.
    :return: The retrieved task.
    :raises HTTPNotFoundException: If the task is not found or is not owned by the
        specified owner.
    """
    try:
        task = Task.model_validate(await tasks_api.get(f"/{task_name}"))
    except ValidationError:
        raise HTTPNotFoundException from None
    if owner is not None and owner != task.owner:
        raise HTTPNotFoundException
    return task


# TODO(yan): Put get_task_history in a proper TasksAPI SDK class
# SEP-130
async def get_task_history(
    tasks_api: TaskAPI, task_history_id: int, owner: str | None = None
) -> TaskHistoryResponse:
    """Fetch and validate a task history by ID.

    This function retrieves a task history by its ID from the Tasks API and optionally
    validates that it is owned by a specific owner. If the task history does not exist
    or the validation fails, it raises a 404 HTTP exception.

    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :param task_history_id: The ID of the task history to retrieve.
    :param owner: The owner filter for the task history's task. Defaults to ``None``,
        meaning no filter.
    :return: The retrieved task history.
    :raises HTTPNotFoundException: If the task history is not found or the validation
        fails.
    """
    try:
        task_history = TaskHistoryResponse.model_validate(
            await tasks_api.get(f"/history/{task_history_id}")
        )
    except ValidationError:
        logger.debug("ValidationError retrieving task history.", exc_info=True)
        raise HTTPNotFoundException from None
    logger.debug("TASK IS %s", task_history)
    if owner is not None and owner != task_history.task.owner:
        raise HTTPNotFoundException
    return task_history


async def check_for_conflicted_running_tasks(
    task_name: str, tasks_api: TaskAPI
) -> None:
    """Check for running or pending tasks with the same name.

    This function checks if there are any running or pending tasks with the same name
    as the provided `task_name`. If such tasks are found, it raises an
    HTTPConflictException.

    :param task_name: The name of the task to check for.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :raises HTTPConflictException: If there are running or pending tasks with the same
        name.
    """
    response = await tasks_api.get(
        f"/{task_name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    running_tasks = response["items"]
    response = await tasks_api.get(
        f"/{task_name}/history/", params={"status": TaskHistoryStatusEnum.PENDING}
    )
    pending_tasks = response["items"]
    if running_tasks or pending_tasks:
        raise HTTPConflictException("Task is already running or pending.")


HasNoConflictedRunningTasks = Depends(check_for_conflicted_running_tasks)


async def check_group_for_conflicted_running_tasks(
    task_names: Sequence[str], tasks_api: TaskAPI
) -> None:
    """Raise if any task in a group has a running or pending run.

    Backup and restore groups run on their derived/child legs, not on the parent
    config task, so gating an edit on the parent name alone lets an edit slip
    through mid-run. Check every group member.

    :param task_names: The parent and derived/child leg names to inspect.
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :raises HTTPConflictException: If any named task has a running or pending run.
    """
    for name in task_names:
        await check_for_conflicted_running_tasks(name, tasks_api)


def reject_if_protected(task: Task, *, action: str = "edit") -> Task:
    """Return the task unchanged or raise 409 when it is protected.

    Shared protected-task check for task-based plugins. Composable inline by
    dependencies that must run earlier gates (for example ``alters`` resolving a
    satellite path to its parent) before rejecting protected tasks.

    :param task: The resolved task to gate.
    :param action: The action verb for the 409 detail (``"edit"`` or ``"delete"``).
    :raises HTTPConflictException: If the task is marked as protected.
    :return: The unprotected task.
    """
    if task.protected:
        raise HTTPConflictException(f"Cannot {action} a protected task.")
    return task


def protected_task_guard(
    task_dep: Callable[..., Awaitable[Task]],
    *,
    action: str = "edit",
) -> Callable[..., Awaitable[Task]]:
    """Build a dependency that rejects protected tasks with HTTP 409.

    Parameterized on the plugin's task-fetch dependency and the action verb so a
    single helper serves every task plugin. Attach the returned callable to a
    derived PUT via ``update_guard`` or expose it as an ``Annotated`` type alias.

    :param task_dep: The plugin's task-fetch dependency used to resolve the task.
    :param action: The action verb for the 409 detail (``"edit"`` or ``"delete"``).
    :return: A FastAPI dependency that returns the task or raises 409.
    """

    async def _guard(task: Annotated[Task, Depends(task_dep)]) -> Task:
        return reject_if_protected(task, action=action)

    return _guard


def make_conflict_guard(
    task_dep: Callable[..., Awaitable[Task]],
) -> Callable[..., Awaitable[None]]:
    """Build a dependency that 409s when the resolved task has a running run.

    Parameterized on the plugin's task-fetch dependency so the conflict check
    resolves off the fetched ``task.name`` rather than a fixed ``task_name`` path
    parameter, keeping it decoupled from the route's detail path parameter. Shares
    the cached ``task_dep`` with the protected-task guard and the route handler, so
    the task is fetched once per request.

    :param task_dep: The plugin's task-fetch dependency used to resolve the task.
    :return: A FastAPI dependency that returns ``None`` or raises 409 when a
        running or pending run exists for the resolved task.
    """

    async def _guard(
        task: Annotated[Task, Depends(task_dep)],
        tasks_api: TaskAPI,
    ) -> None:
        await check_for_conflicted_running_tasks(task.name, tasks_api)

    return _guard
