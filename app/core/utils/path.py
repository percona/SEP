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

"""Define path-related utilities."""

from os import PathLike
from pathlib import Path

from app import BASE_DIR


def resolve_relative_path(path: str | bytes | PathLike) -> Path:
    """Resolve relative paths with BASE_DIR.

    :param path: The relative path to resolve.
    :type path: str | bytes | PathLike
    :return: The resolved absolute path.
    :rtype: Path
    :raises ValueError: If the path cannot be resolved.
    """
    try:
        return BASE_DIR / path
    except TypeError as exc:
        raise ValueError(f"Unable to resolve path: {path}") from exc
