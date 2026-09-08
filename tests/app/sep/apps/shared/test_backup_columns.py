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

"""Cover the shared backup-family ``Type`` column factory."""

import pytest
from pydantic import ValidationError

from app.sep.apps.shared.backups.columns import (
    BACKUP_TYPE_COLUMN,
    backup_type_column,
)


def test_backup_type_column_carries_the_supplied_labels():
    """Stamp the caller's per-value labels onto the returned column."""
    column = backup_type_column({"M": "Mydumper"})

    assert column.value_labels == {"M": "Mydumper"}


def test_backup_type_column_preserves_the_shared_column_identity():
    """Keep the shared column's key, label and format on the returned copy."""
    column = backup_type_column({"P": "pgBackRest"})

    assert (column.key, column.label, column.format) == (
        BACKUP_TYPE_COLUMN.key,
        BACKUP_TYPE_COLUMN.label,
        BACKUP_TYPE_COLUMN.format,
    )


def test_backup_type_column_leaves_the_shared_constant_unlabelled():
    """Leave ``BACKUP_TYPE_COLUMN`` unmutated after differently-labelled calls."""
    backup_type_column({"M": "Mydumper"})
    backup_type_column({"P": "pgBackRest"})

    assert BACKUP_TYPE_COLUMN.value_labels is None


def test_backup_type_column_does_not_alias_across_calls():
    """Return distinct columns carrying distinct maps on successive calls."""
    first = backup_type_column({"M": "Mydumper"})
    second = backup_type_column({"P": "pgBackRest"})

    assert first is not second
    assert first.value_labels == {"M": "Mydumper"}
    assert second.value_labels == {"P": "pgBackRest"}


def test_backup_type_column_rejects_an_empty_label():
    """Enforce the column's non-empty key and value constraints on the map."""
    with pytest.raises(ValidationError):
        backup_type_column({"M": ""})

    with pytest.raises(ValidationError):
        backup_type_column({"": "Mydumper"})


def test_backup_type_column_copies_the_caller_mapping():
    """Copy the caller's mapping, so a later edit to it cannot leak into the column."""
    labels = {"M": "Mydumper"}

    column = backup_type_column(labels)
    labels["X"] = "XtraBackup"

    assert column.value_labels == {"M": "Mydumper"}
