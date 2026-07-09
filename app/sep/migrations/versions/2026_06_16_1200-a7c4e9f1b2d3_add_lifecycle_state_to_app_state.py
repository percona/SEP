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

"""add lifecycle_state to app state

Revision ID: a7c4e9f1b2d3
Revises: 64f10ead74f6
Create Date: 2026-06-16 12:00:00.000000

The boolean ``appstate.enabled`` column is replaced by the 4-state
``lifecycle_state`` enum in this single migration. Dropping ``enabled`` here is
safe despite the usual two-phase column-drop rule: the entire ``appstate``
feature is unreleased and ships for the first time alongside this change, so no
deployed release reads ``appstate.enabled``. There is no old-code-against-
migrated-schema window for this column.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c4e9f1b2d3"
down_revision: Union[str, None] = "64f10ead74f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIFECYCLE_MEMBERS = ("ENABLED", "DISABLED", "ENABLING", "DISABLING")
_LIFECYCLE_CHECK_NAME = "applifecycleenum"
_LIFECYCLE_CHECK_SQL = "lifecycle_state IN ({})".format(
    ", ".join(f"'{member}'" for member in _LIFECYCLE_MEMBERS)
)


def _lifecycle_type() -> sa.Enum:
    """Build the non-native ``lifecycle_state`` enum column type.

    The CHECK constraint is created explicitly (``create_constraint=False``)
    rather than inline: SQLite's ``ADD COLUMN`` does not emit the enum's inline
    CHECK, so relying on the type would leave a fresh DB without it. The explicit
    constraint reuses the same name (``applifecycleenum``) and ``IN`` clause that
    ``AppState``'s metadata emits, so a DB built from migrations matches one
    built from ``metadata.create_all``.
    """
    return sa.Enum(
        *_LIFECYCLE_MEMBERS,
        name=_LIFECYCLE_CHECK_NAME,
        native_enum=False,
        create_constraint=False,
    )


def upgrade() -> None:
    """Add ``lifecycle_state``, backfill it from ``enabled``, then drop ``enabled``."""
    op.add_column(
        "appstate",
        sa.Column("lifecycle_state", _lifecycle_type(), nullable=True),
    )
    op.execute(
        "UPDATE appstate SET lifecycle_state = "
        "CASE WHEN enabled THEN 'ENABLED' ELSE 'DISABLED' END"
    )
    with op.batch_alter_table("appstate") as batch_op:
        batch_op.alter_column(
            "lifecycle_state", existing_type=_lifecycle_type(), nullable=False
        )
        batch_op.drop_column("enabled")
        batch_op.create_check_constraint(_LIFECYCLE_CHECK_NAME, _LIFECYCLE_CHECK_SQL)


def downgrade() -> None:
    """Restore the boolean ``enabled`` column from ``lifecycle_state``."""
    op.add_column("appstate", sa.Column("enabled", sa.Boolean(), nullable=True))
    op.execute("UPDATE appstate SET enabled = (lifecycle_state = 'ENABLED')")
    with op.batch_alter_table("appstate") as batch_op:
        batch_op.alter_column("enabled", existing_type=sa.Boolean(), nullable=False)
        batch_op.drop_constraint(_LIFECYCLE_CHECK_NAME, type_="check")
        batch_op.drop_column("lifecycle_state")
