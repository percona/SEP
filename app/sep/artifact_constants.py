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

"""Constants for the artifact download module.

These constants live in their own module to avoid the import cycle that
would otherwise form when both ``app.sep.routes.artifacts`` and a plugin's
``deps.py`` need them: ``artifacts.py`` imports plugin-side constants
(for example, :data:`app.sep.apps.dipper.constants.DIPPER_PAYLOADS_DIR`),
while plugin ``deps.py`` modules import the artifact constants here.
"""

__all__ = [
    "ARTIFACT_DOWNLOAD_SALT",
    "ARTIFACT_TYPE_DIPPER",
    "ARTIFACT_TYPE_SNIPPET",
]

ARTIFACT_DOWNLOAD_SALT = "artifact-download"
ARTIFACT_TYPE_SNIPPET = "snippet"
ARTIFACT_TYPE_DIPPER = "dipper"
