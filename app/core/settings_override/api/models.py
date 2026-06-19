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
    "SettingClassGroup",
    "SettingResponse",
    "SettingsListResponse",
    "SettingsPatch",
]

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel

from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import ReloadClassification


class SettingResponse(BaseModel):
    """Represent a single setting's metadata and current value.

    :param setting_class: The settings class the field belongs to.
    :type setting_class: SettingClassEnum
    :param key: The field name on the settings class.
    :type key: str
    :param key_path: Carry the canonical key segments for ``key`` such that
        ``"__".join(key_path) == key``.
    :type key_path: list[str]
    :param value: The current value visible through the proxy, dumped to a
        JSON-safe shape via the field's annotation. ``SecretStr`` fields are
        redacted to ``"**********"``.
    :type value: Any
    :param default_value: The field's declared default value, dumped via the
        same JSON serialiser. ``None`` when no default exists.
    :type default_value: Any
    :param type: A human-readable representation of the field's declared
        annotation (for operator visibility; validation uses the actual
        ``FieldInfo``).
    :type type: str
    :param reload: The reload classification (HOT or NOT_OVERRIDABLE).
    :type reload: ReloadClassification
    :param description: The field's free-text description, or ``None``.
    :type description: str | None
    :param is_secret: Whether the field's annotation contains a Pydantic secret
        (``SecretStr`` / ``SecretBytes``) at any depth.
    :type is_secret: bool
    :param is_complex: Whether the field's annotation is or contains a Pydantic
        ``BaseModel`` subclass (true for nested submodels).
    :type is_complex: bool
    :param has_override: Whether a row exists in the ``settingoverride`` table
        for this ``(setting_class, key)`` pair, regardless of ``is_active``.
    :type has_override: bool
    :param is_advanced: Whether the setting is flagged ``advanced`` so the UI can
        present it separately from everyday settings. Defaults to ``False`` so
        the addition is purely additive and backward-compatible. Display-only:
        it does not affect PATCH/DELETE eligibility.
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


class SettingsPatch(RootModel[dict[str, JsonValue]]):
    """Batch PATCH payload: a flat ``{field_name: new_value, ...}`` mapping.

    An empty body is rejected as 422 because a no-op PATCH is a client bug, not
    a valid request. The server coerces each value to the field's declared
    type via :func:`coerce_field_value`; validation is all-or-nothing -- if any
    key fails, nothing is written.
    """

    root: dict[str, JsonValue] = Field(min_length=1)


class SettingClassGroup(BaseModel):
    """One settings-class group in the LIST response.

    :param setting_class: The settings class this group represents.
    :type setting_class: SettingClassEnum
    :param settings: The fields declared on the settings class, with their
        current values and metadata.
    :type settings: list[SettingResponse]
    """

    setting_class: SettingClassEnum
    settings: list[SettingResponse]


class SettingsListResponse(BaseModel):
    """The LIST endpoint response, grouping settings by class.

    :param groups: One :class:`SettingClassGroup` per settings class the
        router was configured with.
    :type groups: list[SettingClassGroup]
    """

    groups: list[SettingClassGroup]
