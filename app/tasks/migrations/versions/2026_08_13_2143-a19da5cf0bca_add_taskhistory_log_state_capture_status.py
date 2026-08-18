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

"""add taskhistory_log_state capture_status

Revision ID: a19da5cf0bca
Revises: e2f3a4b5c6d7
Create Date: 2026-08-13 21:43:58.711511

Add a per-``(source, stream)`` capture verdict on ``taskhistory_log_state`` so a
reader can tell a stream that genuinely produced nothing from one whose bytes
were lost before SEP read them. The stored offsets cannot distinguish the two:
both leave the cursors at zero.

Existing rows — including every row stranded at ``producer_offset = 0`` by the
lost-log defect — take ``unknown`` from the server default. That is deliberate
and there is no backfill: the source bytes are already garbage-collected, so
which of the two populations a given row belongs to is unrecoverable, and
``unknown`` is the only honest classification.

The server default is ``UNKNOWN`` while the model default is ``INCOMPLETE``, and
the difference is load-bearing. SQLAlchemy always sends the column on INSERT, so
the server default governs only these pre-existing rows; rows written after the
upgrade start ``INCOMPLETE`` and are upgraded once their stream drains to EOF.

Both are spelled as enum *member names*, not member values: ``sa.Enum`` persists
``.name``, so a server default of ``"unknown"`` would write a string the mapped
type cannot read back, and every backfilled row would raise ``LookupError`` on
the first ORM read.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a19da5cf0bca"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CAPTURE_STATUS_MEMBERS = ("COMPLETE", "INCOMPLETE", "UNKNOWN")
_CAPTURE_STATUS_CHECK_NAME = "logcapturestatusenum"
_CAPTURE_STATUS_CHECK_SQL = "capture_status IN ({})".format(
    ", ".join(f"'{member}'" for member in _CAPTURE_STATUS_MEMBERS)
)


def _capture_status_type() -> sa.Enum:
    """Build the non-native ``capture_status`` enum column type.

    The CHECK constraint is created explicitly (``create_constraint=False``)
    rather than inline: SQLite's ``ADD COLUMN`` skips the enum's implicit CHECK
    with only a warning, so relying on the type would leave a fresh SQLite DB
    without it while PostgreSQL got one. The explicit constraint reuses the same
    name (``logcapturestatusenum``) and ``IN`` clause that ``TaskHistoryLogState``
    emits, so a DB built from migrations matches one built from
    ``metadata.create_all``.

    :return: The non-native enum type, with constraint creation deferred.
    """
    return sa.Enum(
        *_CAPTURE_STATUS_MEMBERS,
        name=_CAPTURE_STATUS_CHECK_NAME,
        native_enum=False,
        create_constraint=False,
    )


def upgrade() -> None:
    op.add_column(
        "taskhistory_log_state",
        sa.Column(
            "capture_status",
            _capture_status_type(),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    with op.batch_alter_table("taskhistory_log_state") as batch_op:
        batch_op.create_check_constraint(
            _CAPTURE_STATUS_CHECK_NAME, _CAPTURE_STATUS_CHECK_SQL
        )


def downgrade() -> None:
    with op.batch_alter_table("taskhistory_log_state") as batch_op:
        batch_op.drop_constraint(_CAPTURE_STATUS_CHECK_NAME, type_="check")
        batch_op.drop_column("capture_status")
