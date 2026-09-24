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

"""rename sep settings override token

Revision ID: ee2b220c8c73
Revises: cbc3026013de
Create Date: 2026-09-24 12:00:00.000000

Move the stored ``settingoverride.setting_class`` token of the service's own
settings class from ``SEP_SETTINGS`` to ``EXTENSIONS_SETTINGS``.

The token is derived from the settings class name, and that class is now
``ExtensionsSettings``. Without this revision every existing override row for it
would be orphaned: nothing reads a token no live class derives, so the
overrides would silently fall back to their YAML defaults.

Only this track writes rows for that class, and on a shared database the three
tracks share one physical ``settingoverride`` table, so the rename runs here
alone. Both tokens are frozen literals: the revision must keep meaning the same
thing whatever the class is called on the release that executes it.

The ciphertext envelope marker moves from ``sep.enc.v1.`` to
``extensions.enc.v1.`` in the same release. A leaf still carrying the old marker
is recognised as neither marked nor bare ciphertext, so it would be read back as
the credential itself; every track rewrites its own table's markers, and this
revision does so for this one. The marker moves forward only: every earlier
revision's downgrade runs this release's code, which reads the new marker alone,
so restoring the old one would strand the downgrades below this revision.
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.utils import acquire_pg_advisory_xact_lock, table_exists
from app.core.settings_override.alembic_ops import rename_ciphertext_marker
from app.core.settings_override.constants import SETTINGOVERRIDE_MIGRATION_LOCK_KEY

# revision identifiers, used by Alembic.
revision = "ee2b220c8c73"
down_revision = "cbc3026013de"
branch_labels = None
depends_on = None

_OLD_SETTING_CLASS = "SEP_SETTINGS"
_NEW_SETTING_CLASS = "EXTENSIONS_SETTINGS"
_OLD_MARKER = "sep.enc.v1."
_NEW_MARKER = "extensions.enc.v1."


def _retoken(source: str, target: str) -> None:
    """Rewrite every override row stored under ``source`` to ``target``.

    :param source: The token the rows currently carry.
    :param target: The token to store instead.
    """
    bind = op.get_bind()
    acquire_pg_advisory_xact_lock(bind, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
    if not table_exists(bind, "settingoverride"):
        return
    op.execute(
        sa.text(
            "UPDATE settingoverride SET setting_class = :target "
            "WHERE setting_class = :source"
        ).bindparams(target=target, source=source)
    )


def upgrade() -> None:
    """Move the service settings' rows and every stored marker to the new names."""
    _retoken(_OLD_SETTING_CLASS, _NEW_SETTING_CLASS)
    rename_ciphertext_marker(_OLD_MARKER, _NEW_MARKER)


def downgrade() -> None:
    """Restore the ``SEP_SETTINGS`` token the earlier revisions expect."""
    _retoken(_NEW_SETTING_CLASS, _OLD_SETTING_CLASS)
