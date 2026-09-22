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

from app.core.alerts.config import AlertSettings
from app.core.config import Settings
from pydantic import BaseModel, SecretStr

from app.core.settings_override.alembic_ops import (
    downgrade_unmark_secret_override_values,
)
from app.core.utils.fields import (
    CredentialHttpUrl,
    StrCredentialAnyUrl,
    StrCredentialHttpUrl,
)

# revision identifiers, used by Alembic.
revision = "cbc3026013de"
down_revision = "a833d33359d7"
branch_labels = None
depends_on = None

#: The ``settingoverride.setting_class`` values these replicas answer for,
#: matching the tokens ``setting_class_token`` derives for the live classes.
_SETTINGS_CLASS = "SETTINGS"
_ALERT_SETTINGS_CLASS = "ALERT_SETTINGS"
_SEP_SETTINGS_CLASS = "SEP_SETTINGS"
_SNIPPETS_SETTINGS_CLASS = "SNIPPETS_SETTINGS"


class _FrozenPMM(BaseModel):
    """Declare the frozen credential leaves of ``PMMSettings``."""

    endpoint: StrCredentialHttpUrl | None = None
    api_key: SecretStr | None = None


class _FrozenCeleryOptions(BaseModel):
    """Declare the frozen credential leaves of ``CeleryOptions``."""

    broker_url: StrCredentialAnyUrl | None = None
    result_backend: StrCredentialAnyUrl | None = None


class _FrozenSettings(BaseModel):
    """Declare the frozen credential-bearing fields of ``Settings``."""

    __setting_class_token__ = _SETTINGS_CLASS

    PMM: _FrozenPMM | None = None
    CELERY: _FrozenCeleryOptions | None = None
    SECRET_KEY: SecretStr | None = None
    SEP_INTERNAL_TOKEN: SecretStr | None = None
    ENCRYPTION_KEY: SecretStr | None = None


class _FrozenAlertProvider(BaseModel):
    """Declare the credential leaf every ``BaseAlertProvider`` subclass carried."""

    routing_key: SecretStr | None = None


class _FrozenAlertSettings(BaseModel):
    """Declare the frozen credential-bearing fields of ``AlertSettings``.

    ``PROVIDERS`` is a ``list`` where the live field is a ``set``. The walker
    branches on ``_is_collection_origin``, which accepts either, and reads only
    the element type, so the choice is free; ``list`` matches the JSON array
    actually stored.
    """

    __setting_class_token__ = _ALERT_SETTINGS_CLASS

    PROVIDERS: list[_FrozenAlertProvider] | None = None


class _FrozenDatabaseOptions(BaseModel):
    """Declare the frozen credential leaves of ``DatabaseOptions``."""

    PASSWORD: SecretStr | None = None


class _FrozenDeliveryPlan(BaseModel):
    """Declare the frozen credential leaves of ``DeliveryPlan``."""

    endpoint: CredentialHttpUrl | None = None
    secrets: dict[str, SecretStr] | None = None


class _FrozenDeliveryPlanInputs(BaseModel):
    """Declare the frozen credential leaves of ``DeliveryPlanInputs``."""

    endpoint: CredentialHttpUrl | None = None
    secrets: dict[str, SecretStr] | None = None


class _FrozenSEPSettings(BaseModel):
    """Declare the frozen credential-bearing fields of ``SEPSettings``."""

    __setting_class_token__ = _SEP_SETTINGS_CLASS

    INVENTORY_ENDPOINT: CredentialHttpUrl | None = None
    TASKS_ENDPOINT: CredentialHttpUrl | None = None
    DATABASE: _FrozenDatabaseOptions | None = None
    DIAGNOSTICS_DELIVERY: _FrozenDeliveryPlan | None = None
    DIAGNOSTICS_DELIVERY_INPUTS: _FrozenDeliveryPlanInputs | None = None


class _FrozenSnippetsSettings(BaseModel):
    """Stand in for ``SnippetsSettings``, which reaches no credential leaf.

    Field-less rather than absent: dropping it would reclassify its rows as
    unresolved, which changes the rewrite's log line.
    """

    __setting_class_token__ = _SNIPPETS_SETTINGS_CLASS


SETTINGS_CLASSES = (
    _FrozenSettings,
    _FrozenAlertSettings,
    _FrozenSEPSettings,
    _FrozenSnippetsSettings,
)


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
