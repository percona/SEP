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

"""Test the re-encryption helpers the three ``settingoverride`` migrations delegate to.

The helpers reach their bind through ``alembic.op``, so each case drives them
inside a real :class:`~alembic.migration.MigrationContext` over a real SQLite
engine rather than mocking the operations proxy away. The cross-dialect case
lives in ``tests/app/migrations/test_shared_postgres_settingoverride.py``.
"""

import importlib.util
import logging
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlmodel import select, Session

from app import BASE_DIR
from app.core.alerts.config import AlertSettings
from app.core.config import BaseYamlSettings, Settings
from app.core.encryption import decrypt, encrypt, is_encrypted
from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_secret_override_values,
    upgrade_encrypt_secret_override_values,
)
from app.core.settings_override.models import SettingOverride
from app.core.settings_override.registry import (
    is_hot_reloadable,
    is_nested_overridable_parent,
    iter_class_fields,
)
from app.core.settings_override.secret_storage import annotation_contains_secret
from app.core.utils import json_serializer
from app.inventory.config import InventorySettings
from app.sep.api.routes.settings import SEP_ADMIN_SETTINGS_CLASSES
from app.sep.apps.framework.registry import collect_app_owned_settings_classes
from app.sep.config import SEPSettings
from app.tasks.anonymizer.config import AnonymizerSettings
from app.tasks.config import TasksSettings
from tests.app.core.settings_override.conftest import (
    ALERT_SETTINGS_TOKEN,
    PMM_API_KEY,
    PMM_ENDPOINT,
    ROUTING_KEY,
    SEP_SETTINGS_TOKEN,
    SETTINGS_TOKEN,
)

_SEP_TRACK_CLASSES = (Settings, AlertSettings, SEPSettings)
_TASKS_TRACK_CLASSES = (TasksSettings,)

_DELIVERY_SECRETS = {"sn_api_key": "key-value", "client_token": "token-value"}

_SECRET_ROWS: list[tuple[str, str, Any]] = [
    (SETTINGS_TOKEN, "PMM", {"endpoint": PMM_ENDPOINT, "api_key": PMM_API_KEY}),
    (SETTINGS_TOKEN, "PMM__api_key", PMM_API_KEY),
    (
        ALERT_SETTINGS_TOKEN,
        "PROVIDERS",
        [{"PROVIDER": "pagerduty", "routing_key": ROUTING_KEY}],
    ),
    (
        SEP_SETTINGS_TOKEN,
        "DIAGNOSTICS_DELIVERY_INPUTS",
        {"endpoint": "https://intake.example.com/", "secrets": dict(_DELIVERY_SECRETS)},
    ),
]

_NON_SECRET_ROWS: list[tuple[str, str, Any]] = [
    (SETTINGS_TOKEN, "LOGGING", "DEBUG"),
    (SEP_SETTINGS_TOKEN, "SYNC_REFRESH_TIME", 11),
]


@pytest.fixture(name="engine")
def engine_fixture() -> Iterator[Engine]:
    """Yield a SQLite engine carrying only the ``settingoverride`` table."""
    engine = create_engine("sqlite://", json_serializer=json_serializer)
    SettingOverride.metadata.create_all(engine, tables=[SettingOverride.__table__])
    try:
        yield engine
    finally:
        engine.dispose()


def _seed(engine: Engine, rows: list[tuple[str, str, Any]]) -> None:
    """Insert one override row per entry.

    :param engine: The engine to write through.
    :param rows: ``(setting_class, key, value)`` triples to persist.
    """
    with Session(engine) as session:
        for setting_class, key, value in rows:
            session.add(
                SettingOverride(
                    setting_class=setting_class, key=key, value=value, is_active=True
                )
            )
        session.commit()


def _stored(engine: Engine) -> dict[tuple[str, str], Any]:
    """Return every persisted value keyed by ``(setting_class, key)``.

    :param engine: The engine to read from.
    :return: The stored values as the database holds them.
    """
    with Session(engine) as session:
        rows = session.exec(select(SettingOverride)).all()
    return {(row.setting_class, row.key): row.value for row in rows}


def _run(
    engine: Engine,
    operation: Callable[[Iterable[type[BaseYamlSettings]]], None],
    settings_classes: tuple[type[BaseYamlSettings], ...],
) -> None:
    """Run a migration helper against ``engine`` inside a real Alembic context.

    :param engine: The engine the helper's ``op.get_bind()`` resolves to.
    :param operation: The upgrade or downgrade helper to invoke.
    :param settings_classes: The settings classes the simulated track owns.
    """
    with engine.begin() as connection:
        context = MigrationContext.configure(connection=connection)
        with Operations.context(context):
            operation(settings_classes)


#: The Alembic tracks that each ship a re-encryption revision.
_TRACKS = ("sep", "inventory", "tasks")


