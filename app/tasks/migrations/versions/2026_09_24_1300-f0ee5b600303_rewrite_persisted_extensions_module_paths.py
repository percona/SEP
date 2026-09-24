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
the ``file://`` URI in ``data.payload`` is read on every dispatch.

Only those three fields move, and only where the value starts with the package:
``app.sep.`` for the two import paths, ``file://app/sep/`` for the payload,
which revision ``13e897d11734`` made relative to the repository. Anything else
in ``Task.data``, including a URL or a path that merely contains the package's
name, is the user's and is left as stored.

Startup seeding already rewrites the ``data`` of the system tasks it owns, but
not the builder, and not a user task created from an app. The prefixes are
frozen literals, so the revision keeps meaning the same thing whatever the
package is called on the release that executes it.

Downgrade across the rename is unsupported. The downgrade restores these rows,
but the release before the rename cannot run on the database regardless: the
Extensions track's version table keeps its new name.
"""

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

_OLD_MODULE = "app.sep."
_NEW_MODULE = "app.extensions."
_OLD_PAYLOAD = "file://app/sep/"
_NEW_PAYLOAD = "file://app/extensions/"


def _moved(value: object, source: str, target: str) -> object:
    """Return ``value`` with its leading ``source`` replaced by ``target``.

    :param value: A stored field value.
    :param source: The prefix the value must start with to move.
    :param target: The prefix to store instead.
    :return: The moved string, or ``value`` unchanged.
    """
    if isinstance(value, str) and value.startswith(source):
        return target + value.removeprefix(source)
    return value


def _rewrite_persisted_paths(module: tuple[str, str], payload: tuple[str, str]) -> None:
    """Move every task's import paths and payload reference between two prefixes.

    Iterates rows through the bound connection so the change is identical on
    PostgreSQL and SQLite, writing back only the rows that actually change.

    :param module: The ``(source, target)`` dotted-path prefixes.
    :param payload: The ``(source, target)`` ``file://`` reference prefixes.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_TASK.c.id, _TASK.c.alert_detail_builder, _TASK.c.data)
    ).all()
    for row in rows:
        values = {}
        builder = _moved(row.alert_detail_builder, *module)
        if builder != row.alert_detail_builder:
            values["alert_detail_builder"] = builder
        if isinstance(row.data, dict):
            data = dict(row.data)
            for key, prefixes in (("callable", module), ("payload", payload)):
                if key in data:
                    data[key] = _moved(data[key], *prefixes)
            if data != row.data:
                values["data"] = data
        if values:
            bind.execute(
                sa.update(_TASK).where(_TASK.c.id == row.id).values(**values)
            )


def upgrade() -> None:
    """Point persisted paths at the ``app/extensions`` package."""
    _rewrite_persisted_paths(
        (_OLD_MODULE, _NEW_MODULE), (_OLD_PAYLOAD, _NEW_PAYLOAD)
    )


def downgrade() -> None:
    """Point persisted paths back at the ``app/sep`` package."""
    _rewrite_persisted_paths(
        (_NEW_MODULE, _OLD_MODULE), (_NEW_PAYLOAD, _OLD_PAYLOAD)
    )
