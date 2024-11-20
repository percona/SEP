"""Define utilities for text and strings."""

import re
import unicodedata
from base64 import b64encode

__all__ = [
    "to_uppercase",
    "slugify",
    "b64encode_str",
]


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
