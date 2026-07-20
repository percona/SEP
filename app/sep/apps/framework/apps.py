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
(:func:`~app.sep.apps.framework.api.derive_crud_routes`,
:func:`~app.sep.apps.framework.api.derive_execute_route`,
:func:`~app.sep.apps.framework.api.capabilities_endpoint`) and the model-first
form DSL into a complete derived ``APIRouter`` from a single declarative object,
so a task app no longer hand-wires those helpers per plugin. The derived router
is computed once at construction into ``api_router`` so the existing
:class:`~app.sep.apps.framework.registry.AppRegistry` mounts it through the
same ``api_router`` seam with no registry change.
"""

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Self

from fastapi import APIRouter, Body, Depends, Form, params
from fastapi.routing import APIRoute
from pydantic import (
    BaseModel,
    Field,
    model_validator,
    PrivateAttr,
    SkipValidation,
    TypeAdapter,
)

from app.core.pagination import make_pagination_dep, PaginationDependency
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.api import (
    capabilities_endpoint,
    derive_crud_routes,
    derive_execute_route,
    derive_script_routes,
)
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.framework.connectivity import CONNECTIVITY_WARNING_FIELD
from app.sep.apps.framework.deps import make_task_dep
from app.sep.apps.framework.form_dsl import (
    AppFormModel,
    derive_app_schema,
    FormLayout,
    iter_service_refs,
)
from app.sep.apps.framework.responses import (
    BaseTaskResponse,
    build_default_task_response,
    TaskResponseBuilder,
)
from app.sep.apps.framework.schema import (
    AppSchema,
    Capabilities,
    ChainedPredecessor,
    DerivedTask,
    DetailView,
    ListView,
    RelatedApp,
)
from app.sep.apps.framework.script_source import ScriptSource
from app.sep.apps.framework.spec import (
    assemble_envelope,
    EnvelopeSpec,
    resolve_refs,
    ResolvedEntities,
    stamp_form_input,
    validate_arg_formats,
)
from app.sep.deps import InventoryAPI, make_conflict_guard, protected_task_guard
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskWrite

__all__ = [
    "NO_PAGINATION",
    "UNGUARDED",
    "AppCapabilities",
    "Cascade",
    "ListFilterConfig",
    "StaticMount",
    "TaskExecutionApp",
    "Views",
]

TaskSpecBuilder = Callable[[AppFormModel, ResolvedEntities], EnvelopeSpec]


class _Unguarded:
    """Mark a derived destructive route as opting out of the default guards.

    A named singleton (mirroring the :data:`~app.sep.apps.framework.form_dsl` DSL's
    ``_UNSET`` idiom) so an author's opt-out reads as a greppable, importable
    :data:`UNGUARDED` rather than an anonymous marker. Distinct from the field
    default ``()`` (apply the framework guards) and a non-empty tuple (per-app
    override).
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """Return the marker name so tracebacks and reprs read ``UNGUARDED``."""
        return "UNGUARDED"


UNGUARDED = _Unguarded()


