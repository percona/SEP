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

"""Build a settings REST API router parameterised by sub-app wiring."""

__all__ = ["build_settings_router"]

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, params, Request, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import BaseYamlSettings
from app.core.exceptions import (
    HTTPConflictException,
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.core.settings_override.api.models import (
    SettingClassGroup,
    SettingResponse,
    SettingsListResponse,
    SettingsPatch,
)
from app.core.settings_override.lifecycle import (
    fire_change_callbacks,
    publish_snapshot,
)
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import (
    _resolve_field_in_model,
    canonical_override_key,
    chain_has_explicit_not_overridable,
    coerce_field_value,
    dump_field_value,
    field_materializer,
    FieldMetadata,
    is_hot_reloadable,
    is_nested_overridable_parent,
    iter_class_fields,
    materialize_override_value,
    override_keys_for_rows,
    ReloadClassification,
    resolve_nested_field,
    resolve_nested_field_metadata,
    resolve_nested_value,
)

ClassEntry = tuple[SettingClassEnum, type[BaseYamlSettings], OverridableSettingsProxy]


def _settings_response_from_field(
    *,
    setting_class: SettingClassEnum,
    settings_cls: type[BaseYamlSettings],
    proxy: OverridableSettingsProxy,
    field_meta: FieldMetadata,
    has_override: bool,
) -> SettingResponse:
    """Build a :class:`SettingResponse` for one field on a settings class.

    :param setting_class: The settings class identifier (enum member).
    :type setting_class: SettingClassEnum
    :param settings_cls: The Pydantic settings class declaring the field.
    :type settings_cls: type[BaseYamlSettings]
    :param proxy: The proxy whose attribute access yields the field's current
        value (snapshot if present, else the wrapped Pydantic instance).
    :type proxy: OverridableSettingsProxy
    :param field_meta: The introspected metadata for the field.
    :type field_meta: FieldMetadata
    :param has_override: Whether a ``settingoverride`` row exists for this
        ``(class, key)`` pair.
    :type has_override: bool
    :return: The structured response for the field.
    :rtype: SettingResponse
    """
    if "__" in field_meta.key:
        field_info, current_value = resolve_nested_value(
            settings_cls=settings_cls, proxy=proxy, key=field_meta.key
        )
    else:
        field_info = settings_cls.model_fields[field_meta.key]
        current_value = getattr(proxy, field_meta.key)
    return SettingResponse(
        setting_class=setting_class,
        key=field_meta.key,
        value=dump_field_value(field_info, current_value),
        default_value=dump_field_value(field_info, field_meta.default),
        type=_format_annotation(field_meta.annotation),
        reload=field_meta.reload,
        description=field_meta.description,
        is_secret=field_meta.is_secret,
        is_complex=field_meta.is_complex,
        has_override=has_override,
    )


def _format_annotation(annotation: Any) -> str:
    """Return a human-readable string for a Pydantic field annotation.

    Strips the ``typing.`` prefix common to generic aliases and falls back to
    :func:`repr` when the annotation has no ``__name__``.

    :param annotation: The annotation to render.
    :type annotation: Any
    :return: A human-readable name for the annotation.
    :rtype: str
    """
    if annotation is None:
        return "None"
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    return repr(annotation).removeprefix("typing.")


def _validate_patch_body(
    *,
    settings_cls: type[BaseYamlSettings],
    body: SettingsPatch,
) -> list[tuple[str, Any]]:
    """Validate every key/value in a PATCH body for one settings class.

    Performs Phase A of the PATCH handler: each key is checked for existence
    on ``settings_cls``, HOT classification, and type/constraint validation via
    :func:`materialize_override_value` (which routes materializer-backed fields
    -- ``PROVIDERS``, ``FOOTER_TEMPLATE``, ``NOMAD`` -- through their declared
    materializer so the API accepts the same payloads the snapshot loader does).
    Errors are collected per-key; if any are present the entire batch is
    rejected with HTTP 422. Materializer-backed fields persist the raw JSON (the
    materialized value is not JSON-storable); plain fields persist the coerced
    value.

    :param settings_cls: The Pydantic settings class to validate against.
    :type settings_cls: type[BaseYamlSettings]
    :param body: The PATCH payload as a :class:`SettingsPatch` root model.
    :type body: SettingsPatch
    :return: The list of ``(key, coerced_value)`` tuples ready to persist.
    :rtype: list[tuple[str, Any]]
    :raises HTTPUnprocessableEntityException: If any key fails validation;
        the exception's ``detail`` is a structured list of Pydantic-style
        error entries.
    """
    errors = []
    to_apply = []
    for key, raw_value in body.root.items():
        if "__" in key:
            _validate_nested_key(
                settings_cls=settings_cls,
                key=key,
                raw_value=raw_value,
                errors=errors,
                to_apply=to_apply,
            )
            continue
        field_info = settings_cls.model_fields.get(key)
        if field_info is None:
            errors.append(
                {
                    "loc": ["body", key],
                    "msg": "Field does not exist on this settings class.",
                    "type": "unknown_key",
                }
            )
            continue
        if not is_hot_reloadable(settings_cls, key):
            errors.append(
                {
                    "loc": ["body", key],
                    "msg": "Setting cannot be overridden from the API.",
                    "type": "not_overridable",
                }
            )
            continue
        materializer = field_materializer(settings_cls, key)
        try:
            materialized = materialize_override_value(
                settings_cls, key, field_info, raw_value
            )
        except ValidationError as exc:
            errors.extend(
                {
                    "loc": ["body", key, *entry.get("loc", ())],
                    "msg": entry.get("msg", ""),
                    "type": entry.get("type", "value_error"),
                }
                for entry in exc.errors()
            )
            continue
        except ValueError as exc:
            errors.append(
                {"loc": ["body", key], "msg": str(exc), "type": "value_error"}
            )
            continue
        # Materializer-backed fields (PROVIDERS, FOOTER_TEMPLATE, NOMAD) produce
        # values that are not JSON-storable (a provider set, a Template, a
        # NomadExecutor); persist the raw JSON so build_snapshot re-materializes
        # on load.
        to_apply.append((key, raw_value if materializer is not None else materialized))

    if errors:
        raise HTTPUnprocessableEntityException(detail=errors)
    return to_apply


def _validate_nested_key(
    *,
    settings_cls: type[BaseYamlSettings],
    key: str,
    raw_value: Any,
    errors: list[dict[str, Any]],
    to_apply: list[tuple[str, Any]],
) -> None:
    """Validate one ``__``-delimited nested key, appending to ``errors``/``to_apply``.

    Gates the key in four steps, each mapping to a distinct 422 ``type``:
    the parent must exist (``unknown_key``) and be nested-overridable
    (``not_overridable``); the leaf must resolve (``unknown_nested_field``)
    and no segment along the path may be explicitly not-overridable
    (``not_overridable``); finally the value is coerced to the leaf type
    (structured Pydantic error on failure).

    :param settings_cls: The Pydantic settings class to validate against.
    :type settings_cls: type[BaseYamlSettings]
    :param key: The ``__``-delimited override key.
    :type key: str
    :param raw_value: The raw value to coerce to the leaf type.
    :type raw_value: Any
    :param errors: The running list of structured error entries, mutated in place.
    :type errors: list[dict[str, Any]]
    :param to_apply: The running list of ``(key, coerced_value)`` tuples,
        mutated in place.
    :type to_apply: list[tuple[str, Any]]
    """
    top_resolved = _resolve_field_in_model(settings_cls, key.split("__", 1)[0])
    if top_resolved is None:
        errors.append(
            {
                "loc": ["body", key],
                "msg": "Parent field does not exist on this settings class.",
                "type": "unknown_key",
            }
        )
        return
    canonical_top, _ = top_resolved
    if not is_nested_overridable_parent(settings_cls, canonical_top):
        errors.append(
            {
                "loc": ["body", key],
                "msg": "Setting cannot be overridden from the API.",
                "type": "not_overridable",
            }
        )
        return
    resolved = resolve_nested_field(settings_cls, key)
    if resolved is None:
        errors.append(
            {
                "loc": ["body", key],
                "msg": "Nested field does not exist on this settings class.",
                "type": "unknown_nested_field",
            }
        )
        return
    chain, leaf_info = resolved
    if chain_has_explicit_not_overridable(settings_cls, key):
        errors.append(
            {
                "loc": ["body", key],
                "msg": "Setting cannot be overridden from the API.",
                "type": "not_overridable",
            }
        )
        return
    try:
        validated = coerce_field_value(leaf_info, raw_value)
    except ValidationError as exc:
        errors.extend(
            {
                "loc": ["body", key, *entry.get("loc", ())],
                "msg": entry.get("msg", ""),
                "type": entry.get("type", "value_error"),
            }
            for entry in exc.errors()
        )
        return
    # Persist the canonical path so case-insensitive spellings collapse to one row.
    to_apply.append(("__".join(chain), validated))


async def _fire_inline_rebind_callbacks(
    request: Request,
    setting_class: SettingClassEnum,
    proxy: OverridableSettingsProxy,
    previous: Mapping[str, object],
) -> None:
    """Fire rebind callbacks for keys this handler's inline publish just changed.

    The background refresher fires rebind callbacks only on a snapshot diff it
    computes itself (the snapshot before its ``publish_snapshot`` vs the one
    after). The PATCH/DELETE handlers publish the new snapshot *inline*, so by
    the refresher's next cycle the proxy already holds the new value and the
    cycle's diff is empty -- a hot-reload target (the live ``NomadExecutor``, a
    RemoteAPI client endpoint) would never rebind until restart. Firing here, off
    the same ``previous``-vs-published diff, closes that gap for the process that
    handled the request; the refresher still covers *other* processes.

    The per-sub-app callback registry is published by the lifespan on
    ``request.app.state.override_callbacks``. Requests routed to a mounted sub-app
    resolve ``request.app`` to that sub-app, so the lifespan anchors the registry
    on the sub-app's state. It is absent for unit tests that skip the lifespan, in
    which case this is a no-op.

    :param request: The incoming request; its ``app.state`` carries the sub-app's
        rebind-callback registry.
    :type request: Request
    :param setting_class: The settings class whose snapshot was just republished.
    :type setting_class: SettingClassEnum
    :param proxy: The proxy holding the freshly-published snapshot.
    :type proxy: OverridableSettingsProxy
    :param previous: The snapshot in effect immediately before the inline publish.
    :type previous: Mapping[str, object]
    """
    callbacks = getattr(request.app.state, "override_callbacks", None)
    if not callbacks:
        return
    await fire_change_callbacks(
        callbacks, setting_class, previous, proxy.get_snapshot()
    )


def build_settings_router(
    *,
    classes: list[ClassEntry],
    session_dep: Any,
    admin_dep: params.Depends,
    mutation_deps: list[params.Depends] | None = None,
) -> APIRouter:
    """Build an :class:`APIRouter` exposing the settings CRUD endpoints.

    The factory generates LIST / DETAIL / PATCH / DELETE routes parameterised
    by the settings classes the sub-app wants to expose, its session
    dependency, and its admin-auth dependency. ``admin_dep`` is applied at
    the router level so every endpoint inherits the admin gate. State-changing
    endpoints (PATCH / DELETE) additionally take ``mutation_deps``, which the
    SEP wiring uses to require Bearer authentication on mutations: a
    cookie-authenticated admin can otherwise be CSRF'd into mutating settings
    because :func:`app.sep.deps.validate_csrf` only inspects form bodies, and
    JSON mutations carry no form body.

    :param classes: One ``(SettingClassEnum, settings_cls, proxy)`` triple per
        settings class to expose on this router.
    :type classes: list[ClassEntry]
    :param session_dep: An ``Annotated[AsyncSession, Depends(...)]`` type alias
        for the sub-app's session dependency (e.g. ``app.sep.deps.SessionDep``
        or ``app.tasks.deps.SessionDep``). Used as the parameter annotation on
        each generated handler so FastAPI resolves the session per-request.
    :type session_dep: Any
    :param admin_dep: A FastAPI ``Depends(...)`` callable that gates access to
        admin users only (e.g. ``app.sep.deps.IsApiAdmin`` or
        ``app.api.deps.IsAdminDep``). Applied at the router level so every
        endpoint inherits the admin gate.
    :type admin_dep: params.Depends
    :param mutation_deps: Optional list of FastAPI ``Depends(...)`` callables
        applied only to the state-changing endpoints (PATCH / DELETE). The
        SEP wiring passes ``[RequireBearerForUnsafeMethods]`` so cookie sessions cannot
        mutate settings; the Tasks wiring leaves this empty because its
        admin dependency is bearer-only via ``OAuth2PasswordBearer``.
    :type mutation_deps: list[params.Depends] | None
    :return: A configured :class:`APIRouter` ready to mount under a sub-app's
        ``/settings`` prefix.
    :rtype: APIRouter
    """
    router = APIRouter(dependencies=[admin_dep])
    class_lookup = {member: (cls, proxy) for member, cls, proxy in classes}

    def _resolve(
        setting_class: SettingClassEnum,
    ) -> tuple[type[BaseYamlSettings], OverridableSettingsProxy]:
        """Return the settings class and proxy for ``setting_class`` or 404.

        :param setting_class: The class identifier requested by the client.
        :type setting_class: SettingClassEnum
        :return: The settings class and its proxy.
        :rtype: tuple[type[BaseYamlSettings], OverridableSettingsProxy]
        :raises HTTPNotFoundException: If ``setting_class`` is not configured
            on this router.
        """
        entry = class_lookup.get(setting_class)
        if entry is None:
            raise HTTPNotFoundException(
                f"Settings class {setting_class.value!r} is not exposed by"
                " this sub-app.",
            )
        return entry

    @router.get("/")
    async def list_settings(session: session_dep) -> SettingsListResponse:  # type: ignore[valid-type]
        """List every exposed settings class with current values and metadata.

        :param session: The sub-app's database session.
        :type session: AsyncSession
        :return: Grouped responses, one group per configured settings class.
        :rtype: SettingsListResponse
        """
        groups = []
        for setting_class, settings_cls, proxy in classes:
            rows = await SettingsOverrideManager.list(
                session, setting_class=setting_class, is_active=True
            )
            override_keys = override_keys_for_rows(settings_cls, rows)
            settings_list = [
                _settings_response_from_field(
                    setting_class=setting_class,
                    settings_cls=settings_cls,
                    proxy=proxy,
                    field_meta=field_meta,
                    has_override=field_meta.key in override_keys,
                )
                for field_meta in iter_class_fields(settings_cls)
            ]
            groups.append(
                SettingClassGroup(setting_class=setting_class, settings=settings_list)
            )
        return SettingsListResponse(groups=groups)

    @router.get("/{setting_class}/{key}")
    async def get_setting(
        setting_class: SettingClassEnum,
        key: str,
        session: session_dep,  # type: ignore[valid-type]
    ) -> SettingResponse:
        """Return one field's metadata and current value.

        :param setting_class: The settings class the field belongs to.
        :type setting_class: SettingClassEnum
        :param key: The field name on the settings class.
        :type key: str
        :param session: The sub-app's database session.
        :type session: AsyncSession
        :return: The structured response for the field.
        :rtype: SettingResponse
        :raises HTTPNotFoundException: If the class isn't exposed or the key
            doesn't exist on the class.
        """
        settings_cls, proxy = _resolve(setting_class)
        key = canonical_override_key(settings_cls, key)
        field_meta = _field_meta_or_404(settings_cls, key)
        rows = await SettingsOverrideManager.list(
            session, setting_class=setting_class, is_active=True
        )
        override_keys = override_keys_for_rows(settings_cls, rows)
        return _settings_response_from_field(
            setting_class=setting_class,
            settings_cls=settings_cls,
            proxy=proxy,
            field_meta=field_meta,
            has_override=key in override_keys,
        )

    @router.patch("/{setting_class}", dependencies=mutation_deps or [])
    async def patch_settings(
        request: Request,
        setting_class: SettingClassEnum,
        body: SettingsPatch,
        session: session_dep,  # type: ignore[valid-type]
    ) -> list[SettingResponse]:
        """Apply a batch of overrides for one settings class atomically.

        Phase A validates every key in ``body`` (existence on the class, HOT
        classification, type/constraint coercion) and collects per-key errors.
        If any key fails, the whole batch is rejected with a structured 422
        and nothing is written. Phase B persists every valid entry in a single
        transaction, refreshes the proxy snapshot once, then fires the rebind
        callbacks for any changed keys so a HOT target rebinds without waiting
        for the next background refresh cycle.

        :param request: The incoming request; its ``app.state`` carries the
            sub-app's rebind-callback registry.
        :type request: Request
        :param setting_class: The settings class the override targets.
        :type setting_class: SettingClassEnum
        :param body: The batch of ``{key: value, ...}`` overrides.
        :type body: SettingsPatch
        :param session: The sub-app's database session.
        :type session: AsyncSession
        :return: One :class:`SettingResponse` per applied key, in input order.
        :rtype: list[SettingResponse]
        :raises HTTPNotFoundException: If the class isn't exposed.
        :raises HTTPUnprocessableEntityException: If any key fails validation;
            no rows are written.
        """
        settings_cls, proxy = _resolve(setting_class)
        to_apply = _validate_patch_body(settings_cls=settings_cls, body=body)
        await _persist_overrides(
            session=session,
            setting_class=setting_class,
            to_apply=to_apply,
        )
        previous = proxy.get_snapshot()
        await publish_snapshot(proxy, session, settings_cls)
        await _fire_inline_rebind_callbacks(request, setting_class, proxy, previous)
        field_meta_by_key = _applied_field_meta(settings_cls, to_apply)
        return [
            _settings_response_from_field(
                setting_class=setting_class,
                settings_cls=settings_cls,
                proxy=proxy,
                field_meta=field_meta_by_key[key],
                has_override=True,
            )
            for key, _ in to_apply
        ]

    @router.delete(
        "/{setting_class}/{key}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=mutation_deps or [],
    )
    async def delete_setting(
        request: Request,
        setting_class: SettingClassEnum,
        key: str,
        session: session_dep,  # type: ignore[valid-type]
    ) -> None:
        """Revert one override row to the field's declared default.

        Idempotent: deleting a (class, key) pair that has no override row
        succeeds with 204. Attempting to delete a NOT_OVERRIDABLE field
        responds 409 -- the field cannot have an override row in the first
        place, so the operator's intent is unsatisfiable.

        After republishing the snapshot, fires the rebind callbacks for the
        reverted key so a HOT target rebinds to its restored value without
        waiting for the next background refresh cycle.

        :param request: The incoming request; its ``app.state`` carries the
            sub-app's rebind-callback registry.
        :type request: Request
        :param setting_class: The settings class the field belongs to.
        :type setting_class: SettingClassEnum
        :param key: The field name on the settings class.
        :type key: str
        :param session: The sub-app's database session.
        :type session: AsyncSession
        :raises HTTPNotFoundException: If the class isn't exposed or the key
            doesn't exist on the class.
        :raises HTTPConflictException: If the field is NOT_OVERRIDABLE.
        :raises HTTPUnprocessableEntityException: If ``key`` names a
            ``NESTED_ONLY`` parent (the whole parent cannot be overridden;
            target an individual ``parent__leaf`` instead).
        """
        settings_cls, proxy = _resolve(setting_class)
        key = canonical_override_key(settings_cls, key)
        field_meta = _field_meta_or_404(settings_cls, key)
        _assert_key_deletable(settings_cls, field_meta)
        await SettingsOverrideManager.delete_where(
            session, setting_class=setting_class, key=key
        )
        previous = proxy.get_snapshot()
        await publish_snapshot(proxy, session, settings_cls)
        await _fire_inline_rebind_callbacks(request, setting_class, proxy, previous)

    return router


def _field_meta_or_404(settings_cls: type[BaseYamlSettings], key: str) -> FieldMetadata:
    """Return the :class:`FieldMetadata` for ``key`` on ``settings_cls`` or raise 404.

    Accepts both top-level keys (matched against
    :func:`iter_class_fields`) and ``__``-delimited nested keys (resolved via
    :func:`resolve_nested_field_metadata` into a synthesised leaf metadata
    whose ``key`` is the full nested string).

    :param settings_cls: The Pydantic settings class to look up the field on.
    :type settings_cls: type[BaseYamlSettings]
    :param key: The field name (or ``__``-delimited nested key) to find.
    :type key: str
    :return: The metadata for the field.
    :rtype: FieldMetadata
    :raises HTTPNotFoundException: If ``key`` is not a declared field of
        ``settings_cls`` (nor a resolvable nested key).
    """
    if "__" in key:
        nested_meta = resolve_nested_field_metadata(settings_cls, key)
        if nested_meta is not None:
            return nested_meta
        raise HTTPNotFoundException(
            f"Setting {settings_cls.__name__}.{key} does not exist.",
        )
    for field_meta in iter_class_fields(settings_cls):
        if field_meta.key == key:
            return field_meta
    raise HTTPNotFoundException(
        f"Setting {settings_cls.__name__}.{key} does not exist.",
    )


def _applied_field_meta(
    settings_cls: type[BaseYamlSettings],
    to_apply: list[tuple[str, Any]],
) -> dict[str, FieldMetadata]:
    """Return a ``key -> FieldMetadata`` map covering every applied override key.

    Seeds the map with all top-level fields and adds a synthesised entry for
    each ``__``-delimited key in ``to_apply`` (which ``iter_class_fields`` does
    not enumerate). Every key was already accepted by
    :func:`_validate_patch_body`, so the nested lookups cannot 404.

    :param settings_cls: The Pydantic settings class the keys belong to.
    :type settings_cls: type[BaseYamlSettings]
    :param to_apply: The list of ``(key, value)`` tuples being applied.
    :type to_apply: list[tuple[str, Any]]
    :return: A mapping from override key to its field metadata.
    :rtype: dict[str, FieldMetadata]
    """
    field_meta_by_key = {f.key: f for f in iter_class_fields(settings_cls)}
    for key, _ in to_apply:
        if "__" in key and key not in field_meta_by_key:
            field_meta_by_key[key] = _field_meta_or_404(settings_cls, key)
    return field_meta_by_key


def _assert_key_deletable(
    settings_cls: type[BaseYamlSettings],
    field_meta: FieldMetadata,
) -> None:
    """Raise the appropriate HTTP error when ``field_meta`` cannot be deleted.

    A ``__``-delimited key whose top-level parent is not nested-overridable is
    rejected with 422 (``not_overridable``), mirroring the PATCH guard in
    :func:`_validate_nested_key` so DELETE and PATCH agree on which nested keys
    are addressable. A ``NESTED_ONLY`` parent rejects whole-parent deletion with
    422 (target a nested child instead); a ``NOT_OVERRIDABLE`` field rejects
    deletion with 409 (no override row can exist). Overridable keys pass through
    silently.

    :param settings_cls: The Pydantic settings class the field belongs to.
    :type settings_cls: type[BaseYamlSettings]
    :param field_meta: The resolved metadata for the key being deleted.
    :type field_meta: FieldMetadata
    :raises HTTPUnprocessableEntityException: If the key names a ``NESTED_ONLY``
        parent, or a nested key under a non-nested-overridable parent.
    :raises HTTPConflictException: If the key names a ``NOT_OVERRIDABLE`` field.
    """
    if "__" in field_meta.key:
        top = field_meta.key.split("__", 1)[0]
        if not is_nested_overridable_parent(settings_cls, top):
            raise HTTPUnprocessableEntityException(
                detail=[
                    {
                        "loc": ["path", "key"],
                        "msg": "Setting cannot be overridden from the API.",
                        "type": "not_overridable",
                    }
                ]
            )
    if field_meta.reload == ReloadClassification.NESTED_ONLY:
        raise HTTPUnprocessableEntityException(
            detail=[
                {
                    "loc": ["path", "key"],
                    "msg": "Whole-parent override is not allowed; target a"
                    " nested field instead.",
                    "type": "not_overridable",
                }
            ]
        )
    if field_meta.reload == ReloadClassification.NOT_OVERRIDABLE:
        raise HTTPConflictException(
            f"Setting {settings_cls.__name__}.{field_meta.key} cannot be"
            " overridden; no row to delete.",
        )


async def _persist_overrides(
    *,
    session: AsyncSession,
    setting_class: SettingClassEnum,
    to_apply: list[tuple[str, Any]],
) -> None:
    """Insert or update each ``(setting_class, key)`` row in a single transaction.

    Existing rows have ``value`` and ``is_active`` updated; missing rows are
    inserted fresh. The transaction is committed once at the end so a failure
    on any single row rolls back the entire batch.

    Concurrent PATCHes against the same key would otherwise race: both
    requests can observe ``existing is None`` between their ``first()`` and
    the unique-index commit, and the second commit would raise
    :class:`sqlalchemy.exc.IntegrityError`. The handler catches that case,
    rolls back the failed transaction, and replays the batch against the
    rows the winning writer left in place so the second PATCH still applies
    its values cleanly.

    :param session: The sub-app's database session.
    :type session: AsyncSession
    :param setting_class: The settings class the rows belong to.
    :type setting_class: SettingClassEnum
    :param to_apply: The list of ``(key, coerced_value)`` tuples to persist.
    :type to_apply: list[tuple[str, Any]]
    """
    try:
        await _stage_and_commit_overrides(
            session=session, setting_class=setting_class, to_apply=to_apply
        )
    except IntegrityError:
        await session.rollback()
        await _stage_and_commit_overrides(
            session=session, setting_class=setting_class, to_apply=to_apply
        )


async def _stage_and_commit_overrides(
    *,
    session: AsyncSession,
    setting_class: SettingClassEnum,
    to_apply: list[tuple[str, Any]],
) -> None:
    """Stage every (setting_class, key) row and commit the batch.

    :param session: The sub-app's database session.
    :type session: AsyncSession
    :param setting_class: The settings class the rows belong to.
    :type setting_class: SettingClassEnum
    :param to_apply: The list of ``(key, coerced_value)`` tuples to persist.
    :type to_apply: list[tuple[str, Any]]
    """
    for key, value in to_apply:
        existing = await SettingsOverrideManager.first(
            session, setting_class=setting_class, key=key
        )
        if existing is None:
            session.add(
                SettingOverride(
                    setting_class=setting_class,
                    key=key,
                    value=value,
                    is_active=True,
                )
            )
        else:
            existing.value = value
            existing.is_active = True
            session.add(existing)
    await session.commit()
