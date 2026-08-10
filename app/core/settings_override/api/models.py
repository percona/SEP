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

"""Pydantic request/response models for the settings REST API."""

__all__ = [
    "SettingClassAppMetadata",
    "SettingClassGroup",
    "SettingOption",
    "SettingResponse",
    "SettingsListResponse",
    "SettingsPatch",
]

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel

from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import ReloadClassification


class SettingOption(BaseModel):
    """Represent one selectable member for an enum-typed setting.

    :param label: The enum member name shown in the UI (e.g. ``WARNING``).
    :param value: The JSON-dumped member value the client must PATCH
        (e.g. ``30`` for an ``IntEnum``).
    """

    label: str
    value: JsonValue


class SettingResponse(BaseModel):
    """Represent a single setting's metadata and current value.

    :param setting_class: The settings class the field belongs to.
    :param key: The field name on the settings class.
    :param key_path: Carry the canonical key segments for ``key`` such that
        ``"__".join(key_path) == key``.
    :param value: The current value visible through the proxy, dumped to a
        JSON-safe shape via the field's annotation. ``SecretStr`` fields are
        redacted to ``"**********"``.
    :param default_value: The field's declared default value, dumped via the
        same JSON serialiser. ``None`` when no default exists.
    :param type: A human-readable representation of the field's declared
        annotation (for operator visibility; validation uses the actual
        ``FieldInfo``).
    :param reload: The reload classification (HOT or NOT_OVERRIDABLE).
    :param description: The field's free-text description, or ``None``.
    :param is_secret: Whether the field's annotation contains a Pydantic secret
        (``SecretStr`` / ``SecretBytes``) at any depth.
    :param is_complex: Whether the field's annotation is or contains a Pydantic
        ``BaseModel`` subclass (true for nested submodels).
    :param has_override: Whether a row exists in the ``settingoverride`` table
        for this ``(setting_class, key)`` pair, regardless of ``is_active``.
    :param is_advanced: Whether the setting is flagged ``advanced`` so the UI can
        present it separately from everyday settings. Display-only:
        it does not affect PATCH/DELETE eligibility.
    :param is_applicable: Whether the setting applies under current runtime state
        (e.g. the active auth provider). ``False`` lets the UI present the field
        as inert. Display-only, like ``is_advanced``: it does not block
        PATCH/DELETE server-side; the runtime gate is the real enforcement.
    :param options: Selectable enum members for dropdown UIs, or ``None`` /
        empty when the field is not an ``Enum`` annotation. Populated by
        iterating ``list(enum_cls)`` so aliases are skipped.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    setting_class: SettingClassEnum
    key: str
    key_path: list[str] = Field(default_factory=list)
    value: Any
    default_value: Any
    type: str
    reload: ReloadClassification
    description: str | None
    is_secret: bool
    is_complex: bool
    has_override: bool
    is_advanced: bool = False
    is_applicable: bool = True
    options: list[SettingOption] | None = None


class SettingsPatch(RootModel[dict[str, JsonValue]]):
    """Batch PATCH payload: a flat ``{field_name: new_value, ...}`` mapping.

    An empty body is rejected as 422 because a no-op PATCH is a client bug, not
    a valid request. The server coerces each value to the field's declared
    type via :func:`coerce_field_value`; validation is all-or-nothing -- if any
    key fails, nothing is written.
    """

    root: dict[str, JsonValue] = Field(min_length=1)


class SettingClassAppMetadata(BaseModel):
    """App-ownership metadata attached to a :class:`SettingClassGroup`.

    :param is_app_owned: Always ``True`` for app-owned groups.
    :type is_app_owned: bool
    :param app_id: The owning app's registry key.
    :type app_id: str
    :param app_display_name: The owning app's human-facing label.
    :type app_display_name: str
    :param app_enabled: Whether the owning app is currently enabled.
    :type app_enabled: bool
    """

    is_app_owned: bool = True
    app_id: str
    app_display_name: str
    app_enabled: bool


class SettingClassGroup(BaseModel):
    """One settings-class group in the LIST response.

    :param setting_class: The settings class this group represents.
    :type setting_class: SettingClassEnum
    :param settings: The fields declared on the settings class, with their
        current values and metadata.
    :type settings: list[SettingResponse]
    :param is_app_owned: Whether this group belongs to a SEP app under
        ``app/sep/apps/`` rather than core SEP wiring.
    :type is_app_owned: bool
    :param app_id: The owning app's registry key when ``is_app_owned`` is
        ``True``; ``None`` for core groups.
    :type app_id: str | None
    :param app_display_name: The owning app's human-facing label when
        ``is_app_owned`` is ``True``; ``None`` for core groups.
    :type app_display_name: str | None
    :param app_enabled: Whether the owning app is currently enabled when
        ``is_app_owned`` is ``True``; ``None`` for core groups. Disabled
        apps remain listed so the frontend can hide them without a second
        lookup.
    :type app_enabled: bool | None
    """

    setting_class: SettingClassEnum
    settings: list[SettingResponse]
    is_app_owned: bool = False
    app_id: str | None = None
    app_display_name: str | None = None
    app_enabled: bool | None = None


class SettingsListResponse(BaseModel):
    """The LIST endpoint response, grouping settings by class.

    :param groups: One :class:`SettingClassGroup` per settings class the
        router was configured with.
    :type groups: list[SettingClassGroup]
    """

    groups: list[SettingClassGroup]
