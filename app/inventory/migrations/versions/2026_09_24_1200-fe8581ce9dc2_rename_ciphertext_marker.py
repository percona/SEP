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

"""rename ciphertext marker

Revision ID: fe8581ce9dc2
Revises: 6ee7bfe9c9d3
Create Date: 2026-09-24 12:00:00.000000

Move the envelope marker of every stored ``settingoverride`` ciphertext from
``sep.enc.v1.`` to ``extensions.enc.v1.``.

The marker is renamed in the same release, and a leaf still carrying the old one
is recognised as neither marked nor bare ciphertext, so it would be read back as
the credential itself. Both markers are frozen literals: the revision must keep
meaning the same thing whatever the marker is called on the release that
executes it.

``downgrade()`` is a documented no-op. Every earlier revision's downgrade runs
this release's code, which reads the new marker alone, so restoring the old one
would strand the downgrades below this revision.
"""

from app.core.settings_override.alembic_ops import rename_ciphertext_marker

# revision identifiers, used by Alembic.
revision = "fe8581ce9dc2"
down_revision = "6ee7bfe9c9d3"
branch_labels = None
depends_on = None

_OLD_MARKER = "sep.enc.v1."
_NEW_MARKER = "extensions.enc.v1."


def upgrade() -> None:
    """Store every ciphertext under the ``extensions.enc.v1.`` marker."""
    rename_ciphertext_marker(_OLD_MARKER, _NEW_MARKER)


def downgrade() -> None:
    """Leave the marker as it stands; see the module docstring."""
