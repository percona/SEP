"""Define SEP dependencies."""

import logging
from collections.abc import AsyncGenerator, Callable
from http.cookies import SimpleCookie
from typing import Annotated, Any

from fastapi import Depends, Request
from itsdangerous import BadSignature
from jwt import InvalidTokenError
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPTemporaryRedirectException
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.core.exceptions import HTTPNotFoundException
from app.core.fields import URL
from app.core.requests import RemoteAPI
from app.core.security import crypto_timestamp_serializer
from app.inventory.config import inventory_settings
from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
from app.sep.db import get_async_session_maker
from app.sep.inventory import (
    CreatedEntity,
    CreatedNode,
    CreatedSchema,
    CreatedService,
    CreatedTable,
    ENTITY_MAPPING,
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
    return request.url.replace(path="")


BaseURL = Annotated[URL, Depends(get_base_url)]


def get_oauth_redirect_exception(base_url: BaseURL) -> HTTPTemporaryRedirectException:
    """Return the HTTPTemporaryRedirectException for OAuth2 login.

    Create an HTTP redirect exception to handle OAuth2 redirection, clearing
    the old session cookie in the process.

    :param base_url: The base URL to be used for generating the OAuth redirect URL.
    :type base_url: Any
    :return: An exception that triggers a temporary redirect to the OAuth2 authorization
        URL.
    :rtype: HTTPTemporaryRedirectException
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


def get_access_token_from_cookie(  # nosec B107
    oauth_redirect_exception: OAuthRedirectException,
    request: Request,
) -> str:
    """Retrieve and verify the access token from a session cookie.

    Extracts the signed access token from the request cookies, verifies it, and
    returns the unsigned token. If verification fails, raises an OAuth redirect
        exception.

    :param oauth_redirect_exception: The exception to raise if the token is invalid or
        cannot be verified.
    :type oauth_redirect_exception: HTTPTemporaryRedirectException
    :param request: The HTTP request containing the session cookie.
    :type request: Request
    :return: The verified and unsigned access token.
    :rtype: str
    :raises HTTPTemporaryRedirectException: If the token is invalid or cannot be
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
        raise oauth_redirect_exception from None


AccessTokenCookie = Annotated[str, Depends(get_access_token_from_cookie)]


async def get_current_user(
    request: Request,
) -> User:
    """Return the authenticated user from a cookie token.

    :param request: The HTTP request object from which the base URL is derived.
    :type request: Request
    :return: The authenticated user.
    :rtype: User
    :raises HTTPTemporaryRedirectException: If the token is invalid or the user is
        inactive.
    """
    base_url = get_base_url(request)
    oauth_redirect_exception = get_oauth_redirect_exception(base_url)
    token = get_access_token_from_cookie(
        oauth_redirect_exception,
        request,
    )
    try:
        user = await User.from_jwt(token)
    except (BadSignature, InvalidTokenError, ValidationError) as exc:
        logger.debug("Failed to authenticate user: %s", exc, exc_info=True)
        raise oauth_redirect_exception from None
    if not user.is_active:
        logger.debug("User %s is not active", user.username)
        # TODO: Message on inactive  # noqa: TD002, TD003
        raise oauth_redirect_exception
    return user


IsAuthenticated = Depends(get_current_user)
CurrentUser = Annotated[User, IsAuthenticated]


def get_default_context(user: CurrentUser, base_uri: BaseURL) -> dict[str, Any]:
    """Return the default context for templates.

    :param user: The authenticated user.
    :type user: User
    :param base_uri: The base URI of the application.
    :type base_uri: Any
    :return: The default context.
    :rtype: dict[str, Any]
    """
    return {
        "user": user,
        "casdoor_url": settings.CASDOOR.get_frontend_url(base_uri),
        "base_uri": base_uri,
        "plugins": sep_settings.PLUGINS,
        "sync_refresh_time": sep_settings.SYNC_REFRESH_TIME,
    }


DefaultContext = Annotated[dict[str, Any], Depends(get_default_context)]


# TODO(yan): Proper SDK
# SEP-130
def get_inventory_api(user: CurrentUser) -> RemoteAPI:
    """Construct a `RemoteAPI` instance for interacting with the Inventory API.

    :param user: The current authenticated user, from which the access token is
        extracted.
    :type user: User
    :return: An instance of `RemoteAPI` configured for the Inventory service, including
        the endpoint, API key, and SSL settings.
    :rtype: RemoteAPI
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

    :param user: The current authenticated user, from which the access token is
        extracted.
    :type user: User
    :return: An instance of `RemoteAPI` configured for the Tasks service, including
        the endpoint, API key, and SSL settings.
    :rtype: RemoteAPI
    """
    return RemoteAPI(
        endpoint=sep_settings.TASKS_ENDPOINT,
        api_key=user.access_token,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
    )


TaskAPI = Annotated[RemoteAPI, Depends(get_tasks_api)]


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an asynchronous database session for FastAPI routes.

    This function provides a dependency for FastAPI routes that yields an `AsyncSession`
    for interacting with the database. The session is properly closed after use.

    :yield: An asynchronous session for database operations.
    :rtype: AsyncSession
    """
    async_session_maker = get_async_session_maker()
    async with async_session_maker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


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
    return await get_created_entity(
        inventory_api, SyncInventoryEntityTypeEnum.SCHEMA, schema_id
    )


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


async def get_tasks_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    get_task_info_func: Callable[[dict[str, Any]], dict[str, Any]],
    default_context: DefaultContext | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Assemble the template context for task-dependent plugins.

    This function retrieves MySQL services, tasks, and their histories from the
    Inventory and Tasks APIs. It organizes tasks based on their status and integrates
    them into the provided context.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: RemoteAPI
    :param tasks_api: The API client used to interact with the tasks service.
    :type tasks_api: RemoteAPI
    :param get_task_info_func: A callable that receives a task and returns
        the processed task information.
    :type get_task_info_func: Callable[[dict[str, Any]], dict[str, Any]]
    :param default_context: The base context dictionary to update. If None (default),
        initializes an empty dictionary.
    :type default_context: dict[str, Any] | None
    :param owner: The owner filter for retrieving tasks. Defaults to `None`.
    :type owner: str | None
    :return: The assembled context dictionary containing tasks and services information.
    :rtype: dict[str, Any]
    """
    mysql_services = await inventory_api.get(
        "/services/", params={"service_type": ServiceTypeEnum.MYSQL}
    )
    for service in mysql_services:
        service["schemas"] = await inventory_api.get(
            f"/services/{service['id']}/schemas/",
        )
    tasks = []
    history_tasks = []
    scheduled_tasks = []
    running_tasks = []
    for task in await tasks_api.get("/", params={"owner": owner}):
        task_info = {
            "name": task["name"],
            "id": task["id"],
        }
        task_info |= get_task_info_func(task)
        tasks.append(task_info)
        history = await tasks_api.get(f"/{task['name']}/history/")
        for hist in history:
            match TaskHistoryStatusEnum(hist["status"]):
                case TaskHistoryStatusEnum.SUCCESS | TaskHistoryStatusEnum.FAILED:
                    history_tasks.append(hist)
                case TaskHistoryStatusEnum.PENDING:
                    scheduled_tasks.append(hist)
                case TaskHistoryStatusEnum.RUNNING:
                    running_tasks.append(hist)
    executor_hosts = await tasks_api.get("/hosts/")
    context = default_context or {}
    context.update(
        {
            "executor_hosts": list(executor_hosts.values()),
            "mysql_services": mysql_services,
            "tasks": tasks,
            "pending_tasks": scheduled_tasks,
            "running_tasks": running_tasks,
            "history_tasks": history_tasks,
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
    :type tasks_api: TaskAPI
    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param owner: The owner filter for retrieving tasks. Defaults to `None`, meaning
        no filter.
    :type owner: str | None
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or is not owned by the
        specified owner.
    """
    try:
        task = Task.model_validate(await tasks_api.get(f"/{task_name}"))
    except ValidationError:
        raise HTTPNotFoundException from None
    if owner is not None and Task.validate_owner(owner) != task.owner:
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
    :type tasks_api: TaskAPI
    :param task_history_id: The ID of the task history to retrieve.
    :type task_history_id: str
    :param owner: The owner filter for the task history's task. Defaults to `None`,
        meaning no filter.
    :type owner: str | None
    :return: The retrieved task history.
    :rtype: TaskHistoryResponse
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
    if owner is not None and Task.validate_owner(owner) != task_history.task.owner:
        raise HTTPNotFoundException
    return task_history


# TODO(yan): Put stream_task_history_logs in a proper TasksAPI SDK class
# SEP-130
async def task_history_logs_event_stream(
    tasks_api: TaskAPI, task_history_id: int
) -> AsyncGenerator[str, None]:
    """Stream logs from a task history as server-sent events.

    Streams log lines for a given task history ID from the Tasks API and yields them
    formatted as server-sent events.

    :param tasks_api: The TaskAPI client for interacting with the Tasks service.
    :type tasks_api: RemoteAPI
    :param task_history_id: The ID of the task history whose logs to stream.
    :type task_history_id: int
    :yield: Log entries formatted as server-sent events.
    :rtype: str
    """
    async for line in tasks_api.stream(f"/history/{task_history_id}/logs/"):
        log_entry = line.decode("utf-8")
        yield f"data: {log_entry}\n\n"
