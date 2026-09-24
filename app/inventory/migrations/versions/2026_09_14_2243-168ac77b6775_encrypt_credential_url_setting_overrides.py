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

Coverage is **frozen** as the replica model below, which transcribes the shape
``InventorySettings`` reaches today, at the moment of the freeze. Importing the live
class instead would resolve coverage against whatever it looks like on the
release the revision happens to execute against, so a deployment skipping a
release between two renames would leave a legacy plaintext password in the
clear.

**Never edit the replica below to track a later rename.** Doing so restores
exactly the coupling the freeze removes. The correct response to a renamed or
retyped field is a new data migration carrying its own frozen shape.

``InventorySettings`` reaches no credential-bearing URL field, so this revision
rewrites nothing on a database only Inventory writes to. It ships because
``settingoverride`` is a shared core model registered on all three tracks: the
revision keeps the tracks symmetric. The replica carries the ``SecretStr`` leaf
``74b2ad210981`` froze, mirroring the shape the live class presented to both
families, even though ``reencrypt_credential_url_leaves`` never transforms it.

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

from pydantic import BaseModel, SecretStr

from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_credential_url_override_values,
    upgrade_encrypt_credential_url_override_values,
)

# revision identifiers, used by Alembic.
revision = "168ac77b6775"
down_revision = "74b2ad210981"
branch_labels = None
depends_on = None

#: The ``settingoverride.setting_class`` values these replicas answer for,
#: matching the tokens ``setting_class_token`` derives for the live classes.
_INVENTORY_SETTINGS_CLASS = "INVENTORY_SETTINGS"


class _FrozenDatabaseOptions(BaseModel):
    """Declare the frozen credential leaves of ``DatabaseOptions``."""

    PASSWORD: SecretStr | None = None


class _FrozenInventorySettings(BaseModel):
    """Declare the frozen credential-bearing fields of ``InventorySettings``."""

    __setting_class_token__ = _INVENTORY_SETTINGS_CLASS

    DATABASE: _FrozenDatabaseOptions | None = None


SETTINGS_CLASSES = (_FrozenInventorySettings,)


def upgrade() -> None:
    """Encrypt every not-yet-encrypted credential-URL password this track owns.

    Coverage comes from the frozen replicas above rather than the live
    settings classes, so this revision's reach cannot drift with a later rename
    of a field it covers.
    """
    upgrade_encrypt_credential_url_override_values(SETTINGS_CLASSES)


def downgrade() -> None:
    """Restore every encrypted credential-URL password this track owns.

    Coverage comes from the frozen replicas above rather than the live
    settings classes, so this revision's reach cannot drift with a later rename
    of a field it covers.
    """
    downgrade_decrypt_credential_url_override_values(SETTINGS_CLASSES)
