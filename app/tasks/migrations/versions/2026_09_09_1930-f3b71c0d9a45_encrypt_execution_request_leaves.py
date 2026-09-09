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

"""encrypt execution request leaves

Revision ID: f3b71c0d9a45
Revises: c4b8e1f7a2d9
Create Date: 2026-09-09 19:30:00.000000

Encrypt the three credential-bearing leaves of every stored ``taskhistory``
execution request, which the write path stored in the clear before this release:
``meta.args`` holds the command line an operator submitted, passwords included,
``meta.config`` the configuration an app serialised from its form, a plain-string
password field included, and ``payload`` the submitted document or the reference
standing in for one. A raw dump of the tasks database read all three verbatim.

Every row is rewritten with no eligibility test, and a leaf already encrypted is
recognised structurally and left byte-identical, so a re-run rewrites nothing.
A row whose ``execution_request`` is not a JSON object is skipped.

The column type is unchanged: the leaves stay inside the same JSONB document and
every other ``meta`` key stays plaintext and queryable. That is a deliberate
limit rather than an oversight, and it is the whole of the coverage: a request
recording a credential under some other ``meta`` key is untouched by this
revision.

Downgrade restores the plaintext the previous release reads, logging and leaving
any leaf the configured ``ENCRYPTION_KEY`` cannot decrypt rather than aborting a
rollback over a row that was already unreadable.
"""

from alembic import op

from app.tasks.alembic_ops import (
    decrypt_execution_request_leaves,
    encrypt_execution_request_leaves,
)

# revision identifiers, used by Alembic.
revision = "f3b71c0d9a45"
down_revision = "c4b8e1f7a2d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Encrypt every not-yet-encrypted protected leaf in ``taskhistory``."""
    encrypt_execution_request_leaves(op.get_bind())


def downgrade() -> None:
    """Restore every encrypted protected leaf in ``taskhistory`` to plaintext."""
    decrypt_execution_request_leaves(op.get_bind())
