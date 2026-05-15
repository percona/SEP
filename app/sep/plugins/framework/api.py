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

"""Define shared discovery endpoint helpers for plugin routers.

The helpers in this module — :func:`schema_endpoint` and
:func:`capabilities_endpoint` — register the two well-known plugin
discovery routes (``GET /schema`` and ``GET /capabilities``) with the
same auth posture, response-model wiring, and duplicate-registration
guard so plugins opt in with a single call and never re-implement the
wiring.
"""

import functools
import inspect
import typing
from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter
from pydantic import BaseModel

from app.sep.deps import IsApiAuthenticated
from app.sep.plugins.framework.schema import PluginSchema

__all__ = ["capabilities_endpoint", "schema_endpoint"]


CapabilitiesT = TypeVar("CapabilitiesT", bound=BaseModel)


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
        response_model=PluginSchema,
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


def _resolve_capabilities_response_model(
    provider: Callable[..., BaseModel],
) -> type[BaseModel]:
    """Return the ``BaseModel`` subclass declared as ``provider``'s return type.

    Uses :func:`typing.get_type_hints` so deferred-evaluation annotations
    (``from __future__ import annotations``) resolve to the real class
    rather than a string. Falls back to the function's ``__annotations__``
    dict only if ``get_type_hints`` fails to resolve — e.g. for builtins
    where forward refs aren't relevant.

    :param provider: A callable annotated with its return type. The
        callable may declare arbitrary parameters (typically resolved by
        FastAPI's dependency injection via ``Depends(...)``).
    :type provider: Callable[..., BaseModel]
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
            "capabilities_endpoint: capabilities_provider must declare a "
            "return type annotation that is a pydantic.BaseModel subclass "
            "(e.g. `def provider() -> MyCapabilities: ...`)"
        )
    if not inspect.isclass(annotation) or not issubclass(annotation, BaseModel):
        raise TypeError(
            "capabilities_endpoint: capabilities_provider's return type "
            f"annotation must be a pydantic.BaseModel subclass; got "
            f"{annotation!r}"
        )
    return annotation


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
      Lambdas are rejected at registration time because their annotations
      are unavailable in the usual way.
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
    response_model = _resolve_capabilities_response_model(capabilities_provider)

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
