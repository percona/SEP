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
Revises: c9880f0ac1bd
Create Date: 2026-09-04 18:41:55.073171

Re-encrypt the secret-typed leaves of every ``settingoverride`` row this track
can resolve, which the write path stored in the clear before this release.

Coverage is **frozen** as the replica models below, which transcribe the shapes
the live settings classes reach today, at the moment of the freeze. Importing those
classes instead would resolve coverage against whatever they look like on the
release the revision happens to execute against: a deployment skipping a release
between two renames would run this revision against a field set no longer
containing the renamed field, leaving its legacy plaintext row in the clear. The
replicas also keep this revision's imports inside ``app.core``, which is what
lets it run in a migration process at all: resolving coverage through the
override registry would import app packages, whose ``__init__`` pulls a route
graph with a cycle the migration cannot survive.

**Never edit a replica below to track a later rename.** Doing so restores
exactly the coupling the freeze removes. The correct response to a renamed or
retyped field is a new data migration carrying its own frozen shapes;
``test_secret_bearing_overridable_fields_are_pinned`` is what surfaces the
rename so that stays a decision rather than an omission.

The replicas describe every credential-bearing field the classes reached, not
only the overridable ones, because that is what passing the live classes did.
``reencrypt_secret_leaves`` covers both leaf kinds, so the ``CredentialHttpUrl``
fields are declared here too and this revision encrypts their embedded passwords
as well as the ``SecretStr`` leaves.

Completeness is claimed as of this revision only. Alembic never re-runs an
applied revision, so a deployment already carrying this one is not covered by it
when a field it did not reach turns up later — a secret-bearing class becoming
overridable, or a plain field being retyped to a secret. Rows written for such a
field before the change stay in the clear until a new data migration rewrites
them.

Downgrade restores the plaintext the previous release reads.
"""

from pydantic import BaseModel, SecretStr

from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_secret_override_values,
    upgrade_encrypt_secret_override_values,
)
from app.core.utils.fields import (
    CredentialHttpUrl,
    StrCredentialAnyUrl,
    StrCredentialHttpUrl,
)

# revision identifiers, used by Alembic.
revision = "e4b3754984d8"
down_revision = "c9880f0ac1bd"
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


class _FrozenSEPSettings(BaseModel):  # offdiff-ok: frozen replica of the class as named when this revision shipped
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
