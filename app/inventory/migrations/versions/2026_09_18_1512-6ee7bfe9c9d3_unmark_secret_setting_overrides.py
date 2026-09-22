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

"""unmark secret setting overrides

Revision ID: 6ee7bfe9c9d3
Revises: b351dd0aaed8
Create Date: 2026-09-18 15:12:00.000000

Give the versioned ciphertext envelope a downgrade boundary of its own.

From this release, every secret leaf the settings-override write path stores
carries an explicit marker naming its envelope version, so "is this already
encrypted?" is read off the stored value's own format instead of guessed from
its bytes. That is a code-level format with no schema change behind it, which is
exactly why it needs a revision: without one there would be no boundary at which
a rollback could strip the marker, and a release predating the envelope reads a
marked value as *plaintext* and would present it to a remote as a credential.

``upgrade()`` is therefore a documented no-op and ``downgrade()`` carries the
work. Stripping the marker is a string operation over the stored text, so it
needs no ``ENCRYPTION_KEY``, never decrypts, and leaves a bare Fernet token the
earlier release reads correctly through its own structural check.
Coverage is **frozen** as the replica models below, on the same terms as the
encrypt revisions this one rolls back. Importing the live settings classes
instead would resolve coverage against whatever they look like on the release
the revision happens to execute against, and an omission here is worse than in
an encrypt revision: a class the rollback misses keeps its marker, and a release
predating the envelope reads a marked value as the plaintext credential and
presents it to a remote.

**Never edit a replica below to track a later rename.** The correct response to
a renamed or retyped field is a new data migration carrying its own frozen
shapes.

``unmark_secret_leaves`` covers both leaf kinds, exactly as the marking write
path does, so the credential-URL fields are declared here alongside the
``SecretStr`` ones.
"""

from pydantic import BaseModel, SecretStr

from app.core.settings_override.alembic_ops import (
    downgrade_unmark_secret_override_values,
)

# revision identifiers, used by Alembic.
revision = "6ee7bfe9c9d3"
down_revision = "b351dd0aaed8"
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
    """Do nothing: the ciphertext envelope ships with the code, not the schema.

    Present so the rollback below has a revision to hang on. Re-marking rows an
    earlier downgrade unmarked is deliberately not done here — nothing at
    migration time can tell a legacy ciphertext from a legacy plaintext that
    merely looks like one, and guessing wrong freezes the misclassification.
    Those rows are marked again the next time they are written.
    """


def downgrade() -> None:
    """Strip the envelope marker so a release predating it reads these rows."""
    downgrade_unmark_secret_override_values(SETTINGS_CLASSES)
