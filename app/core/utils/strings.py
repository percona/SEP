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

"""Define utilities for text and strings."""

__all__ = [
    "b64decode_str",
    "b64encode_str",
    "shorten_text",
    "slugify",
    "to_uppercase",
]

import re
import unicodedata
from base64 import b64decode, b64encode
from typing import Any

from pydantic import NonNegativeInt, PositiveInt, validate_call


@validate_call
def shorten_text(
    text: str,
    max_length: PositiveInt = 100,
    keep_last_chars: NonNegativeInt = 0,
    ellipsis: str = "...",
) -> str:
    """Shorten a string to a specified maximum length.

    If the string exceeds the maximum length, it is truncated and an ellipsis is added.

    :param text: The string to be shortened.
    :type text: str
    :param max_length: The maximum allowed length of the string, defaults to 100.
    :type max_length: PositiveInt
    :param keep_last_chars: The number of characters to keep at the end of the string,
        defaults to 0.
    :type keep_last_chars: NonNegativeInt
    :param ellipsis: The string to indicate truncation, defaults to "...".
    :type ellipsis: str
    :return: The shortened string.
    :rtype: str
    :raises ValueError: If the combined length of `ellipsis` and `keep_last_chars` is
        greater than or equal to `max_length`.
    :raises ValidationError: If `max_length` is not a positive integer or
        `keep_last_chars` is negative.
    :raises ValidationError: If `text` or `ellipsis` are not strings.
    """
    if (text_length := len(text)) <= max_length:
        return text
    if (ellipsis_length := len(ellipsis)) + keep_last_chars >= max_length:
        raise ValueError(
            "The combined length of ellipsis and keep_last_chars must be less than max_length"
            f" ({ellipsis_length} + {keep_last_chars} >= {max_length})"
        )
    return (
        text[: max_length - ellipsis_length - keep_last_chars]
        + ellipsis
        + text[text_length - keep_last_chars :]
    )


def to_uppercase(name: str) -> str:
    """Convert a string to uppercase.

    This function takes a string input and returns a new string with all
    characters converted to uppercase.

    :param name: The string to be converted to uppercase.
    :type name: str
    :return: The input string converted to uppercase.
    :rtype: str
    """
    return name.upper()


def slugify(text: str) -> str:
    """Convert a string into a slug suitable for URLs.

    Normalize the input text by removing non-ASCII characters, converting to
    lowercase, replacing non-alphanumeric characters with hyphens, and
    stripping leading/trailing hyphens.

    :param text: The string to convert into a slug.
    :type text: str
    :return: The slugified version of the input string.
    :rtype: str
    """
    slug = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("utf-8")
        .lower()
    )
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-")


def b64encode_str(value: str, encoding: str = "utf-8") -> str:
    """Encode a string to Base64.

    Encode the given string to Base64 format using the specified encoding.

    :param value: The string to be encoded.
    :type value: str
    :param encoding: The encoding to use for the string, defaults to "utf-8".
    :type encoding: str, optional
    :return: The Base64 encoded string.
    :rtype: str
    """
    return b64encode(value.encode(encoding)).decode(encoding)


def b64decode_str(value: str, encoding: str = "utf-8") -> str:
    """Decode a Base64 string.

    Decode the given string from Base64 format using the specified encoding.

    :param value: The b64-encoded string.
    :type value: str
    :param encoding: The encoding to use for the string, defaults to "utf-8".
    :type encoding: str, optional
    :return: The decoded string.
    :rtype: str
    """
    return b64decode(value).decode(encoding)


def lower_if_string(value: Any) -> Any:
    """Convert a value to lowercase if it is a string.

    This function checks if the input value is a string and converts it to
    lowercase. If the value is not a string, it returns the value unchanged.

    :param value: The value to be checked and potentially converted.
    :type value: Any
    :return: The input value converted to lowercase if it is a string, otherwise unchanged.
    :rtype: Any
    """
    return value.lower() if isinstance(value, str) else value
