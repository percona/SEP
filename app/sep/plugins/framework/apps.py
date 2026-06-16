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

"""Define ``TaskExecutionApp`` as the declarative spine of the plugin framework.

A ``TaskExecutionApp`` composes route-derivation helpers
(:func:`~app.sep.plugins.framework.api.derive_crud_routes`,
:func:`~app.sep.plugins.framework.api.derive_execute_route`,
:func:`~app.sep.plugins.framework.api.capabilities_endpoint`) and the model-first
form DSL into a complete derived ``APIRouter`` from a single declarative object,
so a task app no longer hand-wires those helpers per plugin. The derived router
is computed once at construction into ``api_router`` so the existing
:class:`~app.sep.plugins.framework.registry.AppRegistry` mounts it through the
same ``api_router`` seam with no registry change.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends, Form
from pydantic import BaseModel, model_validator, PrivateAttr, SkipValidation

from app.core.pagination import PaginationDependency
from app.sep.deps import InventoryAPI
from app.sep.plugins.framework.api import (
    capabilities_endpoint,
    derive_crud_routes,
    derive_execute_route,
)
from app.sep.plugins.framework.base import BaseApp
from app.sep.plugins.framework.deps import make_task_dep
from app.sep.plugins.framework.form_dsl import (
    AppFormModel,
    derive_plugin_schema,
    FormLayout,
)
from app.sep.plugins.framework.payload import (
    assemble_envelope,
    EnvelopeSpec,
    resolve_refs,
    ResolvedEntities,
)
from app.sep.plugins.framework.responses import (
    build_default_task_response,
    TaskResponseBuilder,
)
from app.sep.plugins.framework.schema import (
    Capabilities,
    ChainedPredecessor,
    DerivedTask,
    DetailView,
    ListView,
    PluginSchema,
)
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskOwner, TaskWrite

__all__ = ["AppCapabilities", "Cascade", "TaskExecutionApp", "Views"]

TaskSpecBuilder = Callable[[AppFormModel, ResolvedEntities], EnvelopeSpec]


class AppCapabilities(BaseModel):
    """Toggle which verbs a ``TaskExecutionApp`` derives.

    Distinct from the schema-side
    :class:`~app.sep.plugins.framework.schema.Capabilities` (UI feature flags
    serialised inside ``GET /schema``): this model gates *route derivation* only
    and is never serialised, so it cannot change the ``GET /schema`` wire format.

    :param create: Whether to derive the ``POST /`` create route. Defaults to
        ``True``.
    :param execute: Whether to derive the ``POST /{task_name}/execute`` route.
        Defaults to ``True``.
    :param update: Whether to derive a ``PUT /{task_name}`` route (requires an
        ``update_handler``). Defaults to ``False``.
    :param delete: Whether to derive a ``DELETE /{task_name}`` route (requires a
        ``delete_handler``). Defaults to ``False``.
    """

    create: bool = True
    execute: bool = True
    update: bool = False
    delete: bool = False


@dataclass(frozen=True, slots=True)
class Views:
    """Carry the presentation inputs that are not derivable from the create model.

    :param layout: The create form's section layout; required when the app
        derives its schema from a ``create_model``. Defaults to ``None``.
    :param list_view: The list-view configuration. Defaults to ``None``.
    :param detail_view: The task detail-page layout. Defaults to ``None``.
    :param capabilities: The schema-side UI feature flags (chaining, scheduling,
        …) passed through to the derived schema. Defaults to ``None``.
    """

    layout: FormLayout | None = None
    list_view: ListView | None = None
    detail_view: DetailView | None = None
    capabilities: Capabilities | None = None


@dataclass(frozen=True, slots=True)
class Cascade:
    """Carry the derived-task and predecessor specs fed into the derived schema.

    :param derived: Specs for sibling tasks derived from the parent on cascade.
        Defaults to an empty tuple.
    :param predecessors: Specs for tasks that must run before the parent.
        Defaults to an empty tuple.
    """

    derived: tuple[DerivedTask, ...] = ()
    predecessors: tuple[ChainedPredecessor, ...] = ()


class TaskExecutionApp(BaseApp):
    """Compose the Layer 1 helpers into a derived task-app router from one object.

    The router is built once in a ``model_validator(mode="after")`` into the
    inherited ``api_router`` field, so :class:`AppRegistry` mounts it through the
    same seam with no registry change. ``build_router`` reads only
    definition-authored identity (``name``, ``owner``); the registry's
    ``_bind_definition`` overrides only display-only fields
    (``display_name`` / ``uri_path`` / …), none of which the router consumes, so
    the prebuilt router stays correct under binding. A definition must therefore
    not have its ``name`` overridden by a legacy activation entry.

    The escape-hatch ladder, in order of preference, when a plugin's need is not
    expressible declaratively:

    1. Flag a capability (``AppCapabilities`` verb toggles).
    2. Override a handler (``update_handler`` / ``delete_handler`` /
       ``create_response_model``).
    3. Cascade hooks (the ``cascade`` knob feeding ``derived`` / ``predecessors``).
    4. ``extra_routes`` — appended last, so a derived route always wins a path
       collision. A fixed collection-root ``GET`` (for example ``/ping``) is
       therefore shadowed by the greedy ``GET /{detail_path_param}`` detail route;
       mount such a route under a sub-prefix on the extra router.
    5. Fall through to a bare ``BaseApp`` plus the Layer 1 helpers used directly.

    The spine-knob rule: a definition knob earns first-class support only with at
    least three consuming apps; otherwise it is a handler override or an extra
    route.

    :param owner: The task owner the list route filters by and the envelopes
        carry.
    :param create_model: The model-first ``AppFormModel`` subclass whose fields
        drive the derived schema and create form. Mutually exclusive with the
        transitional ``schema=`` passthrough; one of the two is required.
    :param response_model: The list/detail response model. Required.
    :param views: The presentation bundle (layout, list/detail views, UI
        capabilities). Its ``layout`` is required when ``create_model`` is set.
    :param task_spec_builder: A pure ``(form, resolved) -> EnvelopeSpec`` builder
        for the three-phase create path. Defaults to ``None``.
    :param payload_builder: A ``(form, inventory_api) -> TaskWrite`` dependency
        used directly as the create payload, bypassing the three-phase path.
        Required for a ``schema=`` app (no ``AppFormModel`` to introspect refs).
        Defaults to ``None``.
    :param script_source: Reserved seam for the deferred ``ScriptSource`` flavor;
        mutually exclusive with ``task_spec_builder``. Defaults to ``None``.
    :param get_task: A custom task-by-name dependency whose inner path parameter
        matches a non-default ``detail_path_param``. Defaults to ``None`` (the
        per-owner :func:`make_task_dep` callable, whose path parameter is
        ``task_name``).
    :param capabilities: The verb toggles gating route derivation. Defaults to
        all-default :class:`AppCapabilities`.
    :param pagination: A ``make_pagination_dep(...)`` callable; when set the list
        route paginates. Defaults to ``None``.
    :param connectivity_check: Whether the create route runs the post-creation
        connectivity probe. Defaults to ``False``.
    :param cascade: The derived-task / predecessor specs. Defaults to ``None``.
    :param extra_routes: Extra routers included after the derived routes, so a
        derived route always wins a path collision. A fixed collection-root
        ``GET`` is shadowed by the greedy detail route — mount it under a
        sub-prefix on the extra router. Defaults to ``()``.
    :param detail_path_param: The detail/update/delete path-parameter name.
        Defaults to ``"task_name"``; any other value requires a matching
        ``get_task``.
    :param create_response_model: An explicit create response model override.
        Defaults to ``None``.
    :param update_handler: A fully-formed ``PUT`` handler, derived only when
        ``capabilities.update``. Defaults to ``None``.
    :param delete_handler: A fully-formed ``DELETE`` handler, derived only when
        ``capabilities.delete``. Defaults to ``None``.
    :param execute_write_model: The execute request body model; required when
        ``capabilities.execute``. Defaults to ``None``.
    :param execute_response_model: The execute response model; required when
        ``capabilities.execute``. Defaults to ``None``.
    :param capabilities_provider: A sync provider returning the runtime
        ``GET /capabilities`` response model. Defaults to ``None`` (no
        capabilities route).
    """

    owner: TaskOwner
    create_model: type[AppFormModel] | None = None
    response_model: type[BaseModel]
    views: SkipValidation[Views] = Views()
    task_spec_builder: TaskSpecBuilder | None = None
    payload_builder: Callable[..., Awaitable[TaskWrite]] | None = None
    script_source: Any = None
    get_task: Callable[..., Awaitable[Task]] | None = None
    capabilities: AppCapabilities = AppCapabilities()
    pagination: PaginationDependency | None = None
    connectivity_check: bool = False
    cascade: SkipValidation[Cascade | None] = None
    extra_routes: tuple[APIRouter, ...] = ()
    detail_path_param: str = "task_name"
    create_response_model: type[BaseModel] | None = None
    update_handler: Callable[..., Awaitable[Any]] | None = None
    delete_handler: Callable[..., Awaitable[Any]] | None = None
    execute_write_model: type[BaseModel] | None = None
    execute_response_model: type[BaseModel] | None = None
    capabilities_provider: Callable[..., BaseModel] | None = None

    _task_getter: Callable[..., Awaitable[Task]] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _build_api_router(self) -> Self:
        """Validate the definition, bind the task dependency, and build the router.

        :return: The validated app with ``api_router`` computed.
        :raises ValueError: When the definition is internally inconsistent (see
            :meth:`_validate_definition`).
        """
        self._validate_definition()
        self._task_getter = self.get_task or make_task_dep(self.owner)
        self.api_router = self.build_router()
        return self

    def _validate_definition(self) -> None:
        """Reject an internally-inconsistent definition at construction.

        :raises ValueError: When the schema source, the create-payload path, or
            the route knobs are inconsistent (see the per-aspect helpers).
        """
        self._validate_schema_source()
        self._validate_create_path()
        self._validate_route_knobs()

    def _validate_schema_source(self) -> None:
        """Validate the create_model / ``schema=`` source is unambiguous.

        :raises ValueError: When both or neither of ``create_model`` and
            ``schema=`` are set; or when a ``create_model`` lacks a ``task_name``
            field or its ``views.layout``.
        """
        has_create_model = self.create_model is not None
        has_schema = self.app_schema is not None
        if has_create_model and has_schema:
            raise ValueError(
                "TaskExecutionApp: set exactly one of create_model or schema=, not both"
            )
        if not has_create_model and not has_schema:
            raise ValueError(
                "TaskExecutionApp: set exactly one schema source — a create_model "
                "(model-first) or schema= (transitional passthrough)"
            )
        if not has_create_model:
            return
        if "task_name" not in self.create_model.model_fields:
            raise ValueError(
                "TaskExecutionApp: create_model must declare a task_name field"
            )
        if self.views.layout is None:
            raise ValueError(
                "TaskExecutionApp: views.layout is required to derive the schema "
                "from a create_model"
            )

    def _validate_create_path(self) -> None:
        """Validate the create-payload escape hatches are unambiguous and present.

        :raises ValueError: When a ``schema=`` app supplies a ``task_spec_builder``;
            when ``task_spec_builder`` collides with ``script_source`` or
            ``payload_builder``; when a create-enabled app has no payload source; or
            when a create-disabled app sets a create-route option
            (``connectivity_check`` or ``create_response_model``).
        """
        if self.app_schema is not None and self.task_spec_builder is not None:
            raise ValueError(
                "TaskExecutionApp: a schema= app has no AppFormModel to introspect "
                "references; supply a payload_builder rather than a task_spec_builder"
            )
        if self.task_spec_builder is not None and self.script_source is not None:
            raise ValueError(
                "TaskExecutionApp: task_spec_builder and script_source are mutually "
                "exclusive"
            )
        if self.payload_builder is not None and self.task_spec_builder is not None:
            raise ValueError(
                "TaskExecutionApp: set either payload_builder or task_spec_builder "
                "for the create path, not both"
            )
        if (
            self.capabilities.create
            and self.payload_builder is None
            and self.task_spec_builder is None
        ):
            raise ValueError(
                "TaskExecutionApp: the create capability needs a payload source — a "
                "task_spec_builder or a payload_builder"
            )
        if not self.capabilities.create and (
            self.connectivity_check or self.create_response_model is not None
        ):
            raise ValueError(
                "TaskExecutionApp: connectivity_check and create_response_model are "
                "create-route options; enable capabilities.create or drop them"
            )

    def _validate_route_knobs(self) -> None:
        """Validate the detail-path and execute route knobs.

        :raises ValueError: When a non-default ``detail_path_param`` has no custom
            ``get_task``; or when an execute-enabled app lacks its models.
        """
        if self.detail_path_param != "task_name" and self.get_task is None:
            raise ValueError(
                "TaskExecutionApp: detail_path_param other than 'task_name' requires "
                "a custom get_task whose inner path parameter matches it"
            )
        if self.capabilities.execute and (
            self.execute_write_model is None or self.execute_response_model is None
        ):
            raise ValueError(
                "TaskExecutionApp: the execute capability needs execute_write_model "
                "and execute_response_model"
            )

    @property
    def task_dep(self) -> Any:
        """Return the ``Annotated[Task, Depends(...)]`` task-by-name alias.

        Exposes the bound per-owner task dependency for use by ``extra_routes``
        and tests; the derived execute route consumes the same alias.

        :return: An ``Annotated[Task, Depends(get_task)]`` dependency alias.
        """
        task_by_name = Depends(self._task_getter)
        return Annotated[Task, task_by_name]

    def build_router(self) -> APIRouter:
        """Compose the derived router from the Layer 1 helpers.

        Register ``GET /capabilities`` (when a provider is set) before including
        the derived CRUD router, because the CRUD router's greedy
        ``GET /{detail_path_param}`` route would otherwise shadow the fixed
        capabilities path. The derived CRUD router already owns ``GET /schema``,
        so this method never calls ``schema_endpoint`` itself. ``extra_routes``
        are included last so a derived route always wins a path collision.

        :return: The composed plugin ``APIRouter``.
        """
        router = APIRouter()
        plugin_schema = self._resolve_plugin_schema()

        if self.capabilities_provider is not None:
            capabilities_endpoint(router, self.capabilities_provider)

        crud = derive_crud_routes(
            plugin_schema,
            task_owner=self.owner,
            get_task=self._task_getter,
            response_builder=self._build_response_builder(),
            create_payload=(
                self._build_create_payload() if self.capabilities.create else None
            ),
            create_response_builder=self._build_create_response_builder(),
            connectivity_check=self.connectivity_check,
            detail_path_param=self.detail_path_param,
            pagination_dep=self.pagination,
            update_handler=self.update_handler if self.capabilities.update else None,
            delete_handler=self.delete_handler if self.capabilities.delete else None,
        )
        router.include_router(crud)

        if self.capabilities.execute:
            derive_execute_route(
                router,
                task_dep=self.task_dep,
                write_model=self.execute_write_model,
                response_model=self.execute_response_model,
                name=f"{self.name}_api_execute",
            )

        for extra in self.extra_routes:
            router.include_router(extra)

        return router

    def _resolve_plugin_schema(self) -> PluginSchema:
        """Return the schema, either the ``schema=`` passthrough or a derived one.

        :return: The plugin schema the derived routes register and serve.
        """
        if self.app_schema is not None:
            return self.app_schema

        cascade = self.cascade or Cascade()
        return derive_plugin_schema(
            self.create_model,
            self.views.layout,
            name=self.name,
            display_name=self.display_name,
            capabilities=self.views.capabilities,
            list_view=self.views.list_view,
            detail_view=self.views.detail_view,
            derived=list(cascade.derived) or None,
            predecessors=list(cascade.predecessors) or None,
        )

    def _build_response_builder(self) -> TaskResponseBuilder:
        """Return a sync list/detail response builder over ``response_model``.

        :return: A ``(task, *, status) -> response_model`` builder whose return
            annotation supplies the derived list/detail response model.
        """
        response_model = self.response_model

        def _builder(
            task: Task, *, status: TaskHistoryStatusEnum | None = None
        ) -> response_model:
            return build_default_task_response(response_model, task, status)

        return _builder

    def _build_create_response_builder(self) -> TaskResponseBuilder | None:
        """Return a create response builder when ``create_response_model`` is set.

        :return: A sync builder over ``create_response_model``, or ``None`` when
            no explicit create response model is configured.
        """
        if self.create_response_model is None:
            return None

        create_response_model = self.create_response_model

        def _builder(
            task: Task, *, status: TaskHistoryStatusEnum | None = None
        ) -> create_response_model:
            return build_default_task_response(create_response_model, task, status)

        return _builder

    def _build_create_payload(self) -> Callable[..., Awaitable[TaskWrite]]:
        """Return the create-payload dependency for the derived create route.

        Use the ``payload_builder`` escape hatch verbatim when supplied;
        otherwise build the three-phase (Resolve → Assemble → Envelope)
        dependency over the ``create_model``, reading the envelope's ``name`` and
        ``alert_on_fail`` from the parsed form.

        :return: The create-payload dependency declaring the request body.
        """
        if self.payload_builder is not None:
            return self.payload_builder

        spec_builder = self.task_spec_builder
        owner = self.owner
        form_param = Annotated[self.create_model, Form()]

        async def _create_payload(
            form: form_param, inventory_api: InventoryAPI
        ) -> TaskWrite:
            resolved = await resolve_refs(form, inventory_api)
            spec = spec_builder(form, resolved)
            return assemble_envelope(
                spec,
                resolved,
                name=form.task_name,
                owner=owner,
                alert_on_fail=getattr(form, "alert_on_fail", False),
            )

        return _create_payload