class _NoPagination:
    """Mark a derived list route as explicitly opting out of pagination.

    A named singleton (mirroring :data:`UNGUARDED`) so an author's opt-out reads
    as a greppable, importable :data:`NO_PAGINATION` rather than ``None`` — which
    stays a purely internal route-shape switch in
    :mod:`~app.sep.apps.framework.api`.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """Return the marker name so tracebacks and reprs read ``NO_PAGINATION``."""
        return "NO_PAGINATION"


NO_PAGINATION = _NoPagination()


class AppCapabilities(BaseModel):
    """Toggle which verbs a ``TaskExecutionApp`` derives.

    Distinct from the schema-side
    :class:`~app.sep.apps.framework.schema.Capabilities` (UI feature flags
    serialised inside ``GET /schema``): this model gates *route derivation* only
    and is never serialised, so it cannot change the ``GET /schema`` wire format.

    :param create: Whether to derive the ``POST /`` create route. Defaults to
        ``True``.
    :param detail: Whether to derive the greedy ``GET /{task_name}`` detail
        route. Set ``False`` to suppress it so a custom detail route in
        ``extra_routes`` (for example one doing satellite-to-parent resolution or
        async sibling aggregation) wins the path instead of being shadowed.
        Defaults to ``True``.
    :param list: Whether to derive the ``GET /`` list route. Set ``False`` to
        suppress it so a custom collection-root ``GET /`` in ``extra_routes`` (for
        example a two-query union list the paginated derived route cannot express)
        wins the path instead of being shadowed. Defaults to ``True``.
    :param execute: Whether to derive the ``POST /{task_name}/execute`` route.
        Defaults to ``True``.
    :param update: Whether to derive a ``PUT /{task_name}`` route. Derives a
        standard create-mirroring default unless an ``update_handler`` overrides
        it. Defaults to ``False``.
    :param delete: Whether to derive a ``DELETE /{task_name}`` route. Derives a
        plain fetch-then-delete default unless a ``delete_handler`` overrides it.
        Defaults to ``False``.
    """

    create: bool = True
    detail: bool = True
    list: bool = True
    execute: bool = True
    update: bool = False
    delete: bool = False


class ListFilterConfig(BaseModel):
    """Collapse the derived list route's filter knobs into one config object.

    Carries the ``status`` / ``service_type`` query-parameter toggles plus the
    server-side ``roots_only`` and ``extra_params`` upstream filters. The
    server-side filters keep the paginated ``total`` accurate (the Tasks API
    applies them upstream, so no client-side row dropping corrupts the count):

    :param status: Whether the list route exposes a ``status`` query parameter
        wired to the pipeline's latest-status filter. Defaults to ``False``.
    :param service_type: Whether the list route exposes a ``service_type`` query
        parameter that short-circuits to an empty result when it differs from the
        app's fixed ``service_type``. Requires ``service_type`` on the app.
        Defaults to ``False``.
    :param roots_only: Whether to send ``parent_is_null=true`` upstream so derived
        sibling tasks are hidden and only parent (root) tasks are listed. Defaults
        to ``False``.
    :param extra_params: Fixed upstream task-list query parameters merged into
        every list request (an app's own ``{"some_field": "some_value"}``
        discriminator, applied server-side). Defaults to an empty mapping.
    """

    status: bool = False
    service_type: bool = False
    roots_only: bool = False
    extra_params: dict[str, str] = Field(default_factory=dict)


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


@dataclass(frozen=True, slots=True)
class StaticMount:
    """Declare one authenticated static mount for a script app's payload directory.

    Collected from the registry in ``app/sep/main.py`` and mounted through
    :class:`~app.sep.utils.static.AuthenticatedStaticFiles`, so a payload directory
    is never served anonymously.

    :param path: The mount prefix (for example ``/static/snippets``).
    :param directory: The directory served behind authentication.
    :param name: The Starlette mount name used for reverse URL lookups.
    """

    path: str
    directory: Path
    name: str


class TaskExecutionApp(BaseApp):
    """Compose the route-derivation helpers into a derived task-app router from one object.

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
    5. Fall through to a bare ``BaseApp`` plus the route-derivation helpers used directly.

    The spine-knob rule: a definition knob earns first-class support only with at
    least three consuming apps; otherwise it is a handler override or an extra
    route.

    :param owner: The task owner the list route filters by and the envelopes
        carry.
    :param create_model: The model-first ``AppFormModel`` subclass whose fields
        drive the derived schema and create form. Mutually exclusive with the
        transitional ``schema=`` passthrough; one of the two is required.
    :param response_model: The list/detail response model. Defaults to
        :class:`~app.sep.apps.framework.responses.BaseTaskResponse`.
    :param views: The presentation bundle (layout, list/detail views, UI
        capabilities). Its ``layout`` is required when ``create_model`` is set.
    :param task_spec_builder: A pure ``(form, resolved) -> EnvelopeSpec`` builder
        for the three-phase create path. Defaults to ``None``.
    :param alert_detail_builder: The ``"module:function"`` path of a plugin
        callable that enriches the created task's failure alert, stamped onto the
        ``TaskWrite`` by the three-phase create path. Defaults to ``None``.
    :param payload_builder: A ``(form, inventory_api) -> TaskWrite`` dependency
        used directly as the create payload, bypassing the three-phase path.
        Required for a ``schema=`` app (no ``AppFormModel`` to introspect refs).
        Defaults to ``None``.
    :param script_source: A :class:`ScriptSource` backing a script-flavored app:
        ``build_router`` branches to
        :func:`~app.sep.apps.framework.api.derive_script_routes` and bypasses the
        model-first CRUD derivation entirely. Mutually exclusive with
        ``create_model``, ``schema=``, and ``task_spec_builder``; the standard
        create/detail/update/delete capability flags are not derived for a script
        app. Defaults to ``None``.
    :param get_task: A custom task-by-name dependency whose inner path parameter
        matches a non-default ``detail_path_param``. Defaults to ``None`` (the
        per-owner :func:`make_task_dep` callable, whose path parameter is
        ``task_name``).
    :param capabilities: The verb toggles gating route derivation. Defaults to
        all-default :class:`AppCapabilities`.
    :param pagination: The derived list route's pagination knob. Defaults to
        ``make_pagination_dep()`` (page size 50, ceiling 200), so a list route
        paginates unless overridden — a new app is bounded by default. Pass a
        custom ``make_pagination_dep(max_limit=...)`` callable to change the
        ceiling, or the :data:`NO_PAGINATION` sentinel to opt out and serve a plain
        ``list[model]``.
    :param create_form_encoded: Whether the derived create route accepts a
        form-urlencoded body (``Form()``) instead of the default JSON body
        (``Body()``). A create-route option, so it is rejected unless
        ``capabilities.create`` is enabled. Defaults to ``False``.
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
    :param update_handler: A fully-formed ``PUT`` handler overriding the derived
        default; used only when ``capabilities.update``. When ``None`` (default)
        and ``capabilities.update`` is on, the framework derives a standard
        create-mirroring PUT (guarded per ``update_guard``).
    :param delete_handler: A fully-formed ``DELETE`` handler overriding the
        derived default; used only when ``capabilities.delete``. When ``None``
        (default) and ``capabilities.delete`` is on, the framework derives a plain
        fetch-then-delete DELETE.
    :param execute_write_model: The execute request body model used when
        ``capabilities.execute``. Defaults to ``None``, which derives the route
        with the framework's
        :class:`~app.sep.apps.framework.responses.TaskExecuteWrite`.
    :param execute_response_model: The execute response model used when
        ``capabilities.execute``. Defaults to ``None``, which derives the route
        with the framework's
        :class:`~app.sep.apps.framework.responses.TaskExecutionResponse`.
    :param capabilities_provider: A sync provider returning the runtime
        ``GET /capabilities`` response model. Defaults to ``None`` (no
        capabilities route).
    :param service_type: The app's fixed service type, against which
        ``list_filter.service_type`` short-circuits a mismatched query. Required
        when ``list_filter.service_type`` is set. Defaults to ``None``.
    :param list_filter: The derived list route's filter configuration — the
        ``status`` / ``service_type`` query-parameter toggles plus the server-side
        ``roots_only`` and ``extra_params`` upstream filters. Defaults to an
        all-off :class:`ListFilterConfig`.
    :param response_builder: A sync list/detail builder override injecting the
        per-plugin response extras; replaces the framework default builder. When
        ``None`` (default) the framework builds a default list/detail builder
        that stamps ``service_type`` and remaps the ``created_by`` /
        ``last_updated_by`` user-ids to usernames through the bound response
        context. Defaults to ``None``.
    :param detail_response_builder: A sync detail-only builder override; when
        ``None`` the detail route falls back to ``response_builder`` and the list
        model. When set, the create route renders like detail too unless an
        explicit create model is configured. Defaults to ``None``.
    :param detail_response_model: An explicit detail response model overriding
        return-annotation inference on ``detail_response_builder`` (for an exotic
        builder whose return type cannot be introspected). Defaults to ``None``.
    :param response_context_provider: A zero-arg async provider whose once-awaited
        result (for example a username map) is bound as the builders' ``context``
        across the list, detail, and create builds, consumed by the framework
        default builder or an overriding ``response_builder``. Defaults to
        ``None``.
    :param create_extra_deps: Extra create-route dependencies appended after the
        standard auth guard; requires ``capabilities.create``. Defaults to ``()``.
    :param create_response_builder: A sync create-response builder override that
        injects the per-plugin create-response extras and pins a stable
        create-response component (in place of the framework's auto-derived one),
        reused by the derived PUT. When ``None`` (default) a standard app (no
        detail override, and a ``response_model`` that carries
        ``connectivity_warning`` when ``connectivity_check`` is on) reuses the
        framework default create builder over ``response_model``, pinning the
        create component to it. Mutually exclusive with ``create_response_model``
        and requires ``capabilities.create``. Defaults to ``None``.
    :param update_guard: The tri-state guard knob for the *derived* PUT. ``()`` (the
        default) applies the framework default guards — a protected-task check and a
        running-conflict check, resolved off the fetched task. :data:`UNGUARDED`
        opts the route out (bare ``IsApiAuthenticated``). A non-empty
        ``tuple[params.Depends, ...]`` overrides both with the given guards
        verbatim. Requires ``capabilities.update`` and is rejected alongside a full
        ``update_handler`` (except the ``()`` default, always allowed). Defaults to
        ``()``.
    :param delete_guard: The tri-state guard knob for the *derived* DELETE, with the
        same semantics as ``update_guard``: ``()`` applies the framework default
        guards, :data:`UNGUARDED` opts out, and a non-empty tuple overrides.
        Requires ``capabilities.delete`` and is rejected alongside a full
        ``delete_handler`` (except the ``()`` default, always allowed). Defaults to
        ``()``.
    :param description: The plugin description threaded into the derived
        ``GET /schema`` (``AppSchema.description``). Defaults to ``None``.
    :param related_apps: Separately registered apps the React shell surfaces as
        sibling tabs under ``{route_base}/{route_segment}``. Threaded into the
        derived ``GET /schema`` (``AppSchema.related_apps``). Defaults to an
        empty tuple.
    :param static_mounts: Authenticated static mounts for the app's payload
        directories, collected from the registry and mounted in ``app/sep/main.py``
        through :class:`~app.sep.utils.static.AuthenticatedStaticFiles`. Defaults to
        an empty tuple.
    """

    owner: str
    create_model: type[AppFormModel] | None = None
    response_model: type[BaseModel] = BaseTaskResponse
    views: SkipValidation[Views] = Views()
    task_spec_builder: TaskSpecBuilder | None = None
    alert_detail_builder: str | None = None
    payload_builder: Callable[..., Awaitable[TaskWrite]] | None = None
    script_source: SkipValidation[ScriptSource | None] = None
    get_task: Callable[..., Awaitable[Task]] | None = None
    capabilities: AppCapabilities = AppCapabilities()
    pagination: PaginationDependency | _NoPagination = make_pagination_dep()
    create_form_encoded: bool = False
    cascade: SkipValidation[Cascade | None] = None
    extra_routes: tuple[APIRouter, ...] = ()
    detail_path_param: str = "task_name"
    create_response_model: type[BaseModel] | None = None
    update_handler: Callable[..., Awaitable[Any]] | None = None
    delete_handler: Callable[..., Awaitable[Any]] | None = None
    execute_write_model: type[BaseModel] | None = None
    execute_response_model: type[BaseModel] | None = None
    capabilities_provider: Callable[..., BaseModel] | None = None
    service_type: ServiceTypeEnum | None = None
    list_filter: ListFilterConfig = Field(default_factory=ListFilterConfig)
    response_builder: SkipValidation[TaskResponseBuilder | None] = None
    detail_response_builder: SkipValidation[TaskResponseBuilder | None] = None
    detail_response_model: type[BaseModel] | None = None
    response_context_provider: SkipValidation[Callable[[], Awaitable[Any]] | None] = (
        None
    )
    create_extra_deps: tuple[params.Depends, ...] = ()
    create_response_builder: SkipValidation[TaskResponseBuilder | None] = None
    update_guard: tuple[params.Depends, ...] | _Unguarded = ()
    delete_guard: tuple[params.Depends, ...] | _Unguarded = ()
    description: str | None = None
    related_apps: tuple[RelatedApp, ...] = ()
    static_mounts: tuple[StaticMount, ...] = ()

    _task_getter: Callable[..., Awaitable[Task]] | None = PrivateAttr(default=None)

    @property
    def connectivity_check(self) -> bool:
        """Return whether the derived create route runs the connectivity probe.

        An app probes iff the create capability is enabled and its ``create_model``
        declares a ``check_connectivity=True`` ``ServiceRef`` (top-level or nested
        in a one-of branch); that marked service is also the envelope's primary.
        Probe enablement is keyed off ``check_connectivity`` alone — a ``ServiceRef``
        marked ``primary=True`` designates the envelope primary without probing, so it
        does not turn this on.

        :return: ``True`` when the app derives a probing create route.
        """
        if not self.capabilities.create or self.create_model is None:
            return False
        return any(
            ref.check_connectivity for ref in iter_service_refs(self.create_model)
        )

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

        :raises ValueError: When the schema source, the create-payload path, the
            connectivity references, the route knobs, the response/filter knobs, the
            list-view columns, or the ``ArgFormat`` markers are inconsistent (see the
            per-aspect helpers).
        """
        self._validate_schema_source()
        self._validate_create_path()
        self._validate_connectivity_refs()
        self._validate_route_knobs()
        self._validate_detail_suppress()
        self._validate_list_suppress()
        self._validate_response_knobs()
        self._validate_view_columns()
        self._validate_arg_formats()
        self._validate_related_apps()

    def _validate_related_apps(self) -> None:
        """Reject ``related_apps`` on definitions that do not derive a schema.

        ``related_apps`` is schema metadata consumed by the React shell; a
        ``schema=`` passthrough app carries it on ``AppSchema`` directly, and a
        ``script_source`` app serves ``static_schema`` instead. Duplicate
        ``route_segment`` values are rejected here so a typo surfaces at
        construction rather than at runtime routing.

        :raises ValueError: When ``related_apps`` is set on a ``schema=`` or
            ``script_source`` app, or when two entries share a
            ``route_segment``.
        """
        if not self.related_apps:
            return
        if self.script_source is not None:
            raise ValueError(
                "TaskExecutionApp: related_apps is schema metadata for a "
                "model-first app; a script_source app serves static_schema — "
                "drop related_apps"
            )
        if self.app_schema is not None:
            raise ValueError(
                "TaskExecutionApp: a schema= app carries related_apps on "
                "AppSchema — drop related_apps from the definition"
            )
        duplicates = sorted(
            segment
            for segment, count in Counter(
                spec.route_segment for spec in self.related_apps
            ).items()
            if count > 1
        )
        if duplicates:
            raise ValueError(
                "TaskExecutionApp: duplicate related_apps route_segment "
                f"values {duplicates}"
            )

    def _validate_connectivity_refs(self) -> None:
        """Reject an ambiguous or unselectable primary-service configuration.

        A model-first app names its envelope primary with a *designated* marker —
        ``check_connectivity=True`` (which also probes) or ``primary=True`` (which
        designates without probing). At most one ``ServiceRef`` may be designated
        across both markers; a second designation makes the primary ambiguous. A
        model declaring two or more ``ServiceRef`` fields with none designated has
        no determinable primary. A single unmarked ``ServiceRef`` is valid: it is
        the sole primary and the app does not probe. The disambiguation is about the
        primary, not the probe: ``assemble_envelope`` unconditionally stamps the
        primary service onto every task's connectivity host/port and
        ``service_name``, so the primary must be unambiguous even when no probe runs.

        :raises ValueError: When a designated ``ServiceRef`` is also marked
            ``multiple`` (a multi-value field has no single primary), when a
            ``multiple=True`` ``ServiceRef`` would be the primary with no scalar
            designated ref to take its place, when more than one ``ServiceRef`` is
            designated primary (via ``check_connectivity`` and/or ``primary``), or
            when two or more ``ServiceRef`` fields leave no determinable primary.
        """
        if self.create_model is None:
            return
        refs = list(iter_service_refs(self.create_model))
        designated = [ref for ref in refs if ref.check_connectivity or ref.primary]
        if any(ref.multiple for ref in designated):
            raise ValueError(
                "TaskExecutionApp: a create_model declares a multiple=True ServiceRef "
                "designated primary (check_connectivity=True or primary=True); the "
                "envelope primary is a single service and cannot be selected from a "
                "multi-value field — set multiple=False, or drop the primary marker"
            )
        if not designated and any(ref.multiple for ref in refs):
            raise ValueError(
                "TaskExecutionApp: a create_model declares a multiple=True ServiceRef "
                "with no designated primary ServiceRef to serve as the envelope "
                "primary; a multi-value service field cannot resolve to the single "
                "primary assemble_envelope stamps onto every task — mark a scalar "
                "ServiceRef check_connectivity=True or primary=True"
            )
        if len(designated) > 1:
            raise ValueError(
                "TaskExecutionApp: a create_model designates "
                f"{len(designated)} primary ServiceRef fields via check_connectivity "
                "and/or primary; at most one service is the envelope primary — "
                "designate exactly one"
            )
        if not designated and len(refs) > 1:
            raise ValueError(
                "TaskExecutionApp: a create_model declares "
                f"{len(refs)} ServiceRef fields with none designated primary "
                "(check_connectivity=True or primary=True); no envelope primary "
                "is determinable — designate exactly one"
            )

    def _validate_schema_source(self) -> None:
        """Validate the create_model / ``schema=`` source is unambiguous.

        A script-source app derives per-script forms and serves its optional
        plugin-level schema from ``script_source.static_schema``, so it sets neither
        ``create_model`` (no single create form) nor ``schema=`` (a second, ignored
        schema source); both are rejected.

        :raises ValueError: When a script-source app also sets ``create_model`` or
            ``schema=``; when both or neither of ``create_model`` and ``schema=`` are
            set; or when a ``create_model`` lacks a ``task_name`` field or its
            ``views.layout``.
        """
        if self.script_source is not None:
            if self.create_model is not None:
                raise ValueError(
                    "TaskExecutionApp: a script_source app derives per-script forms; "
                    "it has no single create_model — drop create_model"
                )
            if self.app_schema is not None:
                raise ValueError(
                    "TaskExecutionApp: a script_source app serves GET /schema from "
                    "script_source.static_schema — drop schema="
                )
            return
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
            ``payload_builder``; when a ``script_source`` app sets a model-first
            create-route option (``create_response_model``,
            ``create_response_builder``, ``create_form_encoded``, or
            ``create_extra_deps``) the script branch would silently drop; when a
            ``payload_builder`` app also sets ``create_form_encoded`` (which governs
            only the derived three-phase body); when a create-enabled app that is not
            a ``script_source`` app has no payload source (a script source is itself
            the payload mechanism); or when a create-disabled app sets a create-route
            option.
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
        if self.script_source is not None and (
            self.create_response_model is not None
            or self.create_response_builder is not None
            or self.create_form_encoded
            or self.create_extra_deps
        ):
            raise ValueError(
                "TaskExecutionApp: create_response_model, create_response_builder, "
                "create_form_encoded, and create_extra_deps are model-first "
                "create-route options; a script_source app derives no create route — "
                "drop them"
            )
        if self.payload_builder is not None and self.task_spec_builder is not None:
            raise ValueError(
                "TaskExecutionApp: set either payload_builder or task_spec_builder "
                "for the create path, not both"
            )
        if self.payload_builder is not None and self.create_form_encoded:
            raise ValueError(
                "TaskExecutionApp: create_form_encoded governs the derived "
                "three-phase create body; a payload_builder defines its own body "
                "encoding — drop create_form_encoded or the payload_builder"
            )
        if (
            self.capabilities.create
            and self.payload_builder is None
            and self.task_spec_builder is None
            and self.script_source is None
        ):
            raise ValueError(
                "TaskExecutionApp: the create capability needs a payload source — a "
                "task_spec_builder or a payload_builder"
            )
        if not self.capabilities.create and (
            self.create_response_model is not None
            or self.create_response_builder is not None
            or self.create_form_encoded
        ):
            raise ValueError(
                "TaskExecutionApp: create_response_model, create_response_builder, "
                "and create_form_encoded are create-route options; enable "
                "capabilities.create or drop them"
            )
        if self.create_response_model is not None and (
            self.create_response_builder is not None
        ):
            raise ValueError(
                "TaskExecutionApp: set either create_response_model or "
                "create_response_builder, not both — the builder pins its own model"
            )
        if self.create_extra_deps and not self.capabilities.create:
            raise ValueError(
                "TaskExecutionApp: create_extra_deps are create-route dependencies; "
                "enable capabilities.create or drop them"
            )

    @staticmethod
    def _is_explicit_guard(guard: tuple[params.Depends, ...] | _Unguarded) -> bool:
        """Return whether a guard knob is an explicit spec, not the default.

        The field default ``()`` means "apply the framework guards" and is *not*
        explicit; :data:`UNGUARDED` (opt-out) and a non-empty override tuple are.
        Both explicit forms are rejected on a non-derived verb, while the default
        ``()`` is always allowed.

        :param guard: The tri-state ``update_guard`` / ``delete_guard`` value.
        :return: ``True`` for :data:`UNGUARDED` or a non-empty override tuple.
        """
        return isinstance(guard, _Unguarded) or bool(guard)

    def _validate_route_knobs(self) -> None:
        """Validate the detail-path, execute, and update route knobs.

        :raises ValueError: When a non-default ``detail_path_param`` has no custom
            ``get_task``; when an ``update_handler`` or ``delete_handler`` is set
            without its capability enabled (it would otherwise be silently
            dropped); when ``update_guard`` / ``delete_guard`` is an *explicit* spec
            (:data:`UNGUARDED` or an override tuple) on a non-derived verb (no
            capability, or a full handler) — the ``()`` default is always allowed;
            or when the derived update lacks the create capability whose payload it
            rebuilds the body through.
        """
        if self.detail_path_param != "task_name" and self.get_task is None:
            raise ValueError(
                "TaskExecutionApp: detail_path_param other than 'task_name' requires "
                "a custom get_task whose inner path parameter matches it"
            )
        if self.update_handler is not None and not self.capabilities.update:
            raise ValueError(
                "TaskExecutionApp: update_handler overrides the derived PUT; enable "
                "capabilities.update or drop update_handler"
            )
        if self.delete_handler is not None and not self.capabilities.delete:
            raise ValueError(
                "TaskExecutionApp: delete_handler overrides the derived DELETE; enable "
                "capabilities.delete or drop delete_handler"
            )
        if self._is_explicit_guard(self.update_guard) and not self.capabilities.update:
            raise ValueError(
                "TaskExecutionApp: update_guard guards the derived PUT; enable "
                "capabilities.update or drop update_guard"
            )
        if (
            self._is_explicit_guard(self.update_guard)
            and self.update_handler is not None
        ):
            raise ValueError(
                "TaskExecutionApp: update_guard guards the derived PUT; a full "
                "update_handler must declare its own dependencies — drop update_guard "
                "or the update_handler"
            )
        if self._is_explicit_guard(self.delete_guard) and not self.capabilities.delete:
            raise ValueError(
                "TaskExecutionApp: delete_guard guards the derived DELETE; enable "
                "capabilities.delete or drop delete_guard"
            )
        if (
            self._is_explicit_guard(self.delete_guard)
            and self.delete_handler is not None
        ):
            raise ValueError(
                "TaskExecutionApp: delete_guard guards the derived DELETE; a full "
                "delete_handler must declare its own dependencies — drop delete_guard "
                "or the delete_handler"
            )
        derives_update = self.capabilities.update and self.update_handler is None
        if derives_update and not self.capabilities.create:
            raise ValueError(
                "TaskExecutionApp: the derived PUT rebuilds the body through the "
                "create payload; enable capabilities.create or supply an "
                "update_handler"
            )

    def _validate_response_knobs(self) -> None:
        """Validate the list-filter knob is self-consistent.

        :raises ValueError: When ``list_filter.service_type`` is set without a
            ``service_type`` to filter against.
        """
        if self.list_filter.service_type and self.service_type is None:
            raise ValueError(
                "TaskExecutionApp: list_filter.service_type needs a service_type to "
                "filter against; set service_type or drop the filter"
            )

    def _extra_routes_have_detail(self) -> bool:
        """Return whether ``extra_routes`` register a ``GET`` on the detail path.

        :return: ``True`` when a custom ``GET /{detail_path_param}`` route is
            present across the ``extra_routes`` routers.
        """
        detail_path = f"/{{{self.detail_path_param}}}"
        return any(
            isinstance(route, APIRoute)
            and route.path == detail_path
            and "GET" in route.methods
            for extra in self.extra_routes
            for route in extra.routes
        )

    def _extra_routes_have_list(self) -> bool:
        """Return whether ``extra_routes`` register a ``GET`` on the collection root.

        :return: ``True`` when a custom ``GET /`` route is present across the
            ``extra_routes`` routers.
        """
        return any(
            isinstance(route, APIRoute) and route.path == "/" and "GET" in route.methods
            for extra in self.extra_routes
            for route in extra.routes
        )

    def _validate_list_suppress(self) -> None:
        """Reject an inconsistent ``capabilities.list`` suppress configuration.

        The suppress toggle and a custom list route are mutually implied: the
        derived ``GET /`` is always registered while ``capabilities.list`` is on,
        so a custom collection-root list route only wins the path when the derived
        one is suppressed, and suppressing it without a replacement leaves the app
        with no list route at all.

        :raises ValueError: When ``capabilities.list`` and a custom collection-root
            ``GET /`` route in ``extra_routes`` disagree.
        """
        has_custom_list = self._extra_routes_have_list()
        if self.capabilities.list and has_custom_list:
            raise ValueError(
                "TaskExecutionApp: a custom GET / list route in extra_routes is "
                "shadowed by the derived list; set capabilities.list=False to "
                "suppress the derived one"
            )
        if not self.capabilities.list and not has_custom_list:
            raise ValueError(
                "TaskExecutionApp: capabilities.list=False suppresses the derived "
                "list route but no custom GET / is registered in extra_routes; add "
                "one or re-enable capabilities.list"
            )

    def _validate_detail_suppress(self) -> None:
        """Reject an inconsistent ``capabilities.detail`` suppress configuration.

        The suppress toggle and a custom detail route are mutually implied: the
        derived ``GET /{detail_path_param}`` is greedy, so a custom detail route
        only wins the path when the derived one is suppressed, and suppressing it
        without a replacement leaves the app with no detail route at all. The
        detail-builder overrides are dead config once the derived detail is off.

        :raises ValueError: When ``capabilities.detail`` and a custom detail route
            in ``extra_routes`` disagree, or when a detail-builder override is set
            while ``capabilities.detail`` is ``False``.
        """
        has_custom_detail = self._extra_routes_have_detail()
        if self.capabilities.detail and has_custom_detail:
            raise ValueError(
                "TaskExecutionApp: a custom GET detail route in extra_routes is "
                "shadowed by the greedy derived detail; set capabilities.detail="
                "False to suppress the derived one"
            )
        if not self.capabilities.detail and not has_custom_detail:
            raise ValueError(
                "TaskExecutionApp: capabilities.detail=False suppresses the derived "
                "detail route but no custom GET /{detail_path_param} is registered "
                "in extra_routes; add one or re-enable capabilities.detail"
            )
        if not self.capabilities.detail and (
            self.detail_response_builder is not None
            or self.detail_response_model is not None
        ):
            raise ValueError(
                "TaskExecutionApp: detail_response_builder / detail_response_model "
                "are dead config when capabilities.detail=False; drop them or "
                "re-enable capabilities.detail"
            )

    def _validate_view_columns(self) -> None:
        """Reject a ``list_view`` column key that is not a response-model field.

        Enforce at construction — collecting every unknown column and raising once —
        so a column typo is rejected up front rather than rendering a blank column at
        runtime. Skip ``schema=`` passthrough apps (no ``create_model``) and
        model-first apps that declare no ``list_view``; detail-view ``data.*`` paths
        stay free-form and are checked by the conformance suite instead.

        :raises ValueError: When a ``views.list_view`` column ``key`` is not a field
            on ``response_model``.
        """
        if self.create_model is None or self.views.list_view is None:
            return
        response_fields = set(self.response_model.model_fields)
        unknown = [
            column.key
            for column in self.views.list_view.columns
            if column.key not in response_fields
        ]
        if unknown:
            raise ValueError(
                f"TaskExecutionApp: list_view column keys {unknown} are not fields "
                f"on {self.response_model.__name__}"
            )

    def _validate_arg_formats(self) -> None:
        """Reject a create-model ``ArgFormat`` template the assembler would silently drop.

        Delegate to
        :func:`~app.sep.apps.framework.spec.validate_arg_formats` for a
        model-first app so a typo'd placeholder or a flag template on a non-``bool``
        field fails fast at construction rather than dropping the argument at
        task-creation time. Skip a ``schema=`` passthrough app, which has no
        ``create_model`` to introspect.

        :raises ValueError: When a ``create_model`` field's ``ArgFormat`` template
            carries an unsupported placeholder or is a flag template on a non-``bool``
            field.
        """
        if self.create_model is None:
            return
        validate_arg_formats(self.create_model)

    @property
    def task_dep(self) -> Any:
        """Return the ``Annotated[Task, Depends(...)]`` task-by-name alias.

        Exposes the bound per-owner task dependency for use by ``extra_routes``
        and tests; the derived execute route consumes the same alias.

        :return: An ``Annotated[Task, Depends(get_task)]`` dependency alias.
        """
        task_by_name = Depends(self._task_getter)
        return Annotated[Task, task_by_name]

    def _resolve_list_extra_params(self) -> dict[str, str]:
        """Return the fixed upstream task-list filters the derived list applies.

        Merge the ``roots_only`` server-side ``parent_is_null=true`` filter with
        the app's ``list_filter.extra_params``. These are sent to the Tasks API,
        so the paginated ``total`` stays accurate (no client-side row dropping).

        :return: The merged upstream query parameters for the derived list route.
        """
        params = dict(self.list_filter.extra_params)
        if self.list_filter.roots_only:
            params["parent_is_null"] = "true"
        return params

    def _resolve_guard(
        self, guard: tuple[params.Depends, ...] | _Unguarded, *, action: str
    ) -> tuple[params.Depends, ...]:
        """Resolve a guard knob to the dependency tuple for a derived destructive route.

        The default guards resolve the protected-task and running-conflict checks
        off the cached ``self._task_getter`` (not a fixed ``task_name`` path
        parameter), so they stay decoupled from ``detail_path_param`` and share the
        one task fetch with the route handler.

        :param guard: The tri-state ``update_guard`` / ``delete_guard`` value.
        :param action: The verb (``"edit"`` for PUT, ``"delete"`` for DELETE)
            gating both the derive check and the protected-task guard's 409 detail.
        :return: ``()`` for a non-derived verb or an :data:`UNGUARDED` opt-out; the
            override tuple verbatim for a non-empty tuple; otherwise the framework
            default protected-task + running-conflict guards for the ``()`` default.
        """
        derives = (
            self.capabilities.update and self.update_handler is None
            if action == "edit"
            else self.capabilities.delete and self.delete_handler is None
        )
        if not derives or isinstance(guard, _Unguarded):
            return ()
        if guard:
            return guard
        return (
            Depends(protected_task_guard(self._task_getter, action=action)),
            Depends(make_conflict_guard(self._task_getter)),
        )

    def build_router(self) -> APIRouter:
        """Compose the derived router from the route-derivation helpers.

        A ``script_source`` app branches early to
        :func:`~app.sep.apps.framework.api.derive_script_routes` and never reaches
        the model-first CRUD derivation, but still gets its ``GET /capabilities``
        provider and ``extra_routes`` (the auxiliary surface a migrating script
        plugin needs, for example preview/download/approval). Otherwise register
        ``GET /capabilities`` (when a provider is set) before including the derived
        CRUD router, because the CRUD router's greedy ``GET /{detail_path_param}``
        route would otherwise shadow the fixed capabilities path. The derived CRUD
        router already owns ``GET /schema``, so this method never calls
        ``schema_endpoint`` itself. ``extra_routes`` are included last so a derived
        route always wins a path collision.

        :return: The composed plugin ``APIRouter``.
        """
        pagination_dep = (
            None if isinstance(self.pagination, _NoPagination) else self.pagination
        )
        if self.script_source is not None:
            router = derive_script_routes(
                self.script_source,
                name=self.name,
                pagination_dep=pagination_dep,
            )
            if self.capabilities_provider is not None:
                capabilities_endpoint(router, self.capabilities_provider)
            for extra in self.extra_routes:
                router.include_router(extra)
            return router

        router = APIRouter()
        plugin_schema = self._resolve_plugin_schema()

        if self.create_model is not None:
            self._materialize_create_model_schema()

        if self.capabilities_provider is not None:
            capabilities_endpoint(router, self.capabilities_provider)

        crud = derive_crud_routes(
            plugin_schema,
            task_owner=self.owner,
            get_task=self._task_getter,
            response_builder=self._build_response_builder(),
            detail_response_builder=self.detail_response_builder,
            detail_response_model=self.detail_response_model,
            create_payload=(
                self._build_create_payload() if self.capabilities.create else None
            ),
            create_response_builder=self._build_create_response_builder(),
            connectivity_check=self.connectivity_check,
            detail_path_param=self.detail_path_param,
            pagination_dep=pagination_dep,
            list_status_filter=self.list_filter.status,
            list_service_type=(
                self.service_type if self.list_filter.service_type else None
            ),
            list_extra_params=self._resolve_list_extra_params(),
            derive_list=self.capabilities.list,
            derive_detail=self.capabilities.detail,
            context_provider=self.response_context_provider,
            create_extra_deps=self.create_extra_deps,
            update_enabled=self.capabilities.update,
            update_handler=self.update_handler,
            update_extra_deps=self._resolve_guard(self.update_guard, action="edit"),
            delete_enabled=self.capabilities.delete,
            delete_handler=self.delete_handler,
            delete_extra_deps=self._resolve_guard(self.delete_guard, action="delete"),
        )
        router.include_router(crud)

        if self.capabilities.execute:
            execute_models = {}
            if self.execute_write_model is not None:
                execute_models["write_model"] = self.execute_write_model
            if self.execute_response_model is not None:
                execute_models["response_model"] = self.execute_response_model
            derive_execute_route(
                router,
                task_dep=self.task_dep,
                name=f"{self.name}_api_execute",
                **execute_models,
            )

        for extra in self.extra_routes:
            router.include_router(extra)

        return router

    def _materialize_create_model_schema(self) -> None:
        """Build the create model's validation schema once, deterministically.

        FastAPI builds a fresh request-body schema per derived route (``POST /``
        and the derived ``PUT /{...}``) from ``create_model``. For a Pydantic v2
        discriminated-union ("one-of") body, that per-route construction reads
        global model/definition orderings that vary with ``PYTHONHASHSEED``, so the
        two routes can derive divergent core schemas — the derived update route
        intermittently rejecting a body the create route accepts. Force one clean
        build here, with the full app-model namespace loaded, and cache it on the
        model class so both routes reuse the single materialized schema instead of
        each re-deriving the one-of core schema.
        """
        self.create_model.model_rebuild(force=True)
        # Built purely to force the one-of core schema into pydantic's shared
        # definition cache now; the adapter itself is intentionally discarded.
        TypeAdapter(self.create_model)

    def _resolve_plugin_schema(self) -> AppSchema:
        """Return the schema, either the ``schema=`` passthrough or a derived one.

        :return: The plugin schema the derived routes register and serve.
        """
        if self.app_schema is not None:
            return self.app_schema

        cascade = self.cascade or Cascade()
        return derive_app_schema(
            self.create_model,
            self.views.layout,
            name=self.name,
            display_name=self.display_name,
            description=self.description,
            capabilities=self.views.capabilities,
            list_view=self.views.list_view,
            detail_view=self.views.detail_view,
            derived=list(cascade.derived) or None,
            predecessors=list(cascade.predecessors) or None,
            related_apps=list(self.related_apps) or None,
        )

    def _default_task_response_builder(
        self, response_model: type[BaseModel]
    ) -> TaskResponseBuilder:
        """Build the framework default response builder over ``response_model``.

        Stamp the app's ``service_type`` and remap the ``created_by`` /
        ``last_updated_by`` user-ids to usernames through the bound response
        context, falling back to the raw id when the map lacks an entry. Shared by
        the list/detail and create/update response surfaces so a standard app
        needs no per-app builder; left ``connectivity_warning`` at the model
        default for the framework to merge on create/update.

        :param response_model: The model the builder constructs; its return
            annotation supplies the derived route's response model.
        :return: A ``(task, *, status, context) -> response_model`` builder.
        """
        service_type = self.service_type

        def _builder(
            task: Task,
            *,
            status: TaskHistoryStatusEnum | None = None,
            last_executed_at: datetime | None = None,
            context: dict[str, str] | None = None,
        ) -> response_model:
            mapping = context or {}
            return build_default_task_response(
                response_model,
                task,
                status,
                last_executed_at=last_executed_at,
                extras={
                    "created_by": mapping.get(task.created_by, task.created_by),
                    "last_updated_by": mapping.get(
                        task.last_updated_by, task.last_updated_by
                    ),
                    "service_type": service_type,
                },
            )

        return _builder

    def _build_response_builder(self) -> TaskResponseBuilder:
        """Return the plugin's ``response_builder`` override, or a default builder.

        Use the supplied ``response_builder`` verbatim when set; otherwise build
        the framework default builder (stamp ``service_type`` + remap usernames)
        over ``response_model``.

        :return: A ``(task, *, status, context) -> response_model`` builder whose
            return annotation supplies the derived list/detail response model.
        """
        if self.response_builder is not None:
            return self.response_builder
        return self._default_task_response_builder(self.response_model)

    def _build_create_response_builder(self) -> TaskResponseBuilder | None:
        """Return the create response builder for the derived create/update routes.

        Use the supplied ``create_response_builder`` verbatim when set (it injects
        the per-plugin create-response extras and pins a stable create-response
        component). Otherwise, when a ``create_response_model`` is set, build a
        no-extras sync builder over it — the builder accepts (and ignores) a
        ``context`` keyword so the create route can bind a
        ``response_context_provider``'s result uniformly.

        When neither is set, a create-enabled standard app reuses the framework
        default builder over ``response_model``, pinning the create component to
        it (no auto-derived ``<App>CreateResponse``). That shortcut is skipped —
        falling back to ``None`` so the framework's existing create-model
        resolution applies — when create is disabled (there is no create route to
        attach a builder to), when a detail override means the create route
        renders like detail (its base is the detail model, not ``response_model``),
        when ``connectivity_check`` is on but ``response_model`` cannot carry
        the probe ``connectivity_warning``, or when the app supplies a custom
        ``response_builder`` (whose per-plugin extras the default builder cannot
        replicate, so the create route must reuse that builder via the
        ``base_builder`` fallback).

        :return: The explicit ``create_response_builder``; a no-extras builder over
            ``create_response_model``; the framework default builder over
            ``response_model``; or ``None`` when the default shortcut is skipped.
        """
        if self.create_response_builder is not None:
            return self.create_response_builder

        if self.create_response_model is not None:
            create_response_model = self.create_response_model

            def _builder(
                task: Task,
                *,
                status: TaskHistoryStatusEnum | None = None,
                **_: Any,
            ) -> create_response_model:
                return build_default_task_response(create_response_model, task, status)

            return _builder

        renders_like_detail = (
            self.detail_response_builder is not None
            or self.detail_response_model is not None
        )
        base_cannot_hold_warning = (
            self.connectivity_check
            and CONNECTIVITY_WARNING_FIELD not in self.response_model.model_fields
        )
        if (
            not self.capabilities.create
            or renders_like_detail
            or base_cannot_hold_warning
            or self.response_builder is not None
        ):
            return None
        return self._default_task_response_builder(self.response_model)

    def _build_create_payload(self) -> Callable[..., Awaitable[TaskWrite]]:
        """Return the create-payload dependency for the derived create route.

        Use the ``payload_builder`` escape hatch verbatim when supplied;
        otherwise build the three-phase (Resolve → Assemble → Envelope)
        dependency over the ``create_model``, reading the envelope's ``name`` and
        ``alert_on_fail`` from the parsed form and stamping the app's
        ``alert_detail_builder``. The body parameter is encoded as JSON (``Body()``)
        by default, or form-urlencoded (``Form()``) when ``create_form_encoded`` is
        set.

        :return: The create-payload dependency declaring the request body.
        """
        if self.payload_builder is not None:
            return self.payload_builder

        spec_builder = self.task_spec_builder
        owner = self.owner
        alert_detail_builder = self.alert_detail_builder
        body_marker = Form() if self.create_form_encoded else Body()
        form_param = Annotated[self.create_model, body_marker]

        async def _create_payload(
            form: form_param, inventory_api: InventoryAPI
        ) -> TaskWrite:
            resolved = await resolve_refs(form, inventory_api)
            spec = spec_builder(form, resolved)
            write = assemble_envelope(
                spec,
                resolved,
                name=form.task_name,
                owner=owner,
                alert_on_fail=getattr(form, "alert_on_fail", False),
                alert_detail_builder=alert_detail_builder,
            )
            stamp_form_input(write, form)
            return write

        return _create_payload
