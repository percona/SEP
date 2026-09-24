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
database only Tasks writes to: ``TasksSettings.NOMAD__endpoint`` is a writable
nested leaf under a nested-overridable parent, so a deployment that has
overridden the Nomad endpoint with credentials has a row here to rewrite.

Coverage is **frozen** as the replica models below, which transcribe the shapes
``TasksSettings`` and ``AnonymizerSettings`` reach today, at the moment of
the freeze. Importing those classes instead would resolve coverage against
whatever they look like on the release the revision happens to execute against:
a deployment skipping a release between two renames would run this revision
against a field set no longer containing the renamed field, leaving its legacy
plaintext password in the clear. The replicas also keep this revision's imports
inside ``app.core``, which is what lets it run in a migration process at all:
resolving coverage through the override registry would import app packages,
whose ``__init__`` pulls a route graph with a cycle the migration cannot
survive.

**Never edit a replica below to track a later rename.** Doing so restores
exactly the coupling the freeze removes. The correct response to a renamed or
retyped field is a new data migration carrying its own frozen shapes;
``test_credential_url_overridable_fields_are_pinned`` is what surfaces the
rename so that stays a decision rather than an omission.

The replicas carry the ``SecretStr`` fields as well, mirroring the shapes
``8fdfa7869662`` froze, even though ``reencrypt_credential_url_leaves`` never
transforms them. Declaring the whole shape is what the live classes did on both
families, so nothing here depends on proving a narrower replica inert.

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

from pydantic import BaseModel, SecretStr

from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_credential_url_override_values,
    upgrade_encrypt_credential_url_override_values,
)
from app.core.utils.fields import CredentialHttpUrl

# revision identifiers, used by Alembic.
revision = "b5e17f6b3bc7"
down_revision = "f3b71c0d9a45"
branch_labels = None
depends_on = None

#: The ``settingoverride.setting_class`` values these replicas answer for,
#: matching the tokens ``setting_class_token`` derives for the live classes.
_TASKS_SETTINGS_CLASS = "TASKS_SETTINGS"
_ANONYMIZER_SETTINGS_CLASS = "ANONYMIZER_SETTINGS"


class _FrozenNomadExecutor(BaseModel):
    """Declare the frozen credential leaves of ``NomadExecutor``."""

    endpoint: CredentialHttpUrl | None = None
    api_key: SecretStr | None = None


class _FrozenDatabaseOptions(BaseModel):
    """Declare the frozen credential leaves of ``DatabaseOptions``."""

    PASSWORD: SecretStr | None = None


class _FrozenTasksSettings(BaseModel):
    """Declare the frozen credential-bearing fields of ``TasksSettings``."""

    __setting_class_token__ = _TASKS_SETTINGS_CLASS

    NOMAD: _FrozenNomadExecutor | None = None
    DATABASE: _FrozenDatabaseOptions | None = None


class _FrozenAnonymizerSettings(BaseModel):
    """Stand in for ``AnonymizerSettings``, which reaches no credential leaf.

    Field-less rather than absent: dropping it would reclassify its rows as
    unresolved, which changes the rewrite's log line.
    """

    __setting_class_token__ = _ANONYMIZER_SETTINGS_CLASS


SETTINGS_CLASSES = (_FrozenTasksSettings, _FrozenAnonymizerSettings)


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
