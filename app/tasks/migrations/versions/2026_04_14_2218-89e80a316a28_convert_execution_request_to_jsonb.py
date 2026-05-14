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

"""Convert taskhistory.execution_request to jsonb and add meta GIN index

Revision ID: 89e80a316a28
Revises: 9ebd648709e8
Create Date: 2026-04-14 22:18:35.568389

Perform two PostgreSQL-only operations during the upgrade downtime window:

1. ``ALTER TABLE taskhistory ALTER COLUMN execution_request TYPE jsonb USING
   execution_request::jsonb`` rewrites every row under ``ACCESS EXCLUSIVE``.
   The cost scales with ``taskhistory`` row count (approximately one minute
   per two million rows on typical production hardware); size the upgrade
   window accordingly. The operation is safe under SEP's standard upgrade
   downtime because no concurrent writers compete for the lock.
2. ``CREATE INDEX ix_taskhistory_execution_request_meta ON taskhistory USING
   GIN ((execution_request->'meta') jsonb_path_ops)`` builds a GIN expression
   index used by the ``@>`` containment clauses emitted by
   ``_raise_if_identical_task_conflict``. ``jsonb_path_ops`` is the smallest
   and fastest operator class for ``@>`` queries; it does not support the
   ``?`` / ``?&`` / ``?|`` key-existence operators, so a future ticket that
   needs those operators against ``execution_request->'meta'`` must rebuild
   the index with the default ``jsonb_ops``. Plain ``CREATE INDEX`` (not
   ``CONCURRENTLY``) is correct here because the downtime window has no
   traffic, and a synchronous build rolls back atomically on failure with no
   ``INVALID`` index state to clean up.

SQLite and MySQL: no-op. SQLite has no distinct ``jsonb`` type and its
``json_extract`` path is unchanged. MySQL stays on plain JSON for the same
reason SEP-818 skipped MySQL indexing (fixed-width ``CAST`` truncation risk
in functional indexes).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "89e80a316a28"
down_revision: Union[str, None] = "9ebd648709e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE taskhistory "
        "ALTER COLUMN execution_request TYPE jsonb "
        "USING execution_request::jsonb"
    )
    op.execute(
        "CREATE INDEX ix_taskhistory_execution_request_meta "
        "ON taskhistory USING GIN ((execution_request->'meta') jsonb_path_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_taskhistory_execution_request_meta")
    op.execute(
        "ALTER TABLE taskhistory "
        "ALTER COLUMN execution_request TYPE json "
        "USING execution_request::json"
    )
