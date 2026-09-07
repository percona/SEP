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

"""Cover the MySQL backup model enums."""

from app.sep.apps.mysql_backups.models import BackupType


def test_backup_type_labels_cover_every_member():
    """Label every declared ``BackupType`` member, keyed by its stored value."""
    assert set(BackupType.LABELS) == {member.value for member in BackupType}


def test_backup_type_labels_are_the_declared_display_strings():
    """Pin the display text each stored backup-type value resolves to."""
    assert BackupType.LABELS == {
        "M": "Mydumper",
        "X": "XtraBackup",
        "B": "Binlog",
    }


def test_backup_type_labels_is_not_an_enum_member():
    """Keep ``LABELS`` off the enum's member list via ``enum.nonmember``."""
    assert "LABELS" not in {member.name for member in BackupType}
