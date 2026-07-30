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

"""Define constant for signing artifact-download URLs.

Houses the itsdangerous salt shared by the generic ``app.sep.routes.artifacts``
route and the framework signer in ``app.sep.apps.framework.script_helpers``, so
both sign and verify download tokens under the same namespace.
"""

__all__ = ["ARTIFACT_DOWNLOAD_SALT"]

ARTIFACT_DOWNLOAD_SALT = "artifact-download"
