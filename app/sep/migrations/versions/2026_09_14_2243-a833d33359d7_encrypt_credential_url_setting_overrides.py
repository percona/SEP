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

Revision ID: a833d33359d7
Revises: e4b3754984d8
Create Date: 2026-09-14 22:43:37.071622

Encrypt the embedded userinfo password of every credential-bearing URL stored in
a ``settingoverride`` row this track can resolve, which the write path stored in
the clear before this release. Only the password segment is rewritten, so the
endpoint an operator reads out of a raw database dump stays legible.

The settings classes are passed in rather than discovered: resolving them
through ``build_sep_override_proxies()`` would import app packages, and every
app ``__init__`` pulls a route graph with a cycle the migration cannot survive.

The list below is complete because no *overridable* field reaches a
credential-bearing URL outside these classes.
``test_credential_url_migrations_cover_every_credential_url_bearing_class``
holds that invariant from the test side, where the registry *can* be imported.

Completeness is claimed as of this revision only. Alembic never re-runs an
applied revision, so a deployment already carrying this one is not covered by it
when a field it did not reach turns up later — a class becoming overridable, or
a plain URL field being retyped as credential-bearing. Rows written for such a
field before the change stay in the clear until a new data migration rewrites
them.

Downgrade restores the plaintext the previous release reads, and is scoped to
credential-URL passwords alone. The broad
``downgrade_decrypt_secret_override_values`` would also decrypt the ``SecretStr``
leaves ``e4b3754984d8`` encrypted, and Alembic will not re-run that revision to
put them back — so those credentials would be left in the clear while the
release being rolled back to still reads them as ciphertext.
"""

from app.core.alerts.config import AlertSettings
from app.core.config import Settings
from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_credential_url_override_values,
    upgrade_encrypt_credential_url_override_values,
)
from app.sep.config import SEPSettings
from app.sep.snippets.config import SnippetsSettings

# revision identifiers, used by Alembic.
revision = "a833d33359d7"
down_revision = "e4b3754984d8"
branch_labels = None
depends_on = None

SETTINGS_CLASSES = (Settings, AlertSettings, SEPSettings, SnippetsSettings)


def upgrade() -> None:
    """Encrypt every not-yet-encrypted credential-URL password this track owns."""
    upgrade_encrypt_credential_url_override_values(SETTINGS_CLASSES)


def downgrade() -> None:
    """Restore every encrypted credential-URL password this track owns."""
    downgrade_decrypt_credential_url_override_values(SETTINGS_CLASSES)