def _load_revision(path: Path) -> ModuleType:
    """Import one Alembic revision file by path.

    A revision's filename carries its timestamp and hash, so it is not a valid
    module name and cannot be reached by an ordinary import.

    :param path: The revision file to load.
    :return: The loaded module.
    """
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _foreign_token(value: str = "written under another key") -> str:
    """Return ciphertext minted with a key the configured one cannot decrypt.

    :param value: The plaintext to encrypt with the foreign key.
    :return: The foreign Fernet token.
    """
    return Fernet(Fernet.generate_key()).encrypt(value.encode()).decode("ascii")


class TestUpgradeEncryptSecretOverrideValues:
    """Cover the upgrade direction over the rows a real deployment can hold."""

    def test_encrypts_every_secret_shape(self, engine: Engine) -> None:
        """Encrypt the secret leaf of each stored shape, leaving its siblings plain."""
        _seed(engine, _SECRET_ROWS)

        _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)

        stored = _stored(engine)
        pmm = stored[(SETTINGS_TOKEN, "PMM")]
        assert decrypt(pmm["api_key"]) == PMM_API_KEY
        assert pmm["endpoint"] == "https://pmm.example.com"
        assert decrypt(stored[(SETTINGS_TOKEN, "PMM__api_key")]) == PMM_API_KEY
        provider = stored[(ALERT_SETTINGS_TOKEN, "PROVIDERS")][0]
        assert decrypt(provider["routing_key"]) == ROUTING_KEY
        assert provider["PROVIDER"] == "pagerduty"
        inputs = stored[(SEP_SETTINGS_TOKEN, "DIAGNOSTICS_DELIVERY_INPUTS")]
        assert {
            name: decrypt(value) for name, value in inputs["secrets"].items()
        } == _DELIVERY_SECRETS
        assert inputs["endpoint"] == "https://intake.example.com/"

    def test_leaves_non_secret_rows_byte_identical(self, engine: Engine) -> None:
        """Leave a row whose annotation reaches no secret exactly as it was."""
        _seed(engine, _NON_SECRET_ROWS)
        before = _stored(engine)

        _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)

        assert _stored(engine) == before

    def test_leaves_a_setting_class_this_track_cannot_resolve(
        self, engine: Engine
    ) -> None:
        """Leave a row belonging to another service's chain on a shared database."""
        _seed(engine, _SECRET_ROWS)
        before = _stored(engine)

        _run(engine, upgrade_encrypt_secret_override_values, _TASKS_TRACK_CLASSES)

        assert _stored(engine) == before

    def test_leaves_foreign_key_ciphertext_alone(self, engine: Engine) -> None:
        """Skip ciphertext this key cannot read: re-encrypting destroys the only copy."""
        token = _foreign_token()
        _seed(engine, [(SETTINGS_TOKEN, "PMM__api_key", token)])

        _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)

        assert _stored(engine)[(SETTINGS_TOKEN, "PMM__api_key")] == token

    def test_a_second_run_rewrites_nothing(self, engine: Engine) -> None:
        """Keep one layer of ciphertext when the same rows are re-processed.

        Two tracks share one physical ``settingoverride`` table, so the second
        chain to run reaches rows the first already rewrote.
        """
        _seed(engine, _SECRET_ROWS)
        _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)
        after_first = _stored(engine)

        _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)

        assert _stored(engine) == after_first

    def test_missing_table_is_a_no_op(self) -> None:
        """Return without touching anything when another track already dropped the table.

        The ``SELECT`` the rewrite issues would raise against a missing table, so
        reaching the assertion at all is what proves the guard returned first.
        """
        engine = create_engine("sqlite://", json_serializer=json_serializer)
        try:
            _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)

            assert not inspect(engine).has_table("settingoverride")
        finally:
            engine.dispose()


