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

"""encrypt secret setting overrides

Revision ID: 8fdfa7869662
Revises: 3a4dfc2a2be8
Create Date: 2026-09-04 18:42:04.805530

Re-encrypt the secret-typed leaves of every ``settingoverride`` row this track
can resolve, which the write path stored in the clear before this release.

Neither ``TasksSettings`` nor ``AnonymizerSettings`` reaches a secret-typed
field today, so this revision rewrites nothing on a database only Tasks writes
to. It ships because ``settingoverride`` is a shared core model registered on
all three tracks: the revision keeps the tracks symmetric, and covers any
secret field either class gains later without a second migration.

Downgrade restores the plaintext the previous release reads.
"""

from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_secret_override_values,
    upgrade_encrypt_secret_override_values,
)
from app.tasks.anonymizer.config import AnonymizerSettings
from app.tasks.config import TasksSettings

# revision identifiers, used by Alembic.
revision = "8fdfa7869662"
down_revision = "3a4dfc2a2be8"
branch_labels = None
depends_on = None

SETTINGS_CLASSES = (TasksSettings, AnonymizerSettings)


def upgrade() -> None:
    """Encrypt every not-yet-encrypted secret leaf this track owns."""
    upgrade_encrypt_secret_override_values(SETTINGS_CLASSES)


def downgrade() -> None:
    """Restore every encrypted secret leaf this track owns to plaintext."""
    downgrade_decrypt_secret_override_values(SETTINGS_CLASSES)
