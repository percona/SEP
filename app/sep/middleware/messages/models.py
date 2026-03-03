# Copyright (C) 2025 Percona LLC
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

"""Define models for the messages middleware."""

__all__ = ["Message", "MessageLevel"]

import re
from enum import IntEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)

from app.core.utils.fields import EnumFieldMixin, NonEmptyStr


class MessageLevel(EnumFieldMixin, IntEnum):
    """Enumerate the possible message levels.

    :cvar INFO: Represents a standard information message.
    :vartype INFO: int
    :cvar SUCCESS: Represents a success message.
    :vartype SUCCESS: int
    :cvar WARNING: Represents a warning message.
    :vartype WARNING: int
    :cvar ERROR: Represents an error message.
    :vartype ERROR: int
    """

    INFO = 1
    SUCCESS = 3
    WARNING = 5
    ERROR = 7


class Message(BaseModel):
    """Represent a user-facing message to be displayed in the UI.

    :param level: The level of the message.
    :type level: MessageLevel
    :param text: The content of the message. Must not exceed 512 characters.
    :type text: str
    :param path_pattern: An optional URI path pattern associated with the message.
        If provided, the message will only be shown on requests matching this pattern.
    :type path_pattern: re.Pattern[str] | None
    :param sticky: A flag indicating whether the message should persist until dismissed.
    :type sticky: bool
    """

    model_config = ConfigDict(populate_by_name=True)
    level: MessageLevel = Field(alias="l")
    text: NonEmptyStr = Field(alias="t", max_length=512)
    path_pattern: re.Pattern[str] | None = Field(default=None, alias="p")
    sticky: bool = Field(default=False, exclude=True)

    def __hash__(self) -> int:
        """Return a hash of the message based on its level and text.

        This method allows Message objects to be used in sets or as dictionary keys.

        :return: A hash value for the message.
        :rtype: int
        """
        return hash((self.level, self.text, self.sticky))

    @model_validator(mode="before")
    @classmethod
    def set_sticky_from_level(cls, data: Any) -> Any:
        """Pre-process input data to set the 'sticky' flag based on the message level.

        This method allows validation for messages serialized with the `serialize_level`
        serializer, in which the `sticky` attribute is defined in the `level` by adding
        1 to the value.

        :param data: The raw data to be validated, typically a dictionary.
        :type data: Any
        :return: The processed data with a potentially updated 'sticky' attribute.
        :rtype: Any
        """
        if isinstance(data, dict) and "sticky" not in data:
            level = data.get("l")
            if isinstance(level, int) and not level % 2:
                data["l"] -= 1
                data["sticky"] = True
        return data

    @field_serializer("level")
    def serialize_level(self, level: MessageLevel) -> int:
        """Serialize the message level by incorporating the sticky flag.

        In order to minimize the messages cookie, the `sticky` attribute is defined
        in the `level` by adding 1 to the original `level` value.

        :param level: The original message level.
        :type level: MessageLevel
        :return: The serialized level as an integer, plus 1 if `sticky` is True.
        :rtype: int
        """
        return level + self.sticky
