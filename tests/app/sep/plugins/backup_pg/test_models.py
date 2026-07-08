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

"""Define tests for the app.sep.plugins.backup_pg.models module."""

import pytest
from pydantic import ValidationError

from app.sep.plugins.backup_pg.models import BackupCreate, BackupType


def test_backup_create_strips_stanza_whitespace() -> None:
    """Stanza trims surrounding whitespace."""
    body = BackupCreate(
        task_name="fake_task",
        hostname="localhost",
        service_id=1,
        backup_type=BackupType.PGBACKREST,
        stanza="  sep-test  ",
    )

    assert body.stanza == "sep-test"


@pytest.mark.parametrize("invalid_stanza", ["../sep", "sep/test", "sep.test", "_sep"])
def test_backup_create_rejects_unsafe_stanza(invalid_stanza: str) -> None:
    """Stanza only allows [A-Za-z0-9][A-Za-z0-9_-]*."""
    with pytest.raises(ValidationError):
        BackupCreate(
            task_name="fake_task",
            hostname="localhost",
            service_id=1,
            backup_type=BackupType.PGBACKREST,
            stanza=invalid_stanza,
        )
