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

"""Define utilities for the SEP app snippets."""

__all__ = ["generate_unique_identifiers", "guess_mime_type"]

import string
from collections.abc import Generator
from itertools import product
from pathlib import Path

from app.core.utils import ttl_cache
from app.sep.snippets.config import snippets_settings

_ONE_HOUR = 60 * 60


@ttl_cache(ttl=_ONE_HOUR, maxsize=16)
def guess_mime_type(file_path: Path) -> str:
    """Guess the MIME type of a file based on its path.

    Uses the `python-magic` library if `USE_MAGIC` is enabled in settings,
    otherwise falls back to using the file extension.

    :param file_path: The path to the file.
    :type file_path: Path
    :return: The MIME type of the file, defaulting to "text/plain" if unknown.
    :rtype: str
    """
    if snippets_settings.USE_MAGIC:
        import magic

        return magic.from_file(file_path, mime=True) or "text/plain"
    import mimetypes

    return mimetypes.types_map.get(file_path.suffix) or "text/plain"


def generate_unique_identifiers() -> Generator[str]:
    """Generate unique identifiers.

    Generate unique valid Python/Pydantic identifiers that start with a letter,
    can contain letters, digits, and underscores in the middle, and end with a digit.
    The length of the identifiers increases as needed to ensure uniqueness.

    :yield: A unique identifier.
    :rtype: Generator[str]
    """
    start_chars = string.ascii_letters
    mid_chars = string.ascii_letters + string.digits + "_"
    end_chars = string.digits
    length = 1
    while True:
        for first in start_chars:
            if length == 1:
                yield first
            else:
                for mids in product(mid_chars, repeat=length - 2):
                    for last in end_chars:
                        yield f"{first}{''.join(mids)}{last}"
        length += 1
