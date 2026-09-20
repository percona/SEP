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

Revision ID: b5e17f6b3bc7
Revises: f3b71c0d9a45
Create Date: 2026-09-14 22:43:41.882413

Encrypt the embedded userinfo password of every credential-bearing URL stored in
a ``settingoverride`` row this track can resolve, which the write path stored in
the clear before this release. Only the password segment is rewritten, so the
endpoint an operator reads out of a raw database dump stays legible.

Unlike its secret-encryption predecessor, this revision is **not** a no-op on a
database only Tasks writes to: ``TasksSettings.NOMAD__endpoint`` inherits
``CredentialHttpUrl`` from ``BaseRemoteAPI`` and is a writable nested leaf under
a nested-overridable parent, so a deployment that has overridden the Nomad
endpoint with credentials has a row here to rewrite.

The settings classes are passed in rather than discovered: resolving them
through the app registry would import app packages, and every app ``__init__``
pulls a route graph with a cycle the migration cannot survive. The list is
complete because no *overridable* field on either class reaches a
credential-bearing URL outside them;
``test_credential_url_migrations_cover_every_credential_url_bearing_class``
holds that invariant from the test side, where the registry *can* be imported.

Completeness is claimed as of this revision only. Alembic never re-runs an
applied revision, so a deployment already carrying this one is not covered by it
when either class later gains a credential-bearing URL field: rows written for
that field before the change stay in the clear until a new data migration
rewrites them.

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
from app.tasks.anonymizer.config import AnonymizerSettings
from app.tasks.config import TasksSettings

# revision identifiers, used by Alembic.
revision = "b5e17f6b3bc7"
down_revision = "f3b71c0d9a45"
branch_labels = None
depends_on = None

SETTINGS_CLASSES = (TasksSettings, AnonymizerSettings)


def upgrade() -> None:
    """Encrypt every not-yet-encrypted credential-URL password this track owns."""
    upgrade_encrypt_credential_url_override_values(SETTINGS_CLASSES)


def downgrade() -> None:
    """Restore every encrypted credential-URL password this track owns."""
    downgrade_decrypt_credential_url_override_values(SETTINGS_CLASSES)
