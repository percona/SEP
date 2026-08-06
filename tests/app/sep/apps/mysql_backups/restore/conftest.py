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

"""Define test fixtures for mysql_backups restore payload tests."""

import ast
import pathlib

RESTORE_PAYLOAD_PATH = (
    pathlib.Path(__file__).parents[6]
    / "app/sep/apps/mysql_backups/restore/xtrabackup_payload"
)


def restore_payload_tree() -> ast.Module:
    """Parse and return the restore payload's AST, fresh on every call.

    Centralizes the payload-path lookup so the per-file AST-extraction helpers
    in this directory's test modules do not each re-derive it independently.
    """
    return ast.parse(RESTORE_PAYLOAD_PATH.read_text())
