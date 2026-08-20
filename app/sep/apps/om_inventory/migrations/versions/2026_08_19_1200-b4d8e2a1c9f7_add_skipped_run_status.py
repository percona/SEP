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

"""allow a run to record that it was skipped

A sweep refused because another already held its hosts is not a failure and did not
succeed; it did nothing, on purpose. Recording it rather than returning silently is
what keeps a ten-minute schedule from appearing to have fired and found nothing.

The status column is ``native_enum=False``, so its allowed values live in a CHECK
constraint rather than a PostgreSQL type, and widening it is an ``ALTER`` of that
constraint.

Revision ID: b4d8e2a1c9f7
Revises: e7c4a1b9d3f2
Create Date: 2026-08-19 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.sep.config import sep_settings
from app.sep.om.config import om_schema

# revision identifiers, used by Alembic.
revision: str = "b4d8e2a1c9f7"
down_revision: Union[str, None] = "e7c4a1b9d3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: The **names**, not the values. ``EnumField`` persists ``ProbeRunStatus.RUNNING`` as
#: the string ``"RUNNING"`` while its value is ``"running"``, so a constraint built
#: from the values rejects every row already in the table. The same trap
#: ``SettingClassEnum``'s docstring records, walked into once here first.
_EXISTING = ("RUNNING", "SUCCESS", "PARTIAL", "FAILED")
_NEW = (*_EXISTING, "SKIPPED")


def _status(*values: str) -> sa.Enum:
    """Build the enum type as the model declares it.

    :param values: The allowed values.
    :return: The type.
    """
    return sa.Enum(
        *values,
        name="proberunstatus",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    """Widen the status constraint to admit ``skipped``."""
    with op.batch_alter_table("inventory_run", schema=om_schema(sep_settings.DATABASE)) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_status(*_EXISTING),
            type_=_status(*_NEW),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Narrow it again, discarding the rows that used the removed value.

    Without the delete the narrowed constraint rejects existing data and the ALTER
    fails; a skipped run holds nothing worth keeping, so dropping them is honest.
    """
    schema = om_schema(sep_settings.DATABASE)
    table = f"{schema}.inventory_run" if schema else "inventory_run"
    op.execute(f"DELETE FROM {table} WHERE status = 'SKIPPED'")  # noqa: S608
    with op.batch_alter_table("inventory_run", schema=schema) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_status(*_NEW),
            type_=_status(*_EXISTING),
            existing_nullable=False,
        )
