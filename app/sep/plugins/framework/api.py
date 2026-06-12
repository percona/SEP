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

"""Define shared route helpers for schema-driven plugin routers.

The helpers in this module register a plugin's well-known routes with a
single call so plugins never re-implement the auth posture, response-model
wiring, or status-code conventions:

- :func:`schema_endpoint` and :func:`capabilities_endpoint` register the
  ``GET /schema`` and ``GET /capabilities`` discovery routes.
- :func:`derive_crud_routes` builds a plugin router carrying the schema
  route plus the standard list / detail / create (and optional update /
  delete) CRUD routes, composing the shared framework task helpers for the
  handler bodies.
"""

import functools
import inspect
import typing
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, cast, TypeVar

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.core.pagination import PaginatedResponse
from app.sep.deps import IsApiAuthenticated, TaskAPI
from app.sep.plugins.framework.responses import (
    build_task_list_responses,
    TaskResponseBuilder,
)
from app.sep.plugins.framework.schema import PluginSchema
from app.sep.plugins.framework.task_status import get_task_latest_status
from app.tasks.models import Task, TaskOwner, TaskWrite

__all__ = ["capabilities_endpoint", "derive_crud_routes", "schema_endpoint"]


CapabilitiesT = TypeVar("CapabilitiesT", bound=BaseModel)
ListDetailResponseT = TypeVar("ListDetailResponseT", bound=BaseModel)
CreateResponseT = TypeVar("CreateResponseT", bound=BaseModel)


def schema_endpoint(router: APIRouter, plugin_schema: PluginSchema) -> None:
    """Register a ``GET /schema`` route on ``router`` that returns ``plugin_schema``.

    Call this once from the module that owns the plugin's ``APIRouter``
    (typically under the shared ``plugins_router`` tree in
    ``app/sep/api/router.py``); the route then resolves at
    ``/api/plugins/{plugin}/schema`` once the plugin router is included with
    the matching prefix. The helper itself does not set a prefix.

    .. code-block:: python

        from fastapi import APIRouter

        from app.sep.plugins.framework.api import schema_endpoint
        from app.sep.plugins.checksums.schema import checksums_schema

        router = APIRouter()
        schema_endpoint(router, checksums_schema)

    The route pins ``response_model_by_alias=True`` so the
    ``field_type → "type"`` discriminator alias on each field serialises
    to the wire key the FE renderer expects (no top-level alias generator
    exists post-snake_case flip). ``response_model_exclude_none=True``
    keeps the payload free of the new conditional-rule primitive keys
    (``requires``, ``forbidden``, ``cardinality_rules``, ``fail_when``)
    for schemas that don't opt into them. ``IsApiAuthenticated`` is
    redeclared at the route level even though ``api_router`` applies the
    same dependency at router level; the duplicate declaration guarantees
    a JSON 401 even if a plugin mounts the router outside that tree, and
    FastAPI's dependency cache deduplicates it per request.

    :param router: The plugin's ``APIRouter``.
    :type router: APIRouter
    :param plugin_schema: The plugin's fully-validated schema instance.
    :type plugin_schema: PluginSchema
    :raises ValueError: If ``router`` already exposes a ``GET /schema`` route.
    """
    router_prefix = getattr(router, "prefix", "") or ""
    expected_path = f"{router_prefix}/schema"
    for existing in router.routes:
        existing_methods = set(getattr(existing, "methods", None) or ())
        if (
            getattr(existing, "path", None) == expected_path
            and "GET" in existing_methods
        ):
            raise ValueError(
                "schema_endpoint: router already has a GET /schema route; "
                "call this helper at most once per plugin router"
            )

    @router.get(
        "/schema",
        response_model_by_alias=True,
        response_model_exclude_none=True,
        dependencies=[IsApiAuthenticated],
    )
    async def get_schema() -> PluginSchema:
        """Return the plugin schema captured at registration time.

        :return: The plugin schema instance.
        :rtype: PluginSchema
        """
        return plugin_schema


