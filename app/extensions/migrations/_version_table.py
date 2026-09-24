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

"""Move the track's version table forward from its pre-rename name.

Kept out of ``env.py`` for the same reason as ``_orphan_heads.py``: importing
``env.py`` runs migrations as a side effect.

Alembic finds a database's position through the version table named after the
track. The track had another name before the rename to PMM Extensions, so a
database migrated then records its heads in :data:`PRE_RENAME_VERSION_TABLE`.
Read through the new name alone, that database would look empty and have every
revision replayed over tables it already holds. No revision can do the rename,
because Alembic reads the version table before it runs any, so ``env.py`` does
it first, on the connection it is about to migrate.

The move is forward-only. A downgrade leaves the table under its new name, so
downgrading across the rename to the release before it is unsupported.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION_TABLE = "alembic_version_extensions"
"""The track's version table."""

PRE_RENAME_VERSION_TABLE = "alembic_version_sep"
"""The name the track's version table had before the rename. A frozen literal."""


def adopt_pre_rename_version_table(connection: Connection) -> bool:
    """Rename the pre-rename version table in place, keeping its recorded heads.

    A database that already has the current table, or never had the old one, is
    left alone, so the step is a no-op on every run after the first and on every
    fresh database.

    The inspection opens a transaction on the connection, and it is committed on
    either path. Alembic leaves a transaction it did not begin to its caller, so
    one left open here would swallow the whole migration run, and the rename has
    to be durable before Alembic reads the version table anyway.

    :param connection: The synchronous connection about to be migrated.
    :return: Whether the table was renamed.
    """
    inspector = inspect(connection)
    renamed = not inspector.has_table(VERSION_TABLE) and inspector.has_table(
        PRE_RENAME_VERSION_TABLE
    )
    if renamed:
        connection.execute(
            text(f"ALTER TABLE {PRE_RENAME_VERSION_TABLE} RENAME TO {VERSION_TABLE}")
        )
    connection.commit()
    return renamed
