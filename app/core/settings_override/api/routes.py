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

from typing import Any

from fastapi import APIRouter, params, status
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
from app.core.settings_override.cache import build_snapshot
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import (
    coerce_field_value,
    dump_field_value,
    FieldMetadata,
    is_hot_reloadable,
    iter_class_fields,
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
    on ``settings_cls``, HOT classification, and Pydantic type/constraint
    validation via :func:`coerce_field_value`. Errors are collected per-key;
    if any are present the entire batch is rejected with HTTP 422.

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
        try:
            validated = coerce_field_value(field_info, raw_value)
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
        to_apply.append((key, validated))

    if errors:
        raise HTTPUnprocessableEntityException(detail=errors)
    return to_apply


def build_settings_router(
    *,
    classes: list[ClassEntry],
    session_dep: Any,
    admin_dep: params.Depends,
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
        SEP wiring passes ``[RequireBearerAuth]`` so cookie sessions cannot
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
                session, setting_class=setting_class
            )
            override_keys = {row.key for row in rows}
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
        field_meta = _field_meta_or_404(settings_cls, key)
        existing = await SettingsOverrideManager.first(
            session, setting_class=setting_class, key=key
        )
        return _settings_response_from_field(
            setting_class=setting_class,
            settings_cls=settings_cls,
            proxy=proxy,
            field_meta=field_meta,
            has_override=existing is not None,
        )

    @router.patch("/{setting_class}")
    async def patch_settings(
        setting_class: SettingClassEnum,
        body: SettingsPatch,
        session: session_dep,  # type: ignore[valid-type]
    ) -> list[SettingResponse]:
        """Apply a batch of overrides for one settings class atomically.

        Phase A validates every key in ``body`` (existence on the class, HOT
        classification, type/constraint coercion) and collects per-key errors.
        If any key fails, the whole batch is rejected with a structured 422
        and nothing is written. Phase B persists every valid entry in a single
        transaction, then refreshes the proxy snapshot once.

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
        proxy._set_snapshot(await build_snapshot(session, settings_cls))  # noqa: SLF001
        field_meta_by_key = {f.key: f for f in iter_class_fields(settings_cls)}
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

    @router.delete("/{setting_class}/{key}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_setting(
        setting_class: SettingClassEnum,
        key: str,
        session: session_dep,  # type: ignore[valid-type]
    ) -> None:
        """Revert one override row to the field's declared default.

        Idempotent: deleting a (class, key) pair that has no override row
        succeeds with 204. Attempting to delete a NOT_OVERRIDABLE field
        responds 409 -- the field cannot have an override row in the first
        place, so the operator's intent is unsatisfiable.

        :param setting_class: The settings class the field belongs to.
        :type setting_class: SettingClassEnum
        :param key: The field name on the settings class.
        :type key: str
        :param session: The sub-app's database session.
        :type session: AsyncSession
        :raises HTTPNotFoundException: If the class isn't exposed or the key
            doesn't exist on the class.
        :raises HTTPConflictException: If the field is NOT_OVERRIDABLE.
        """
        settings_cls, proxy = _resolve(setting_class)
        _field_meta_or_404(settings_cls, key)
        if not is_hot_reloadable(settings_cls, key):
            raise HTTPConflictException(
                f"Setting {settings_cls.__name__}.{key} cannot be overridden;"
                " no row to delete.",
            )
        await SettingsOverrideManager.delete_where(
            session, setting_class=setting_class, key=key
        )
        await session.commit()
        proxy._set_snapshot(await build_snapshot(session, settings_cls))  # noqa: SLF001

    return router


def _field_meta_or_404(settings_cls: type[BaseYamlSettings], key: str) -> FieldMetadata:
    """Return the :class:`FieldMetadata` for ``key`` on ``settings_cls`` or raise 404.

    :param settings_cls: The Pydantic settings class to look up the field on.
    :type settings_cls: type[BaseYamlSettings]
    :param key: The field name to find.
    :type key: str
    :return: The metadata for the field.
    :rtype: FieldMetadata
    :raises HTTPNotFoundException: If ``key`` is not a declared field of
        ``settings_cls``.
    """
    for field_meta in iter_class_fields(settings_cls):
        if field_meta.key == key:
            return field_meta
    raise HTTPNotFoundException(
        f"Setting {settings_cls.__name__}.{key} does not exist.",
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
