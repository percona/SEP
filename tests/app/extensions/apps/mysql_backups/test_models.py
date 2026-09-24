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

"""Cover the MySQL backup model enums and catalog helpers."""

import pytest

from app.extensions.apps.mysql_backups.models import (
    BackupType,
    catalogued_transport_from_upload,
    CataloguedSourceTransport,
)


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


class TestCataloguedTransportFromUpload:
    """Cover ``catalogued_transport_from_upload`` scheme classification."""

    @pytest.mark.parametrize(
        ("upload", "expected"),
        [
            ("s3://bucket/path", CataloguedSourceTransport.S3),
            ("  S3://Bucket/Path  ", CataloguedSourceTransport.S3),
            ("gs://bucket/path", CataloguedSourceTransport.GCS),
            ("GS://bucket/path", CataloguedSourceTransport.GCS),
            ("/data/backups/local", None),
            ("", None),
            (None, None),
            ("   ", None),
        ],
        ids=[
            "s3",
            "s3-case-and-whitespace",
            "gcs",
            "gcs-case",
            "local-path",
            "empty",
            "none",
            "blank",
        ],
    )
    def test_classifies_object_store_uploads(
        self, upload: str | None, expected: CataloguedSourceTransport | None
    ) -> None:
        """Classify only unambiguous object-store uploads; leave local/ssh to restore time."""
        assert catalogued_transport_from_upload(upload) is expected