def _resolve_response_model(
    provider: Callable[..., BaseModel],
    *,
    helper: str,
    param: str,
) -> type[BaseModel]:
    """Return the ``BaseModel`` subclass declared as ``provider``'s return type.

    Uses :func:`typing.get_type_hints` so deferred-evaluation annotations
    (``from __future__ import annotations``) resolve to the real class
    rather than a string. Falls back to the function's ``__annotations__``
    dict only when :func:`typing.get_type_hints` raises :class:`NameError`
    — i.e. a forward-ref that resolves against a module the caller hasn't
    imported. Other failures propagate unchanged.

    :param provider: A callable annotated with its return type. The
        callable may declare arbitrary parameters (typically resolved by
        FastAPI's dependency injection via ``Depends(...)``).
    :type provider: Callable[..., BaseModel]
    :param helper: The public helper name, used to frame error messages.
    :type helper: str
    :param param: The offending parameter name, used to frame error messages.
    :type param: str
    :return: The class declared as the provider's return annotation.
    :rtype: type[BaseModel]
    :raises TypeError: If the annotation is missing, isn't a class, or
        isn't a :class:`pydantic.BaseModel` subclass.
    """
    try:
        hints = typing.get_type_hints(provider)
    except NameError:
        # Forward-ref under ``from __future__ import annotations`` that resolves
        # against a module the caller hasn't imported — fall back to the raw
        # string annotation so the downstream isclass/issubclass check produces
        # the expected TypeError instead of leaking ``NameError`` here.
        hints = getattr(provider, "__annotations__", {})

    annotation = hints.get("return")
    if annotation is None:
        raise TypeError(
            f"{helper}: {param} must declare a return type annotation that is "
            f"a pydantic.BaseModel subclass (e.g. `def {param}() -> MyModel: ...`)"
        )
    if not inspect.isclass(annotation) or not issubclass(annotation, BaseModel):
        raise TypeError(
            f"{helper}: {param}'s return type annotation must be a "
            f"pydantic.BaseModel subclass; got {annotation!r}"
        )
    return annotation


def _reject_async_builders(**builders: Callable[..., BaseModel] | None) -> None:
    """Raise ``TypeError`` if any named builder is an ``async def`` callable.

    :func:`derive_crud_routes`'s handlers invoke the response builders
    synchronously, so an ``async def`` builder would yield an un-awaited
    coroutine that ``response_model`` serialisation cannot handle. Reject it at
    registration — mirroring :func:`capabilities_endpoint`'s sync-only guard —
    rather than letting it surface as an opaque failure on the first request.

    :param builders: Builder callables keyed by their parameter name; ``None``
        entries (an omitted optional builder) are skipped.
    :type builders: Callable[..., BaseModel] | None
    :raises TypeError: If any supplied builder is a coroutine function.
    """
    for label, builder in builders.items():
        if builder is not None and inspect.iscoroutinefunction(builder):
            raise TypeError(
                f"derive_crud_routes: {label} must be a sync callable; the "
                "derived handlers invoke it synchronously, so an async builder "
                "would yield an un-awaited coroutine that response_model "
                "serialisation cannot handle."
            )


def capabilities_endpoint(
    router: APIRouter,
    capabilities_provider: Callable[..., CapabilitiesT],
) -> None:
    """Register a ``GET /capabilities`` route returning ``capabilities_provider()``.

    Mirrors :func:`schema_endpoint` for the per-deployment runtime
    capability surface: same auth posture (``IsApiAuthenticated``
    redeclared at the route level), same duplicate-registration guard,
    same ``response_model_exclude_none=True`` posture. Inferring
    ``response_model`` from the provider's return annotation keeps the
    call site terse — plugins write a one-line registration adjacent to
    their ``schema_endpoint(...)`` call.

    .. code-block:: python

        from app.sep.plugins.framework.api import capabilities_endpoint
        from app.sep.plugins.snippets.models import SnippetsCapabilitiesResponse
        from app.sep.snippets.config import snippets_settings

        def _snippets_capabilities() -> SnippetsCapabilitiesResponse:
            return SnippetsCapabilitiesResponse(
                manual_sync_enabled=snippets_settings.ENABLE_MANUAL_SYNC,
            )

        capabilities_endpoint(router, capabilities_provider=_snippets_capabilities)

    Semantics:

    - The provider is invoked **per request**, never cached, so a
      deployment-config hot reload between two calls is reflected on the
      next response without a process restart.
    - ``IsApiAuthenticated`` only — there is no admin gate. Capability
      flags are public-to-authed-users by design; if a plugin needs to
      gate privileged flags, expose them on a separate route, not here.
    - The provider must be a function (or method) with a return-type
      annotation that resolves to a :class:`pydantic.BaseModel` subclass.
      Lambdas are rejected because their syntax provides no way to declare
      a return-type annotation.
    - The provider may declare arbitrary parameters; ``functools.wraps``
      preserves the signature so FastAPI inspects it and resolves any
      ``Depends(...)`` defaults per request (settings, session, current
      user, etc.). A zero-arg provider remains the most common shape
      (settings attribute read), but the helper does not enforce it.
    - The provider should be cheap. DB or network calls do not belong
      behind a synchronous provider; add an async-provider variant when
      a plugin needs that. ``async def`` providers are rejected at
      registration to keep the contract sync-only for now.
    - The new endpoint is intentionally separate from
      :class:`~app.sep.plugins.framework.schema.PluginSchema.capabilities`,
      which describes static UI feature flags (chaining, scheduling,
      alert_on_fail). The two surfaces are not unified: schema-side
      ``Capabilities`` is per-plugin compile-time posture, capability
      responses returned here are per-deployment runtime posture that
      may toggle without a redeploy.

    :param router: The plugin's ``APIRouter``.
    :type router: APIRouter
    :param capabilities_provider: A callable returning a
        :class:`pydantic.BaseModel` instance. The return-type annotation
        is used as the route's ``response_model``. The callable's
        parameters (if any) are passed through to FastAPI for dependency
        resolution.
    :type capabilities_provider: Callable[..., BaseModel]
    :raises TypeError: If ``capabilities_provider``'s return annotation
        is missing, is not a class, or is not a
        :class:`pydantic.BaseModel` subclass. Raised at registration
        time, not first request.
    :raises ValueError: If ``router`` already exposes a
        ``GET /capabilities`` route.
    """
    if inspect.iscoroutinefunction(capabilities_provider):
        raise TypeError(
            "capabilities_endpoint: capabilities_provider must be a sync "
            "callable; async providers are out of scope (see SEP-1133). "
            "Calling an async function from the sync handler would return a "
            "coroutine object that response_model serialisation cannot handle."
        )
    response_model = _resolve_response_model(
        capabilities_provider,
        helper="capabilities_endpoint",
        param="capabilities_provider",
    )

    router_prefix = getattr(router, "prefix", "") or ""
    expected_path = f"{router_prefix}/capabilities"
    for existing in router.routes:
        existing_methods = set(getattr(existing, "methods", None) or ())
        if (
            getattr(existing, "path", None) == expected_path
            and "GET" in existing_methods
        ):
            raise ValueError(
                "capabilities_endpoint: router already has a GET /capabilities "
                "route; call this helper at most once per plugin router"
            )

    @functools.wraps(capabilities_provider)
    def get_capabilities(*args: object, **kwargs: object) -> BaseModel:
        return capabilities_provider(*args, **kwargs)

    router.add_api_route(
        "/capabilities",
        get_capabilities,
        methods=["GET"],
        response_model=response_model,
        response_model_exclude_none=True,
        dependencies=[IsApiAuthenticated],
    )


