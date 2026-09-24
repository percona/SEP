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
Revises: f7f329837258
Create Date: 2026-09-04 18:42:01.820252

Re-encrypt the secret-typed leaves of every ``settingoverride`` row this track
can resolve, which the write path stored in the clear before this release.

Coverage is **frozen** as the replica model below, which transcribes the shape
``InventorySettings`` reaches today, at the moment of the freeze. Importing the live
class instead would resolve coverage against whatever it looks like on the
release the revision happens to execute against, so a deployment skipping a
release between two renames would leave a legacy plaintext row in the clear.

**Never edit the replica below to track a later rename.** Doing so restores
exactly the coupling the freeze removes. The correct response to a renamed or
retyped field is a new data migration carrying its own frozen shape.

``InventorySettings`` reaches no *overridable* secret-typed field, so this
revision rewrites nothing an operator can have created on a database only
Inventory writes to. It ships because ``settingoverride`` is a shared core model
registered on all three tracks: the revision keeps the tracks symmetric, and it
re-encrypts whatever the replica reaches on a database reaching this revision
for the first time. ``DATABASE.PASSWORD`` is declared because the live class
exposed it to the walker, which is what passing the live class did.

That is the whole of its reach. Alembic never re-runs an applied revision, so a
deployment that already carries this one is not covered by it when the class
later gains a secret-typed field: rows written for that field before the
retyping stay in the clear until a new data migration rewrites them.

Downgrade restores the plaintext the previous release reads.
"""

from pydantic import BaseModel, SecretStr

from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_secret_override_values,
    upgrade_encrypt_secret_override_values,
)

# revision identifiers, used by Alembic.
revision = "74b2ad210981"
down_revision = "f7f329837258"
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
    """Encrypt every not-yet-encrypted secret leaf this track owns.

    Coverage comes from the frozen replicas above rather than the live
    settings classes, so this revision's reach cannot drift with a later rename
    of a field it covers.
    """
    upgrade_encrypt_secret_override_values(SETTINGS_CLASSES)


def downgrade() -> None:
    """Restore every encrypted secret leaf this track owns to plaintext.

    Coverage comes from the frozen replicas above rather than the live
    settings classes, so this revision's reach cannot drift with a later rename
    of a field it covers.
    """
    downgrade_decrypt_secret_override_values(SETTINGS_CLASSES)
