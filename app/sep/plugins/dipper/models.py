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

"""Models for the Dipper plugin."""

from pathlib import Path
from typing import ClassVar

from app.sep.plugins.dipper.constants import DIPPER_PAYLOADS_DIR
from app.sep.snippets.models.snippet import BaseSnippet


class DipperScript(BaseSnippet):
    """Represent a Dipper payload script stored on the SEP server filesystem."""

    BASE_DIR: ClassVar[Path] = DIPPER_PAYLOADS_DIR
