"""Define SEP dependencies."""

import logging
from typing import Annotated
from typing import Any

from fastapi import Cookie
from fastapi import Depends
from fastapi import Form
from fastapi import Request
from jwt import InvalidTokenError
from pydantic import ValidationError

from app.core.auth.exceptions import HTTPTemporaryRedirectException
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.core.fields import URL
from app.core.requests import RemoteAPI
from app.inventory.config import inventory_settings
from app.sep.config import sep_settings
from app.tasks.config import tasks_settings
from app.tasks.models import GeneratedTask

logger = logging.getLogger(__name__)
User = get_user_model()


def get_base_url(request: Request) -> URL:
    return request.url.replace(path="")


BaseURL = Annotated[URL, Depends(get_base_url)]


def get_oauth_redirect_exception(base_url: BaseURL) -> HTTPTemporaryRedirectException:
    logger.error("BASE_URL: %s", base_url)
    return HTTPTemporaryRedirectException(sep_settings.OAUTH.get_auth_url(base_url))


OAuthRedirectException = Annotated[
    HTTPTemporaryRedirectException,
    Depends(get_oauth_redirect_exception),
]


async def get_current_user(
    oauth_redirect_exception: OAuthRedirectException,
    token: Annotated[str, Cookie(alias=sep_settings.OAUTH.COOKIE_NAME)] = "",
) -> User:
    """Return the authenticated user from a cookie token.

    Parameters
    ----------
    token: str
        The cookie token to authenticate the user.

    Returns
    -------
    User
        The authenticated user.

    Raises
    ------
    HTTPUnauthorizedException
        If the token is invalid and authentication fails.
    InactiveUserException
        If authentication succeeds but the user is not active.

    """
    try:
        user = await User.from_jwt(token)
    except (InvalidTokenError, ValidationError):
        logger.exception("Failed to authenticate user")
        raise oauth_redirect_exception from None
    if not user.is_active:
        logger.error("User %s is not active", user.username)
        # TODO: Message on inactive
        raise oauth_redirect_exception
    return user


IsAuthenticatedCookie = Depends(get_current_user)
CurrentUser = Annotated[User, IsAuthenticatedCookie]


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
    return RemoteAPI(
        endpoint=sep_settings.INVENTORY_ENDPOINT,
        api_key=user.access_token,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
    )


InventoryAPI = Annotated[RemoteAPI, Depends(get_inventory_api)]


async def get_tasks_api(user: CurrentUser) -> RemoteAPI:
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
    """Create a payload for the backend

    :param config:
    :return:
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
