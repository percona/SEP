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

"""rewrite persisted extensions module paths

Revision ID: f0ee5b600303
Revises: afa9bedb3b0b
Create Date: 2026-09-24 13:00:00.000000

Move task rows whose persisted module and file paths still point at the
``app/sep`` package after it moved to ``app/extensions``. The fields are the
three that revision ``b74f05a17c8d`` rewrote when the package's ``plugins``
directory became ``apps``, for the same reason: each is resolved at runtime.
``Task.alert_detail_builder`` is a ``module:attr`` path imported when an
archiver alert fires, ``data.callable`` is imported by the Celery executor, and
the ``file://`` payload URIs in ``Task.data`` are read on every dispatch.

Startup seeding already rewrites the ``data`` of the system tasks it owns, but
not the builder, and not a user task created from an app. Both replacement pairs
are frozen literals, so the revision keeps meaning the same thing whatever the
package is called on the release that executes it.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f0ee5b600303"
down_revision = "afa9bedb3b0b"
branch_labels = None
depends_on = None

_TASK = sa.table(
    "task",
    sa.column("id", sa.Integer),
    sa.column("alert_detail_builder", sa.String),
    sa.column("data", sa.JSON),
)

_REPLACEMENTS = (
    ("app.sep.", "app.extensions."),
    ("app/sep/", "app/extensions/"),
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
    """Point persisted paths at the ``app/extensions`` package."""
    _rewrite_persisted_paths(_REPLACEMENTS)


def downgrade() -> None:
    """Point persisted paths back at the ``app/sep`` package."""
    _rewrite_persisted_paths([(new, old) for old, new in _REPLACEMENTS])
