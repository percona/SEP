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

Revision ID: cbc3026013de
Revises: a833d33359d7
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
"""

from app.core.alerts.config import AlertSettings
from app.core.config import Settings
from app.core.settings_override.alembic_ops import (
    downgrade_unmark_secret_override_values,
)
from app.sep.config import SEPSettings
from app.sep.snippets.config import SnippetsSettings

# revision identifiers, used by Alembic.
revision = "cbc3026013de"
down_revision = "a833d33359d7"
branch_labels = None
depends_on = None

SETTINGS_CLASSES = (Settings, AlertSettings, SEPSettings, SnippetsSettings)


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