class TestDowngradeDecryptSecretOverrideValues:
    """Cover the downgrade direction, which the previous release's code reads."""

    def test_restores_the_original_plaintext(self, engine: Engine) -> None:
        """Restore every stored shape to exactly what the upgrade found."""
        _seed(engine, _SECRET_ROWS)
        before = _stored(engine)
        _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)

        _run(engine, downgrade_decrypt_secret_override_values, _SEP_TRACK_CLASSES)

        assert _stored(engine) == before

    def test_legacy_plaintext_row_survives_a_downgrade(self, engine: Engine) -> None:
        """Leave a row the upgrade never reached unchanged rather than failing on it."""
        _seed(engine, _SECRET_ROWS)
        before = _stored(engine)

        _run(engine, downgrade_decrypt_secret_override_values, _SEP_TRACK_CLASSES)

        assert _stored(engine) == before

    def test_undecryptable_row_is_logged_and_left_in_place(
        self, engine: Engine, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Complete the rollback, leaving a row minted under another key untouched.

        Aborting would block the rollback outright, and the row was already
        unreadable before the downgrade began.
        """
        caplog.set_level(
            logging.WARNING, logger="app.core.settings_override.alembic_ops"
        )
        token = _foreign_token()
        _seed(
            engine,
            [
                (SETTINGS_TOKEN, "PMM__api_key", token),
                (SETTINGS_TOKEN, "PMM", {"api_key": encrypt(PMM_API_KEY)}),
            ],
        )

        _run(engine, downgrade_decrypt_secret_override_values, _SEP_TRACK_CLASSES)

        stored = _stored(engine)
        assert stored[(SETTINGS_TOKEN, "PMM__api_key")] == token
        assert stored[(SETTINGS_TOKEN, "PMM")]["api_key"] == PMM_API_KEY
        assert any("decrypted" in record.getMessage() for record in caplog.records)

    def test_a_second_run_rewrites_nothing(self, engine: Engine) -> None:
        """Leave already-plaintext rows alone when a second track runs the same downgrade."""
        _seed(engine, _SECRET_ROWS)
        _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)
        _run(engine, downgrade_decrypt_secret_override_values, _SEP_TRACK_CLASSES)
        after_first = _stored(engine)

        _run(engine, downgrade_decrypt_secret_override_values, _SEP_TRACK_CLASSES)

        assert _stored(engine) == after_first


def test_encrypted_rows_are_not_plaintext(engine: Engine) -> None:
    """Confirm the round-trip assertions above are not vacuous.

    Every other case compares decrypted output against the seeded plaintext,
    which would also hold if the upgrade did nothing at all.
    """
    _seed(engine, _SECRET_ROWS)

    _run(engine, upgrade_encrypt_secret_override_values, _SEP_TRACK_CLASSES)

    stored = _stored(engine)
    assert is_encrypted(stored[(SETTINGS_TOKEN, "PMM")]["api_key"])
    assert is_encrypted(stored[(SETTINGS_TOKEN, "PMM__api_key")])
    assert is_encrypted(stored[(ALERT_SETTINGS_TOKEN, "PROVIDERS")][0]["routing_key"])
    assert is_encrypted(
        stored[(SEP_SETTINGS_TOKEN, "DIAGNOSTICS_DELIVERY_INPUTS")]["secrets"][
            "sn_api_key"
        ]
    )


def _secret_bearing_overridable_fields() -> set[tuple[type[BaseYamlSettings], str]]:
    """Return every ``(settings class, key)`` an override row can hold a secret at.

    :return: The overridable secret-bearing fields of every override-exposed class.
    """
    exposed = [
        *(settings_cls for _token, settings_cls, _proxy in SEP_ADMIN_SETTINGS_CLASSES),
        *(entry.settings_cls for entry in collect_app_owned_settings_classes()),
        InventorySettings,
        TasksSettings,
        AnonymizerSettings,
    ]
    return {
        (settings_cls, meta.key)
        for settings_cls in exposed
        for meta in iter_class_fields(settings_cls)
        if annotation_contains_secret(meta.annotation)
        and (
            is_hot_reloadable(settings_cls, meta.key)
            or is_nested_overridable_parent(settings_cls, meta.key)
        )
    }


def test_migration_settings_classes_cover_every_secret_bearing_class() -> None:
    """Assert the three migrations' class lists reach every class that can hold a secret.

    The lists are hand-written because a migration cannot import an app package
    (doing so pulls a route graph with a cycle), so nothing on the migration
    side can notice a class going missing. A settings class can be declared by
    an app without touching core or migrations at all, so the day one marks a
    secret-bearing field overridable, the write path would encrypt new rows
    while no migration ever reached the existing ones. This test is the only
    place both sides can be compared.

    Class membership is the whole of what it compares, which is what a database
    reaching these revisions for the first time needs and nothing more. The
    revisions keep no record of which fields they rewrote, and Alembic will not
    re-run them where they have already applied, so a field turning secret-typed
    on a class that is already listed passes this check untouched;
    :func:`test_secret_bearing_overridable_fields_are_pinned` is what catches it.
    """
    revisions = sorted(
        BASE_DIR.glob("app/*/migrations/versions/*encrypt_secret_setting_overrides.py")
    )
    assert len(revisions) == len(_TRACKS), "one re-encryption revision per track"
    covered = {
        settings_cls
        for revision in revisions
        for settings_cls in _load_revision(revision).SETTINGS_CLASSES
    }
    needs_migrating = {
        settings_cls for settings_cls, _key in _secret_bearing_overridable_fields()
    }

    assert needs_migrating, "the check is vacuous if no class can hold a secret"
    assert needs_migrating <= covered


def test_secret_bearing_overridable_fields_are_pinned() -> None:
    """Assert no overridable field turned secret-typed without its own data migration.

    The re-encryption revisions rewrite a database once, the first time it
    reaches them. Retyping an already-overridable field to a secret afterwards
    leaves every row written for it in the clear wherever they have already
    applied, and the class-level check above cannot see it because the class was
    listed all along. Pinning the set is what turns that into a failure here.

    Adding a field that is secret-typed from the start needs no rewrite -- no row
    was ever stored for it -- so widening the set below is the whole fix. A field
    that *changed* type needs a data migration shipped alongside it.
    """
    assert _secret_bearing_overridable_fields() == {
        (Settings, "PMM"),
        (AlertSettings, "PROVIDERS"),
        (SEPSettings, "DIAGNOSTICS_DELIVERY_INPUTS"),
    }
