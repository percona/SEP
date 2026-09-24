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

"""Cover the filter that keeps the library's beat tables out of autogenerate."""

from unittest.mock import MagicMock

import pytest

from app.core.celery.migrations import BEAT_TABLE_NAMES, include_object
from tests.app.beat_autogenerate import BEAT_TABLES


def consider(name: str, type_: str, *, reflected: bool) -> bool:
    """Ask the filter about one object, called the way Alembic calls it.

    Alembic passes every argument positionally, so the arguments the filter
    ignores are supplied here rather than skipped.

    :param name: The object's name, bare rather than schema-qualified.
    :param type_: The kind of object, such as ``"table"`` or ``"column"``.
    :param reflected: Whether the object came from database reflection.
    :return: Whether the autogenerate sweep should consider the object.
    """
    return include_object(MagicMock(), name, type_, reflected, None)


def test_the_excluded_names_are_the_librarys_six_schedule_tables():
    """Derive exactly the beat tables, under the bare names autogenerate reflects.

    ``ModelBase.metadata.tables`` is keyed by the schema-qualified name, so a
    filter built from those keys would match nothing a reflection ever offers.
    """
    assert BEAT_TABLE_NAMES == BEAT_TABLES


def test_a_reflected_beat_table_is_kept_out_of_the_sweep():
    """Exclude a beat table read back from the store, which no track owns."""
    assert consider("celery_periodictask", "table", reflected=True) is False


@pytest.mark.parametrize(
    ("name", "type_", "reflected"),
    [
        pytest.param("celery_periodictask", "table", False, id="beat-name-in-metadata"),
        pytest.param("syncinstance", "table", True, id="reflected-extensions-table"),
        pytest.param(
            "celery_sync_state", "table", True, id="celery-prefixed-extensions-table"
        ),
        pytest.param(
            "celery_periodictask", "column", True, id="column-of-a-beat-table"
        ),
    ],
)
def test_every_other_object_stays_in_the_sweep(
    name: str, type_: str, *, reflected: bool
):
    """Keep the filter narrow enough that a genuinely removed table still shows.

    A blanket "drop every unmatched reflected object" rule would trade this
    ticket's noisy defect for a silent one, so each case here is a shape the
    filter must decline to exclude.
    """
    assert consider(name, type_, reflected=reflected) is True
