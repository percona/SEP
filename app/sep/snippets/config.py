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

"""Define settings for support snippets in the SEP app."""

import re
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, field_validator, PositiveInt
from sqlalchemy_celery_beat.models import Period

from app.core.celery.models import IntervalSchedule
from app.core.config import BaseYamlSettings
from app.core.utils import validate_module_is_importable
from app.core.utils.fields import (
    FilenameExtension,
    MimeType,
    RelativeDirectoryPath,
    RequiredStr,
)


class SnippetsMetaOptions(BaseModel):
    """Metadata options for snippets.

    :param LINE_PATTERN: Regular expression to match metadata lines in the snippet file.
        Use a group named "line" to capture only a part of the line. Defaults to
        `r"^# (?P<line>.+)$"`.
    :type LINE_PATTERN: re.Pattern[str]
    :param DELIMITER: The delimiter indicating the start/end of metadata in a snippet.
        Defaults to `"---"`.
    :type DELIMITER: RequiredStr
    :param STOP_SEARCH_PATTERN: Regular expression to stop searching for metadata lines.
        Defaults to `r"r"^[^#].+$"`.
    :type STOP_SEARCH_PATTERN: re.Pattern[str]
    :param DEFAULT_STRICT: Whether to block extra arguments by default. Defaults to
        `False`, meaning extra arguments are allowed.
    :type DEFAULT_STRICT: bool
    """

    LINE_PATTERN: re.Pattern[str] = re.compile(r"^# (?P<line>.+)$")
    DELIMITER: RequiredStr = "---"
    STOP_SEARCH_PATTERN: re.Pattern[str] = re.compile(r"^[^#].+$")
    DEFAULT_STRICT: bool = False


class SnippetsSettings(BaseYamlSettings):
    """Define configuration options for support snippets.

    :cvar SETTINGS_PREFIXES: The prefixes for snippets related settings in the
        configuration file. Set to `["SEP", "SNIPPETS"]`.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param SNIPPETS_DIR: The directory containing support snippets. Defaults to
        `Path("snippets")`.
    :type SNIPPETS_DIR: RelativeDirectoryPath
    :param META: Metadata options for snippets. See `SnippetsMetaOptions`.
    :type META: SnippetsMetaOptions
    :param FILTER_EXTENSIONS: A list of file extensions to filter files by in
        `SNIPPETS_DIR`. If `None`, no filtering is applied. Defaults to `None`.
    :type FILTER_EXTENSIONS: list[FilenameExtension] | None
    :param FILTER_MIME_TYPES: A list of MIME types to filter files by in
        `SNIPPETS_DIR`. If `None`, no filtering is applied. Defaults to `None`.
    :type FILTER_MIME_TYPES: list[MimeType] | None
    :param USE_MAGIC: Whether to use the `python-magic` package to determine file types.
        Defaults to `False`. If `True`, the `python-magic` package must be installed.
    :type USE_MAGIC: bool
    :param SYNC_INTERVAL: The interval schedule for synchronizing snippets. Defaults to
        every 1 hour.
    :type SYNC_INTERVAL: IntervalSchedule
    :param PREVIEW_MAX_CHARS: The maximum number of characters to include in the snippet
        preview. Defaults to 10,000.
    :type PREVIEW_MAX_CHARS: PositiveInt
    :param PREVIEW_MAX_LINES: The maximum number of lines to include in the snippet
        preview. Defaults to 500.
    :type PREVIEW_MAX_LINES: PositiveInt
    :param ENABLE_MANUAL_SYNC: Whether to enable manual synchronization of snippets.
        Defaults to `False`.
    :type ENABLE_MANUAL_SYNC: bool
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP", "SNIPPETS"]
    SNIPPETS_DIR: RelativeDirectoryPath = Path("snippets")
    META: SnippetsMetaOptions = SnippetsMetaOptions()
    FILTER_EXTENSIONS: list[FilenameExtension] | None = None
    FILTER_MIME_TYPES: list[MimeType] | None = None
    USE_MAGIC: bool = False
    SYNC_INTERVAL: IntervalSchedule = IntervalSchedule(every=1, period=Period.HOURS)
    PREVIEW_MAX_CHARS: PositiveInt = 10000
    PREVIEW_MAX_LINES: PositiveInt = 500
    ENABLE_MANUAL_SYNC: bool = False

    @field_validator("USE_MAGIC")
    @classmethod
    def _validate_python_magic_is_installed(cls, v: bool) -> bool:  # noqa: FBT001
        if v:
            try:
                validate_module_is_importable("magic")
            except ImportError:
                raise ValueError(
                    "The 'python-magic' package is required for this feature."
                ) from None
        return v


snippets_settings = SnippetsSettings()
