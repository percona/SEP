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

import logging
from collections.abc import AsyncGenerator, Callable
from typing import Annotated, Any
from zoneinfo import available_timezones

from fastapi import Depends, HTTPException, Request, status
from fastapi_csrf_protect import CsrfProtect
from itsdangerous import BadSignature
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.alerts.config import alert_settings
from app.core.auth.exceptions import HTTPForbiddenException
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.core.exceptions import (
    HTTPConflictException,
    HTTPNotFoundException,
    HTTPRedirectException,
)
from app.core.requests import RemoteAPI
from app.core.security import crypto_timestamp_serializer
from app.core.utils.fields import URL
from app.inventory.config import inventory_settings
from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
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
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.config import tasks_settings
from app.tasks.models import (
    Task,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
    TaskOwner,
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


async def get_current_user(
    request: Request,
) -> User:
    """Return the authenticated user from a cookie token.

    :param request: The HTTP request object from which the base URL is derived.
    :type request: Request
    :return: The authenticated user.
    :rtype: User
    :raises LoginRedirectException: If the token is invalid or the user is
        inactive.
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
    return user


IsAuthenticated = Depends(get_current_user)
CurrentUser = Annotated[User, IsAuthenticated]


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

CsrfProtectDep = Annotated[CsrfProtect, Depends()]


async def validate_csrf(
    request: Request,
    csrf_protect: CsrfProtectDep,
) -> None:
    """Validate the CSRF token from the request.

    :param request: The HTTP request object.
    :type request: Request
    :param csrf_protect: The CSRF protection mechanism dependency.
    :type csrf_protect: CsrfProtect
    """
    time_limit = int(sep_settings.SESSION.MAX_AGE.total_seconds())
    await csrf_protect.validate_csrf(request, time_limit=time_limit)


IsCsrfValidated = Depends(validate_csrf)


async def get_username_mapping() -> dict[str, str]:
    """Create a mapping from user ID to username using Casdoor.

    This function fetches all users from Casdoor and creates a mapping from
    user ID to username. Caching should be implemented in the Casdoor SDK
    to avoid repeated API calls.

    :return: A dictionary mapping user IDs to usernames.
    :rtype: dict[str, str]
    """
    try:
        users = await settings.CASDOOR.get_users()
        return {str(user["id"]): user["name"] for user in users}
    except (ValueError, KeyError, HTTPException):
        logger.exception("Failed to get username mapping from Casdoor")
        return {}


async def get_default_context(
    request: Request,
    user: CurrentUser,
    base_uri: BaseURL,
) -> dict[str, Any]:
    """Return the default context for templates.

    :param request: The HTTP request object.
    :type request: Request
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
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "pmm_url": sep_settings.PMM.frontend,
        "footer_text": sep_settings.FOOTER_TEXT,
        "user_id_to_username": await get_username_mapping(),
    }


DefaultContext = Annotated[dict[str, Any], Depends(get_default_context)]


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
        nodes = await inventory_api.get("/nodes/")
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
    owner: TaskOwner | None = None,
    *,
    alert_on_fail_default: bool = False,
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
    :param executor_hosts_ctx: The enriched executor hosts context with display names.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :param default_context: The base context dictionary to update. If None (default),
        initializes an empty dictionary.
    :type default_context: dict[str, Any] | None
    :param owner: The owner filter for retrieving tasks. Defaults to `None`.
    :type owner: TaskOwner | None
    :param alert_on_fail_default: Default value for the alert on failure setting.
    :type alert_on_fail_default: bool
    :return: The assembled context dictionary containing tasks and services information.
    :rtype: dict[str, Any]
    """
    service_type = (
        ServiceTypeEnum.MONGODB
        if owner in {TaskOwner.BACKUP_MONGO, TaskOwner.RESTORE_MONGO}
        else ServiceTypeEnum.POSTGRESQL
        if owner in {TaskOwner.BACKUP_PG}
        else ServiceTypeEnum.MYSQL
    )
    services = await inventory_api.get(
        "/services/", params={"service_type": service_type}
    )

    for service in services:
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
            "created_by": task.get("created_by"),
            "last_updated_by": task.get("last_updated_by"),
        }
        task_info |= get_task_info_func(task)
        tasks.append(task_info)
        history = await tasks_api.get(f"/{task['name']}/history/")
        for hist in history:
            match TaskHistoryStatusEnum(hist["status"]):
                case TaskHistoryStatusEnum.PENDING:
                    scheduled_tasks.append(hist)
                case TaskHistoryStatusEnum.RUNNING:
                    running_tasks.append(hist)
                case _:
                    history_tasks.append(hist)
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
            "AVAILABLE_TIMEZONES": list(available_timezones()),
            "alert_on_fail_default": alert_on_fail_available and alert_on_fail_default,
            "alert_on_fail_available": alert_on_fail_available,
        }
    )
    return context


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
    running_tasks = await tasks_api.get(
        "/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    scheduled_tasks = await tasks_api.get(
        "/history/", params={"status": TaskHistoryStatusEnum.PENDING}
    )
    periodic_tasks = await tasks_api.get("/periodic/", params={"enabled": "True"})
    tasks = await tasks_api.get("/")
    task_owner_mapping = {task["name"]: task["owner"] for task in tasks}
    for periodic_task in periodic_tasks:
        task_name = periodic_task.get("task")
        periodic_task["owner"] = task_owner_mapping.get(task_name)
    inventories = await inventory_api.get("/summary/")
    plugins = sep_settings.PLUGINS
    is_task_manager_enabled = any(
        p.name == "Task Manager" and p.sidebar for p in plugins
    )
    context = default_context or {}
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
    tasks_api: TaskAPI, task_name: str, owner: TaskOwner | None = None
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
    :type owner: TaskOwner | None
    :return: The retrieved task.
    :rtype: Task
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
    tasks_api: TaskAPI, task_history_id: int, owner: TaskOwner | None = None
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
    :type owner: TaskOwner | None
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
    running_tasks = await tasks_api.get(
        f"/{task_name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    pending_tasks = await tasks_api.get(
        f"/{task_name}/history/", params={"status": TaskHistoryStatusEnum.PENDING}
    )
    if running_tasks or pending_tasks:
        raise HTTPConflictException("Task is already running or pending.")


HasNoConflictedRunningTasks = Depends(check_for_conflicted_running_tasks)
