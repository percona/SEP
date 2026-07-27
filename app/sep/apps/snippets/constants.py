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

"""Constants for the Snippets plugin."""

ARTIFACT_TYPE_SNIPPET = "snippet"

# Built-in snippet checksum manifest (sha256sum two-space format under SNIPPETS_DIR).
BUILTIN_CHECKSUM_MANIFEST = "builtin-snippets.sha256"

# Audit trail for automatic approvals of manifest-verified built-in snippets.
BUILTIN_APPROVAL_USER_ID = "system"
BUILTIN_APPROVAL_REASON = "Auto-approved: matches built-in checksum manifest"
