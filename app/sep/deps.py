"""Define SEP dependencies."""

import logging
from http.cookies import SimpleCookie
from typing import Annotated
from typing import Any

from fastapi import Depends
from fastapi import Form
from fastapi import Request
from itsdangerous import BadSignature
from jwt import InvalidTokenError
from pydantic import ValidationError

from app.core.auth.exceptions import HTTPTemporaryRedirectException
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.core.fields import URL
from app.core.requests import RemoteAPI
from app.core.security import crypto_timestamp_serializer
from app.inventory.config import inventory_settings
from app.sep.config import sep_settings
from app.tasks.config import tasks_settings
from app.tasks.models import GeneratedTask

logger = logging.getLogger(__name__)
User = get_user_model()


def get_base_url(request: Request) -> URL:
    """Extract the base URL from an incoming request by removing the path.

    Parameters
    ----------
    request : Request
        The HTTP request object from which the base URL is derived.

    Returns
    -------
    URL
        The base URL with the path removed.

    """
    return request.url.replace(path="")


BaseURL = Annotated[URL, Depends(get_base_url)]


def get_oauth_redirect_exception(base_url: BaseURL) -> HTTPTemporaryRedirectException:
    """Return the HTTPTemporaryRedirectException for OAuth2 login

    Create an HTTP redirect exception to handle OAuth2 redirection, clearing
    the old session cookie in the process.

    Parameters
    ----------
    base_url : BaseURL
        The base URL to be used for generating the OAuth redirect URL.

    Returns
    -------
    HTTPTemporaryRedirectException
        An exception that triggers a temporary redirect to the OAuth2 authorization URL.

    """
    exc = HTTPTemporaryRedirectException(sep_settings.OAUTH.get_auth_url(base_url))
    cookie = SimpleCookie()
    cookie[sep_settings.SESSION.COOKIE_NAME] = ""
    cookie[sep_settings.SESSION.COOKIE_NAME]["httponly"] = True
    cookie[sep_settings.SESSION.COOKIE_NAME]["secure"] = sep_settings.SESSION.SECURE
    cookie[sep_settings.SESSION.COOKIE_NAME]["samesite"] = sep_settings.SESSION.SAMESITE
    exc.headers["set-cookie"] = cookie.output(header="").strip()
    return exc


OAuthRedirectException = Annotated[
    HTTPTemporaryRedirectException,
    Depends(get_oauth_redirect_exception),
]


def get_access_token_from_cookie(
    oauth_redirect_exception: OAuthRedirectException,
    signed_access_token: str = "",
) -> str:
    """Return the unsigned token from the signed cookie.

    Retrieve and verify the access token from a session cookie. If the token
    is invalid or expired, trigger an OAuth redirect exception.

    Parameters
    ----------
    oauth_redirect_exception : OAuthRedirectException
        The exception to raise if the token is invalid or cannot be verified.
    signed_access_token : str, optional
        The signed access token stored in the session cookie.
        Defaults to an empty string.

    Returns
    -------
    str
        The verified and unsigned access token.

    Raises
    ------
    HTTPTemporaryRedirectException
        If the token is invalid or cannot be verified due to a `BadSignature`.

    Notes
    -----
    - The access token is verified using `crypto_timestamp_serializer` with
      a maximum age set by the session's expiration time.

    """
    try:
        return crypto_timestamp_serializer.loads(
            signed_access_token,
            max_age=sep_settings.SESSION.MAX_AGE.total_seconds(),
        )
    except BadSignature:
        logger.debug("Failed to unsign token", exc_info=True)
        raise oauth_redirect_exception


AccessTokenCookie = Annotated[str, Depends(get_access_token_from_cookie)]


async def get_current_user(
    request: Request,
) -> User:
    """Return the authenticated user from a cookie token.

    Parameters
    ----------
    request : Request
        The HTTP request object from which the base URL is derived.

    Returns
    -------
    User
        The authenticated user.

    Raises
    ------
    HTTPTemporaryRedirectException
        If the token is invalid or the user is inactive.

    """
    base_url = get_base_url(request)
    oauth_redirect_exception = get_oauth_redirect_exception(base_url)
    token = get_access_token_from_cookie(
        oauth_redirect_exception,
        request.cookies.get(sep_settings.SESSION.COOKIE_NAME, ""),
    )
    try:
        user = await User.from_jwt(token)
    except (BadSignature, InvalidTokenError, ValidationError) as exc:
        logger.debug("Failed to authenticate user: %s", exc, exc_info=True)
        raise oauth_redirect_exception from None
    if not user.is_active:
        logger.debug("User %s is not active", user.username)
        # TODO: Message on inactive
        raise oauth_redirect_exception
    return user


