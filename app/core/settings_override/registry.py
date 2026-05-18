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

"""Classification registry for DB-backed setting overrides."""

__all__ = ["ReloadClassification", "hot_field_names", "is_hot_reloadable"]

from enum import StrEnum

from pydantic import BaseModel

from app.core.utils.pydantic import CustomFieldMetadata


class ReloadClassification(StrEnum):
    """Declare the reload behavior of an overridable settings field.

    :cvar HOT: Field can be overridden via a DB row and the new value takes
        effect on the next snapshot refresh, without restarting the service.
    :vartype HOT: str
    :cvar NOT_OVERRIDABLE: Field is not overridable from the database; YAML
        and environment variables remain the only sources of truth.
    :vartype NOT_OVERRIDABLE: str
    """

    HOT = "hot"
    NOT_OVERRIDABLE = "not_overridable"


def is_hot_reloadable(settings_cls: type[BaseModel], field_name: str) -> bool:
    """Return whether the given field is marked HOT on the given settings class.

    :param settings_cls: The Pydantic settings class to inspect.
    :type settings_cls: type[BaseModel]
    :param field_name: The name of the field to check.
    :type field_name: str
    :return: ``True`` when ``field_name`` exists on ``settings_cls`` and is
        marked with ``{"reload": ReloadClassification.HOT}`` via
        :func:`app.core.utils.pydantic.field_with_metadata`.
    :rtype: bool
    """
    field = settings_cls.model_fields.get(field_name)
    if field is None:
        return False
    metadata = CustomFieldMetadata.field_to_dict(field)
    return metadata.get("reload") == ReloadClassification.HOT


def hot_field_names(settings_cls: type[BaseModel]) -> frozenset[str]:
    """Return the set of field names on ``settings_cls`` marked HOT.

    :param settings_cls: The Pydantic settings class to inspect.
    :type settings_cls: type[BaseModel]
    :return: A frozenset of field names declared HOT via
        :func:`app.core.utils.pydantic.field_with_metadata`.
    :rtype: frozenset[str]
    """
    return frozenset(
        name
        for name in settings_cls.model_fields
        if is_hot_reloadable(settings_cls, name)
    )
