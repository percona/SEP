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

Revision ID: 74b2ad210981
Revises: 9f2c14d6b8a7
Create Date: 2026-09-04 18:42:01.820252

Re-encrypt the secret-typed leaves of every ``settingoverride`` row this track
can resolve, which the write path stored in the clear before this release.

``InventorySettings`` reaches no secret-typed field today, so this revision
rewrites nothing on a database only Inventory writes to. It ships because
``settingoverride`` is a shared core model registered on all three tracks: the
revision keeps the tracks symmetric, and it re-encrypts whatever the class
reaches on a database reaching this revision for the first time.

That is the whole of its reach. Alembic never re-runs an applied revision, so a
deployment that already carries this one is not covered by it when the class
later gains a secret-typed field: rows written for that field before the
retyping stay in the clear until a new data migration rewrites them.

Downgrade restores the plaintext the previous release reads.
"""

from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_secret_override_values,
    upgrade_encrypt_secret_override_values,
)
from app.inventory.config import InventorySettings

# revision identifiers, used by Alembic.
revision = "74b2ad210981"
down_revision = "9f2c14d6b8a7"
branch_labels = None
depends_on = None

SETTINGS_CLASSES = (InventorySettings,)


def upgrade() -> None:
    """Encrypt every not-yet-encrypted secret leaf this track owns."""
    upgrade_encrypt_secret_override_values(SETTINGS_CLASSES)


def downgrade() -> None:
    """Restore every encrypted secret leaf this track owns to plaintext."""
    downgrade_decrypt_secret_override_values(SETTINGS_CLASSES)