IsAuthenticated = Depends(get_current_user)
CurrentUser = Annotated[User, IsAuthenticated]


def get_default_context(user: CurrentUser, base_uri: BaseURL) -> dict[str, Any]:
    """Return the default context for templates.

    Parameters
    ----------
    user: CurrentUser
        The authenticated user.
    base_uri: BaseURI
        The base URI of the application.

    Returns
    -------
    dict[str, Any]
        The default context.

    """
    return {
        "user": user,
        "casdoor_url": settings.CASDOOR.get_frontend_url(base_uri),
        "base_uri": base_uri,
        "plugins": sep_settings.PLUGINS,
    }


DefaultContext = Annotated[dict[str, Any], Depends(get_default_context)]


# TODO: Proper SDK
def get_inventory_api(user: CurrentUser) -> RemoteAPI:
    """Construct a `RemoteAPI` instance for interacting with the Inventory API.

    Parameters
    ----------
    user : CurrentUser
        The current authenticated user, from which the access token is extracted.

    Returns
    -------
    RemoteAPI
        An instance of `RemoteAPI` configured for the Inventory service, including
        the endpoint, API key, and SSL settings.

    """
    return RemoteAPI(
        endpoint=sep_settings.INVENTORY_ENDPOINT,
        api_key=user.access_token,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
    )


InventoryAPI = Annotated[RemoteAPI, Depends(get_inventory_api)]


def get_tasks_api(user: CurrentUser) -> RemoteAPI:
    """Construct a `RemoteAPI` instance for interacting with the Tasks API.

    Parameters
    ----------
    user : CurrentUser
        The current authenticated user, from which the access token is extracted.

    Returns
    -------
    RemoteAPI
        An instance of `RemoteAPI` configured for the Tasks service, including
        the endpoint, API key, and SSL settings.

    """
    return RemoteAPI(
        endpoint=sep_settings.TASKS_ENDPOINT,
        api_key=user.access_token,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
    )


TaskAPI = Annotated[RemoteAPI, Depends(get_tasks_api)]


async def build_alters_task_payload(
    task_name: Annotated[str, Form()],
    hostname: Annotated[str, Form()],
    connect_to: Annotated[str, Form()],
    schema_name: Annotated[str, Form()],
    table_name: Annotated[str, Form()],
    recursion_method: Annotated[str, Form()],
    alter: Annotated[str, Form()],
    dsn_table: Annotated[str, Form()] = "",
) -> GeneratedTask:
    """Build the alter task payload from form.

    Build the payload for an Alters task to be executed, including the
    necessary command arguments for performing schema changes.

    Parameters
    ----------
    task_name : str
        The name of the task to be created.
    hostname : str
        The target hostname for the task execution.
    connect_to : str
        The connection type, which could be a hostname or `localhost`.
    schema_name : str
        The database schema name on which the task will operate.
    table_name : str
        The table name within the schema to be altered.
    recursion_method : str
        The method for handling recursion.
    alter : str
        The specific alter command to be executed.
    dsn_table : str, optional
        The DSN table for recursion method when using `dsn`.
        Defaults to an empty string.

    Returns
    -------
    GeneratedTask
        A fully constructed `GeneratedTask` object containing all the necessary commands
        and parameters for the Alters task execution.

    """
    if connect_to == "localhost":
        dsn = f"D={schema_name},t={table_name}"
    else:
        dsn = f"h={connect_to},D={schema_name},t={table_name}"
    if sep_settings.ALTERS_DB_USERNAME:
        dsn += f",u={sep_settings.ALTERS_DB_USERNAME}"
    if sep_settings.ALTERS_DB_PASSWORD:
        dsn += f",p={sep_settings.ALTERS_DB_PASSWORD}"
        # TODO: mask/hash password on view

    if recursion_method == "dsn":
        recursion_method = f"dsn={dsn_table}"
    else:
        recursion_method = recursion_method

    return GeneratedTask(
        app="alters",
        commands=[
            {
                "args": [
                    f"--alter={alter}",
                    dsn,
                    f"--recursion-method={recursion_method}",
                    "--execute",
                ],
                "command": "pt-online-schema-change",
                "meta": {"schema_name": schema_name, "table_name": table_name},
            },
        ],
        name=task_name,
        target=hostname,
    )


AltersGeneratedTask = Annotated[GeneratedTask, Depends(build_alters_task_payload)]
