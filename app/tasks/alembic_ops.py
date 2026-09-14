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

"""Provide the Tasks-track Alembic helpers that rewrite stored execution requests.

Kept out of the revision file so the rewrite can be exercised on a real
PostgreSQL engine. A revision module's filename is not an importable identifier,
so the only route into its body is a full Alembic run, and the Tasks-track
migration fixture stands one up on SQLite alone, while the operation being
tested is entirely a JSONB read and rewrite. The connection is a parameter
rather than an ``op.get_bind()`` call inside for the same reason; the revision
supplies it.
"""

__all__ = [
    "decrypt_execution_request_leaves",
    "encrypt_execution_request_leaves",
]

import logging
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.core.db.sql_types import AutoJSON
from app.tasks.execution_request_secrets import (
    decrypt_request_leaves,
    reencrypt_request_leaves,
)

logger = logging.getLogger(__name__)

_TABLE = "taskhistory"
_COLUMN = "execution_request"

#: Rows held in memory at once while rewriting. Unlike ``settingoverride``,
#: whose rewrite this one mirrors, ``taskhistory`` is unbounded: nothing purges
#: it, so it carries a row per execution for the life of the deployment, and one
#: ``payload`` can be a whole submitted document. Selecting the table in one go
#: would size the upgrade's memory by how long the deployment has been running.
_BATCH_SIZE = 500


def encrypt_execution_request_leaves(bind: Connection) -> None:
    """Encrypt every not-yet-encrypted protected leaf stored in ``taskhistory``.

    Idempotent: a leaf an earlier run already rewrote is structurally recognised
    and left byte-identical, so re-running rewrites nothing and ciphertext
    written under a different ``ENCRYPTION_KEY`` is never encrypted twice.

    :param bind: The migration's bound connection.
    """
    _rewrite_execution_requests(bind, reencrypt_request_leaves)


def decrypt_execution_request_leaves(bind: Connection) -> None:
    """Restore every encrypted protected leaf to the plaintext the old code reads.

    A leaf the configured ``ENCRYPTION_KEY`` cannot decrypt is logged and left as
    it stands rather than aborting: it was already unreadable before the
    downgrade, and refusing to complete would block the rollback the operator is
    performing.

    :param bind: The migration's bound connection.
    """
    _rewrite_execution_requests(bind, _decrypted_document)


def _decrypted_document(document: dict[str, Any]) -> dict[str, Any]:
    """Return ``document`` with its protected leaves decrypted where they can be.

    :param document: The stored execution request.
    :return: The document with every readable protected leaf in plaintext.
    """
    restored, _ = decrypt_request_leaves(document)
    return restored


def _execution_request_table() -> sa.TableClause:
    """Return a lightweight ``taskhistory`` table carrying the JSON column type.

    Declaring ``execution_request`` as :class:`AutoJSON` is what makes the
    rewrite dialect-correct: the column resolves to ``JSONB`` on PostgreSQL and
    ``JSON`` elsewhere, so the loop sees decoded JSON rather than a
    dialect-dependent raw string. The ORM's own column type is deliberately not
    reused, because it would decrypt on read and re-encrypt on write, which is
    the very transform being applied here.

    :return: The table clause the rewrite selects from and updates.
    """
    return sa.table(
        _TABLE,
        sa.column("id", sa.Integer),
        sa.column(_COLUMN, AutoJSON),
    )


def _rewrite_execution_requests(
    bind: Connection, rewrite: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    """Apply ``rewrite`` to every stored execution request, updating what changed.

    Rows are read in primary-key order a batch at a time rather than all at once,
    so the memory the upgrade needs is bounded by :data:`_BATCH_SIZE` instead of
    by the table's size.

    Paging forward by ``id`` assumes nothing is writing to the table meanwhile,
    which is what running migrations against a stopped application gives. It does
    not survive a rolling upgrade: an old instance still writing plaintext can
    insert behind the cursor, and a row whose id was allocated before the cursor
    passed it but which commits afterwards is invisible to that batch and then
    permanently behind it. Either leaves a row in the clear that a re-run would
    pick up.

    :param bind: The migration's bound connection.
    :param rewrite: The per-row transformation of the stored document.
    """
    table = _execution_request_table()
    rewritten = 0
    skipped = 0
    last_id = 0
    while True:
        rows = bind.execute(
            sa.select(table.c.id, table.c[_COLUMN])
            .where(table.c.id > last_id)
            .order_by(table.c.id)
            .limit(_BATCH_SIZE)
        ).all()
        if not rows:
            break
        last_id = rows[-1].id
        for row in rows:
            document = getattr(row, _COLUMN)
            if not isinstance(document, dict):
                skipped += 1
                continue
            value = rewrite(document)
            if value == document:
                continue
            bind.execute(
                table.update().where(table.c.id == row.id).values(**{_COLUMN: value})
            )
            rewritten += 1
    logger.info(
        "Rewrote %s taskhistory row(s); left %s whose execution_request is not a "
        "JSON object.",
        rewritten,
        skipped,
    )
