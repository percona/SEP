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

"""rewrite persisted plugins module paths to apps

Remediate task rows whose persisted module/file paths still point at the old
``app/sep/plugins`` package after it was renamed to ``app/sep/apps``. Three
runtime-resolved fields are rewritten in place: ``Task.alert_detail_builder``
(a ``module:attr`` path imported when an archiver alert fires), the
inventory-sync ``data.callable`` (imported by the Celery executor), and the
``file://`` payload URIs in ``Task.data`` (read live on every dispatch). New
rows already carry the ``apps`` form; this fixes rows written before the rename.

Revision ID: b74f05a17c8d
Revises: c4e8f0a3b1d2
Create Date: 2026-06-30 18:40:39.709167

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b74f05a17c8d'
down_revision: Union[str, None] = 'c4e8f0a3b1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TASK = sa.table(
    "task",
    sa.column("id", sa.Integer),
    sa.column("alert_detail_builder", sa.String),
    sa.column("data", sa.JSON),
)

_REPLACEMENTS = (
    ("app.sep.plugins", "app.sep.apps"),
    ("app/sep/plugins", "app/sep/apps"),
)


def _rewrite_persisted_paths(replacements: Sequence[tuple[str, str]]) -> None:
    """Apply ``(old, new)`` substring swaps to every task's persisted paths.

    Iterates rows through the bound connection so the substitution is identical
    on PostgreSQL and SQLite, writing back only the rows that actually change.

    :param replacements: Ordered ``(old, new)`` substring pairs to apply.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_TASK.c.id, _TASK.c.alert_detail_builder, _TASK.c.data)
    ).all()
    for row in rows:
        values = {}

        builder = row.alert_detail_builder
        if builder is not None:
            rewritten = builder
            for old, new in replacements:
                rewritten = rewritten.replace(old, new)
            if rewritten != builder:
                values["alert_detail_builder"] = rewritten

        data = row.data
        if data is not None:
            serialized = data if isinstance(data, str) else json.dumps(data)
            rewritten = serialized
            for old, new in replacements:
                rewritten = rewritten.replace(old, new)
            if rewritten != serialized:
                values["data"] = json.loads(rewritten)

        if values:
            bind.execute(
                sa.update(_TASK).where(_TASK.c.id == row.id).values(**values)
            )


def upgrade() -> None:
    _rewrite_persisted_paths(_REPLACEMENTS)


def downgrade() -> None:
    _rewrite_persisted_paths([(new, old) for old, new in _REPLACEMENTS])
