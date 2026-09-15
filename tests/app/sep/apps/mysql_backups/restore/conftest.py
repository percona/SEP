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
from typing import Any

from app.sep.apps.mysql_backups.restore.models import RestoreConfigAll

RESTORE_PAYLOAD_PATH = (
    pathlib.Path(__file__).parents[6]
    / "app/sep/apps/mysql_backups/restore/xtrabackup_payload"
)


def legacy_default(field_name: str) -> Any:
    """Return a gated field's pre-declaration default, read from the config model.

    The config models still declare ``percona`` / ``22`` / ``s3cmd``, so reading
    them here keeps the tests from carrying a second copy of the table the
    normalizer itself derives.
    """
    default = RestoreConfigAll.model_fields[field_name].default
    return getattr(default, "value", default)


def restore_payload_tree() -> ast.Module:
    """Parse and return the restore payload's AST, fresh on every call.

    Centralizes the payload-path lookup so the per-file AST-extraction helpers
    in this directory's test modules do not each re-derive it independently.
    """
    return ast.parse(RESTORE_PAYLOAD_PATH.read_text())
