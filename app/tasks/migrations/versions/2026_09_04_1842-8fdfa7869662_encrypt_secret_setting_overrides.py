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

Revision ID: 8fdfa7869662
Revises: 36a31fac9ef7
Create Date: 2026-09-04 18:42:04.805530

Re-encrypt the secret-typed leaves of every ``settingoverride`` row this track
can resolve, which the write path stored in the clear before this release.

Coverage is **frozen** as the replica models below, which transcribe the shapes
``TasksSettings`` and ``AnonymizerSettings`` reach today, at the moment of
the freeze. Importing those classes instead would resolve coverage against
whatever they look like on the release the revision happens to execute against:
a deployment skipping a release between two renames would run this revision
against a field set no longer containing the renamed field, leaving its legacy
plaintext row in the clear. The replicas also keep this revision's imports
inside ``app.core``, which is what lets it run in a migration process at all:
resolving coverage through the override registry would import app packages,
whose ``__init__`` pulls a route graph with a cycle the migration cannot
survive.

**Never edit a replica below to track a later rename.** Doing so restores
exactly the coupling the freeze removes. The correct response to a renamed or
retyped field is a new data migration carrying its own frozen shapes;
``test_secret_bearing_overridable_fields_are_pinned`` is what surfaces the
rename so that stays a decision rather than an omission.

``reencrypt_secret_leaves`` covers both leaf kinds, so ``NOMAD.endpoint`` is
declared here too and this revision encrypts its embedded password as well as
the ``SecretStr`` leaves — which is what passing the live class did.

``NOMAD.api_key`` post-dates this revision's own create date and is declared
anyway, deliberately. It is covered today only because this revision walks the
live class, and no later migration covers it, so narrowing the replica to the
field set of the create date would leave that credential in the clear on every
database that has not yet applied this revision. What the freeze pins is the
reach these revisions have now; reconstructing an earlier one would lose
coverage rather than preserve it.

Completeness is claimed as of this revision only. Alembic never re-runs an
applied revision, so a deployment already carrying this one is not covered by it
when either class later gains a field it did not reach: rows written for that
field before the change stay in the clear until a new data migration rewrites
them.

Downgrade restores the plaintext the previous release reads.
"""

from pydantic import BaseModel, SecretStr

from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_secret_override_values,
    upgrade_encrypt_secret_override_values,
)
from app.core.utils.fields import CredentialHttpUrl

# revision identifiers, used by Alembic.
revision = "8fdfa7869662"
down_revision = "36a31fac9ef7"
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
