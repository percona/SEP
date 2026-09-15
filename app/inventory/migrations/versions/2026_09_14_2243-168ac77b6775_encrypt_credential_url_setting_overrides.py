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

"""encrypt credential url setting overrides

Revision ID: 168ac77b6775
Revises: 74b2ad210981
Create Date: 2026-09-14 22:43:45.318442

Encrypt the embedded userinfo password of every credential-bearing URL stored in
a ``settingoverride`` row this track can resolve, which the write path stored in
the clear before this release. Only the password segment is rewritten, so the
endpoint an operator reads out of a raw database dump stays legible.

``InventorySettings`` reaches no credential-bearing URL field today, so this
revision rewrites nothing on a database only Inventory writes to. It ships
because ``settingoverride`` is a shared core model registered on all three
tracks: the revision keeps the tracks symmetric, and it rewrites whatever the
class reaches on a database reaching this revision for the first time.

That is the whole of its reach. Alembic never re-runs an applied revision, so a
deployment that already carries this one is not covered by it when the class
later gains a credential-bearing URL field: rows written for that field before
the change stay in the clear until a new data migration rewrites them.

Downgrade restores the plaintext the previous release reads, and is scoped to
credential-URL passwords alone. The broad
``downgrade_decrypt_secret_override_values`` would also decrypt the ``SecretStr``
leaves an earlier revision encrypted, and Alembic will not re-run that revision
to put them back.
"""

from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_credential_url_override_values,
    upgrade_encrypt_credential_url_override_values,
)
from app.inventory.config import InventorySettings

# revision identifiers, used by Alembic.
revision = "168ac77b6775"
down_revision = "74b2ad210981"
branch_labels = None
depends_on = None

SETTINGS_CLASSES = (InventorySettings,)


def upgrade() -> None:
    """Encrypt every not-yet-encrypted credential-URL password this track owns."""
    upgrade_encrypt_credential_url_override_values(SETTINGS_CLASSES)


def downgrade() -> None:
    """Restore every encrypted credential-URL password this track owns."""
    downgrade_decrypt_credential_url_override_values(SETTINGS_CLASSES)
