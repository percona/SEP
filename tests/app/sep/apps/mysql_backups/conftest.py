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

"""Define test fixtures for mysql_backups plugin tests."""

import ast
import pathlib

from tests.app.sep.conftest import (  # noqa: F401
    mock_inventory_api_dep,
    mock_task_api_dep,
    unauthenticated_client,
)

XTRABACKUP_PAYLOAD_PATH = (
    pathlib.Path(__file__).parents[5] / "app/sep/apps/mysql_backups/xtrabackup_payload"
)


def xtrabackup_payload_tree() -> ast.Module:
    """Parse and return the xtrabackup payload's AST, fresh on every call.

    Centralizes the payload-path lookup so the per-file AST-extraction helpers
    in this directory's test modules do not each re-derive it independently.
    """
    return ast.parse(XTRABACKUP_PAYLOAD_PATH.read_text())
