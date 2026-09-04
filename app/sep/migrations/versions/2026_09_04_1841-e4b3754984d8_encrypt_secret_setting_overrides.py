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

Revision ID: e4b3754984d8
Revises: 867df844fe17
Create Date: 2026-09-04 18:41:55.073171

Re-encrypt the secret-typed leaves of every ``settingoverride`` row this track
can resolve, which the write path stored in the clear before this release.

The settings classes are passed in rather than discovered: resolving them
through ``build_sep_override_proxies()`` would import app packages, and every
app ``__init__`` pulls a route graph with a cycle the migration cannot survive.

The list below is complete because no *overridable* field reaches a secret
outside these classes. An app-owned class can be secret-bearing
(``HealthReportSettings.api_key`` is), but every such field today is
``NOT_OVERRIDABLE``, so it can never produce an override row to re-encrypt.
``test_migration_settings_classes_cover_every_secret_bearing_class`` holds that
invariant from the test side, where the registry *can* be imported.

Downgrade restores the plaintext the previous release reads.
"""

from app.core.alerts.config import AlertSettings
from app.core.config import Settings
from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_secret_override_values,
    upgrade_encrypt_secret_override_values,
)
from app.sep.config import SEPSettings
from app.sep.snippets.config import SnippetsSettings

# revision identifiers, used by Alembic.
revision = "e4b3754984d8"
down_revision = "867df844fe17"
branch_labels = None
depends_on = None

SETTINGS_CLASSES = (Settings, AlertSettings, SEPSettings, SnippetsSettings)


def upgrade() -> None:
    """Encrypt every not-yet-encrypted secret leaf this track owns."""
    upgrade_encrypt_secret_override_values(SETTINGS_CLASSES)


def downgrade() -> None:
    """Restore every encrypted secret leaf this track owns to plaintext."""
    downgrade_decrypt_secret_override_values(SETTINGS_CLASSES)
