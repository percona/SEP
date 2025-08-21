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

"""Define utilities for the SEP app snippets."""

from pathlib import Path

from app.sep.snippets.config import snippets_settings


def guess_mime_type(file_path: Path) -> str | None:
    """Guess the MIME type of a file based on its path.

    Uses the `python-magic` library if `USE_MAGIC` is enabled in settings,
    otherwise falls back to using the file extension.

    :param file_path: The path to the file.
    :type file_path: Path
    :return: The MIME type of the file, or None if it cannot be determined.
    :rtype: str | None
    """
    if snippets_settings.USE_MAGIC:
        import magic

        return magic.from_file(file_path, mime=True) or None
    import mimetypes

    return mimetypes.types_map.get(file_path.suffix)
