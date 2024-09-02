"""Define SEP dependencies."""

import logging
from typing import Annotated
from typing import Any

from fastapi import Cookie
from fastapi import Depends
from fastapi import Form
from jwt import InvalidTokenError
from pydantic import ValidationError

from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.core.requests import RemoteAPI
from app.sep.config import sep_settings
from app.sep.exceptions import OAuthRedirectException
from app.tasks.models import GeneratedTask

logger = logging.getLogger(__name__)
User = get_user_model()


async def get_current_user(
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
        raise OAuthRedirectException from None
    if not user.is_active:
        logger.error("User %s is not active", user.username)
        # TODO: Message on inactive
        raise OAuthRedirectException
    return user


IsAuthenticatedCookie = Depends(get_current_user)
CurrentUser = Annotated[User, IsAuthenticatedCookie]


def get_default_context(user: CurrentUser) -> dict[str, Any]:
    """Return the default context for templates.

    Parameters
    ----------
    user: CurrentUser
        The authenticated user.

    Returns
    -------
    dict[str, Any]
        The default context.

    """
    return {
        "user": user,
        "casdoor_url": settings.CASDOOR.ENDPOINT,
        "base_uri": settings.BASE_URI,
    }


DefaultContext = Annotated[dict[str, Any], Depends(get_default_context)]


# TODO: Proper SDK
def get_inventory_api(user: CurrentUser) -> RemoteAPI:
    return RemoteAPI(
        endpoint=sep_settings.INVENTORY_ENDPOINT,
        api_key=user.access_token,
    )


InventoryAPI = Annotated[RemoteAPI, Depends(get_inventory_api)]


async def get_tasks_api(user: CurrentUser) -> RemoteAPI:
    return RemoteAPI(endpoint=sep_settings.TASKS_ENDPOINT, api_key=user.access_token)


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