def derive_crud_routes(
    plugin_schema: PluginSchema,
    *,
    task_owner: TaskOwner,
    get_task: Callable[..., Awaitable[Task]],
    response_builder: TaskResponseBuilder[ListDetailResponseT],
    create_payload: Callable[..., Awaitable[TaskWrite]],
    create_response_builder: TaskResponseBuilder[CreateResponseT] | None = None,
    detail_path_param: str = "task_name",
    pagination_dep: Any | None = None,
    update_handler: Callable[..., Awaitable[Any]] | None = None,
    delete_handler: Callable[..., Awaitable[Any]] | None = None,
) -> APIRouter:
    """Build a plugin router with the standard schema + CRUD routes.

    Register ``GET /schema`` plus standard task-plugin CRUD routes:
    owner-filtered list (``GET /``), detail (``GET /{detail_path_param}``),
    create (``POST /`` with ``201``), and optional update/delete overrides
    (``PUT`` / ``DELETE`` on ``/{detail_path_param}``; delete uses ``204``).
    All derived routes use ``IsApiAuthenticated`` and
    ``response_model_by_alias=True``.

    The derived detail route is greedy: ``GET /{detail_path_param}`` captures
    any single collection-root path segment. If a plugin also needs a static
    collection-root ``GET`` route (for example ``GET /capabilities``), prefer
    a hand-written router (or mount that static route under a sub-prefix)
    instead of this helper.

    .. code-block:: python

        from app.sep.plugins.framework.api import derive_crud_routes

        router = derive_crud_routes(
            archives_schema,
            task_owner=TaskOwner.ARCHIVER,
            get_task=get_archives_task,
            response_builder=build_archives_api_task_response,
            create_payload=build_archives_api_task_payload,
        )

    :param plugin_schema: The plugin's fully-validated schema instance.
    :type plugin_schema: PluginSchema
    :param task_owner: The task owner the list route filters by.
    :type task_owner: TaskOwner
    :param get_task: The raw ``make_task_dep(owner)`` callable resolving a task
        by name; its inner path parameter must equal ``detail_path_param``.
    :type get_task: Callable[..., Awaitable[Task]]
    :param response_builder: Builds the list/detail response model from a task
        and optional status; its return annotation supplies the response model.
    :type response_builder: TaskResponseBuilder[ListDetailResponseT]
    :param create_payload: The raw create-payload builder dependency (declares
        the request ``Body()`` model that drives the create ``422``).
    :type create_payload: Callable[..., Awaitable[TaskWrite]]
    :param create_response_builder: Builds the create response from a task;
        its return annotation supplies the create response model. Defaults to
        reusing ``response_builder`` (and its model).
    :type create_response_builder: TaskResponseBuilder[CreateResponseT] | None
    :param detail_path_param: The detail/update/delete path-parameter name;
        must equal ``get_task``'s inner path parameter (``make_task_dep`` uses
        ``task_name``).
    :type detail_path_param: str
    :param pagination_dep: A ``make_pagination_dep(...)`` result. When given,
        the list route takes that pagination dependency and returns a
        ``PaginatedResponse``; when ``None`` the list returns a plain list.
    :type pagination_dep: Any | None
    :param update_handler: A fully-formed update handler; when given, a
        ``PUT /{detail_path_param}`` route is registered using it. The helper
        applies only ``IsApiAuthenticated`` and ``response_model_by_alias`` — any
        additional route guard (e.g. ``HasNoConflictedRunningTasks``) must be
        declared as one of the handler's own signature dependencies (e.g.
        ``Annotated[None, Depends(HasNoConflictedRunningTasks)]``), since the
        handler is passed as a bare callable and carries no decorator-level
        dependencies into the helper.
    :type update_handler: Callable[..., Awaitable[Any]] | None
    :param delete_handler: A fully-formed delete handler; when given, a
        ``DELETE /{detail_path_param}`` route is registered using it, with
        ``status_code=204``. As with ``update_handler``, any extra route guard
        must be declared as one of the handler's own signature dependencies.
    :type delete_handler: Callable[..., Awaitable[Any]] | None
    :return: A plugin ``APIRouter`` carrying the schema + CRUD routes.
    :rtype: APIRouter
    :raises TypeError: If ``response_builder`` or ``create_response_builder``
        is an ``async def`` callable (the derived handlers invoke it
        synchronously), or does not declare a return-type annotation that is a
        :class:`pydantic.BaseModel` subclass.
    """
    _reject_async_builders(
        response_builder=response_builder,
        create_response_builder=create_response_builder,
    )

    list_detail_model = _resolve_response_model(
        response_builder, helper="derive_crud_routes", param="response_builder"
    )
    create_model = (
        _resolve_response_model(
            create_response_builder,
            helper="derive_crud_routes",
            param="create_response_builder",
        )
        if create_response_builder is not None
        else list_detail_model
    )

    router = APIRouter()
    schema_endpoint(router, plugin_schema)

    detail_path = f"/{{{detail_path_param}}}"

    if pagination_dep is None:

        async def _list(tasks_api: TaskAPI) -> list[BaseModel]:
            responses = await build_task_list_responses(
                tasks_api,
                owner=task_owner.value,
                response_builder=response_builder,
            )
            return cast(list[BaseModel], responses)

        router.add_api_route(
            "/",
            _list,
            methods=["GET"],
            response_model=list[list_detail_model],
            response_model_by_alias=True,
            dependencies=[IsApiAuthenticated],
        )
    else:

        async def _list_paginated(
            tasks_api: TaskAPI, pagination: pagination_dep
        ) -> PaginatedResponse:
            responses = await build_task_list_responses(
                tasks_api,
                owner=task_owner.value,
                response_builder=response_builder,
                pagination=pagination,
            )
            return cast(PaginatedResponse, responses)

        router.add_api_route(
            "/",
            _list_paginated,
            methods=["GET"],
            response_model=PaginatedResponse[list_detail_model],
            response_model_by_alias=True,
            dependencies=[IsApiAuthenticated],
        )

    async def _detail(
        tasks_api: TaskAPI, task: Annotated[Task, Depends(get_task)]
    ) -> BaseModel:
        task_status = await get_task_latest_status(tasks_api, task.name)
        return response_builder(task, status=task_status)

    router.add_api_route(
        detail_path,
        _detail,
        methods=["GET"],
        response_model=list_detail_model,
        response_model_by_alias=True,
        dependencies=[IsApiAuthenticated],
    )

    async def _create(
        tasks_api: TaskAPI,
        task_write: Annotated[TaskWrite, Depends(create_payload)],
    ) -> BaseModel:
        created = await tasks_api.post("/", json=task_write.model_dump())
        task = Task.model_validate(created)
        if create_response_builder is not None:
            return create_response_builder(task)
        return response_builder(task, status=None)

    router.add_api_route(
        "/",
        _create,
        methods=["POST"],
        status_code=status.HTTP_201_CREATED,
        response_model=create_model,
        response_model_by_alias=True,
        dependencies=[IsApiAuthenticated],
    )

    if update_handler is not None:
        router.add_api_route(
            detail_path,
            update_handler,
            methods=["PUT"],
            response_model_by_alias=True,
            dependencies=[IsApiAuthenticated],
        )

    if delete_handler is not None:
        router.add_api_route(
            detail_path,
            delete_handler,
            methods=["DELETE"],
            status_code=status.HTTP_204_NO_CONTENT,
            response_model_by_alias=True,
            dependencies=[IsApiAuthenticated],
        )

    return router
