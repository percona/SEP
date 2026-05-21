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

"""Coerce alters tasks --recursion-method=host to hosts

Revision ID: 7d1232c0e3ce
Revises: e42ce8324da7
Create Date: 2026-05-20 15:00:00.000000

"""
import logging
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "7d1232c0e3ce"
down_revision: Union[str, None] = "e42ce8324da7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)

# Match `--recursion-method=host` only when it is NOT a prefix of `=hosts`
# (the corrected value) and NOT a prefix of `=host=...` (a DSN-style value).
_HOST_TO_HOSTS = re.compile(r"--recursion-method=host(?![\w=])")


def _task_table() -> sa.Table:
    return sa.Table(
        "task",
        sa.MetaData(),
        sa.Column("id", sa.Integer()),
        sa.Column("data", sa.JSON()),
        sa.Column("owner", sqlmodel.sql.sqltypes.AutoString()),
    )


def upgrade() -> None:
    """Rewrite legacy ``--recursion-method=host`` to ``hosts`` in alters task args.

    The singular ``host`` value was never accepted by
    ``pt-online-schema-change`` and would have failed at runtime, so the
    affected population is small. Rewriting the stored args in-place closes
    the loop for unedited legacy tasks without an indefinite parser branch.
    """
    task_table = _task_table()
    conn = op.get_bind()

    rows = conn.execute(
        sa.select(
            task_table.c.id,
            task_table.c.data,
        ).where(task_table.c.owner == "ALTERS")
    ).fetchall()

    updated = 0
    for id_, data in rows:
        if not isinstance(data, dict):
            continue
        meta = data.get("meta") or {}
        if meta.get("command") != "pt-online-schema-change":
            continue
        args = meta.get("args")
        if not isinstance(args, str):
            continue
        new_args = _HOST_TO_HOSTS.sub("--recursion-method=hosts", args)
        if new_args == args:
            continue
        new_data = {**data, "meta": {**meta, "args": new_args}}
        conn.execute(
            task_table.update().where(task_table.c.id == id_).values(data=new_data)
        )
        updated += 1
        logger.info("Coerced --recursion-method=host -> hosts for task id=%s", id_)

    logger.info("Migration completed. Coerced %d alters tasks.", updated)


def downgrade() -> None:
    """No-op rollback.

    The legacy ``host`` value was invalid for ``pt-online-schema-change``;
    reverting the coercion would re-introduce broken stored args.
    """
