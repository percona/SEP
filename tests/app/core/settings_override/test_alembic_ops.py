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

"""Test the re-encryption helpers the six ``settingoverride`` migrations delegate to.

The helpers reach their bind through ``alembic.op``, so each case drives them
inside a real :class:`~alembic.migration.MigrationContext` over a real SQLite
engine rather than mocking the operations proxy away. The cross-dialect case
lives in ``tests/app/migrations/test_shared_postgres_settingoverride.py``.

Two groups of cases drive the helpers with the live settings classes, which is
what the read and write paths pass. The rest load each revision's own frozen
coverage declarations and assert literal historical outcomes against them, so
they keep meaning the same thing once the live classes drift away from what a
shipped revision froze.
"""

import importlib.util
import logging
import typing
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from pathlib import Path
from types import ModuleType, UnionType
from typing import Any, Union
from urllib.parse import urlparse

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.fernet import Fernet
from pydantic import BaseModel, SecretBytes, SecretStr
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlmodel import select, Session

from app import BASE_DIR
from app.core.alerts.config import AlertSettings
from app.core.alerts.models import BaseAlertProvider
from app.core.config import BaseYamlSettings, Settings
from app.core.encryption import decrypt, encrypt, is_encrypted
from app.core.settings_override.alembic_ops import (
    downgrade_decrypt_credential_url_override_values,
    downgrade_decrypt_secret_override_values,
    upgrade_encrypt_credential_url_override_values,
    upgrade_encrypt_secret_override_values,
)
from app.core.settings_override.models import setting_class_token, SettingOverride
from app.core.settings_override.registry import (
    annotated_type,
    annotation_is_credential_url,
    is_credential_url_field,
    is_hot_reloadable,
    is_nested_overridable_parent,
    iter_class_fields,
)
from app.core.utils import json_serializer
from app.core.utils.fields import StrCredentialHttpUrl
from app.inventory.config import InventorySettings
from app.sep.api.routes.settings import SEP_ADMIN_SETTINGS_CLASSES
from app.sep.apps.framework.registry import collect_app_owned_settings_classes
from app.sep.config import SEPSettings
from app.tasks.anonymizer.config import AnonymizerSettings
from app.tasks.config import TasksSettings
from tests.app.core.settings_override.conftest import (
    ALERT_SETTINGS_TOKEN,
    INVENTORY_SETTINGS_TOKEN,
    PMM_API_KEY,
    PMM_ENDPOINT,
    ROUTING_KEY,
    SEP_SETTINGS_TOKEN,
    SETTINGS_TOKEN,
    SNIPPETS_SETTINGS_TOKEN,
    TASKS_SETTINGS_TOKEN,
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

_CREDENTIAL_URL = "https://inv-user:hunter2@inv.example.com:8443/api"
_CREDENTIAL_PASSWORD = "hunter2"
_CREDENTIAL_HOST = "inv.example.com"
_CREDENTIAL_PORT = 8443
_CREDENTIAL_PATH = "/api"

_CREDENTIAL_URL_ROWS: list[tuple[str, str, Any]] = [
    (SEP_SETTINGS_TOKEN, "INVENTORY_ENDPOINT", _CREDENTIAL_URL),
    (SEP_SETTINGS_TOKEN, "TASKS_ENDPOINT", _CREDENTIAL_URL),
    (SETTINGS_TOKEN, "PMM__endpoint", _CREDENTIAL_URL),
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

#: The revision-filename globs selecting each re-encryption family.
_SECRET_REVISION_GLOB = "app/*/migrations/versions/*encrypt_secret_setting_overrides.py"
_CREDENTIAL_URL_REVISION_GLOB = (
    "app/*/migrations/versions/*encrypt_credential_url_setting_overrides.py"
)


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


def _frozen_classes(glob: str, track: str) -> tuple[type[BaseModel], ...]:
    """Return one track's frozen coverage declarations, read from its revision file.

    :param glob: The revision-filename glob selecting one family.
    :param track: The Alembic track owning the revision.
    :return: The ``SETTINGS_CLASSES`` tuple that revision ships.
    """
    revisions = [path for path in BASE_DIR.glob(glob) if path.parts[-4] == track]
    assert len(revisions) == 1, f"one {track} revision matching {glob}"
    return _load_revision(revisions[0]).SETTINGS_CLASSES


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


#: The leaf kinds :func:`_derive_shape` reports, in its own vocabulary: the
#: walker's ``_LeafKind`` is private, and a pinned shape only has to be stable.
_SECRET_LEAF = "secret"
_CREDENTIAL_URL_LEAF = "credential_url"


def _positional_args(annotation: Any) -> list[Any]:
    """Return the types a value at one JSON position may take.

    Strips ``Annotated`` wrappers, flattens unions and drops ``NoneType``, as
    the walker does. It deliberately does **not** reproduce the walker's
    declaration ordering, which exists so a contested position resolves to its
    first credential-bearing candidate; :func:`_derive_shape` keeps every
    candidate instead, so order cannot matter to it.

    :param annotation: The annotation to flatten.
    :return: The candidate types for this position.
    """
    flattened: list[Any] = []
    stack = [annotation]
    while stack:
        current = stack.pop()
        if current is type(None):
            continue
        if hasattr(current, "__metadata__"):
            stack.append(typing.get_args(current)[0])
            continue
        if typing.get_origin(current) in {Union, UnionType}:
            stack.extend(typing.get_args(current))
            continue
        flattened.append(current)
    return flattened


def _candidate_models(positional: list[Any]) -> list[type[BaseModel]]:
    """Return every model a value at one position may validate as.

    Subclasses are included recursively for the same reason the walker includes
    them: a collection annotated with its base (``set[BaseAlertProvider]``)
    reaches the subclass that actually declares the secret field.

    Only subclasses already imported are visible, so a shape derived through a
    polymorphic position depends on what the test session has loaded. That is
    faithful — it is the walker's own behaviour, and the reason a frozen replica
    is not subject to it — but it means a provider stand-in declared in some
    other test module and carrying a credential field would widen the pinned
    shape. None does today; a surprise failure in
    :func:`test_secret_bearing_overridable_fields_are_pinned` naming a leaf no
    live class declares is this, not a rename.

    :param positional: The candidate types for one JSON position.
    :return: The reachable model classes.
    """
    models: list[type[BaseModel]] = []
    queue = list(positional)
    while queue:
        current = queue.pop(0)
        if not (isinstance(current, type) and issubclass(current, BaseModel)):
            continue
        if current in models:
            continue
        models.append(current)
        queue.extend(current.__subclasses__())
    return models


def _derive_shape(
    annotation: Any, path: str = "", seen: frozenset[type[BaseModel]] = frozenset()
) -> frozenset[tuple[str, str]]:
    """Return the credential leaves a walk over ``annotation`` can rewrite.

    Each leaf is reported as its dotted path below the overridden key paired
    with its kind: ``.api_key`` for an object field, ``[].routing_key`` for a
    collection element's field, ``.secrets.*`` for a mapping's values. An
    annotation that *is* a credential leaf reports the empty path.

    The point of reducing to paths rather than comparing annotations is that a
    rename or a retype changes the set while a refactor that preserves the
    stored JSON does not, which is exactly the distinction
    :func:`test_secret_bearing_overridable_fields_are_pinned` has to draw.

    Two deliberate approximations of the walker, both in the direction that
    fails loudly rather than silently: a contested position keeps every
    candidate where the walker resolves to one, and a fixed-length ``tuple``
    is read through its first argument rather than per index. No live field is
    a fixed-length tuple; if one appears, this under-reports it and the pin
    must be revisited alongside it.

    :param annotation: The annotation to reduce.
    :param path: The dotted path already walked, for recursive calls.
    :param seen: Models already expanded, so a self-referential annotation
        terminates.
    :return: The ``(path, kind)`` pairs reachable from ``annotation``.
    """
    if annotation is None:
        return frozenset()
    if annotation_is_credential_url(annotation):
        return frozenset({(path, _CREDENTIAL_URL_LEAF)})
    positional = _positional_args(annotation)
    if any(
        isinstance(arg, type) and issubclass(arg, SecretStr | SecretBytes)
        for arg in positional
    ):
        return frozenset({(path, _SECRET_LEAF)})
    return _container_leaves(positional, path, seen) | _model_leaves(
        positional, path, seen
    )


def _container_leaves(
    positional: list[Any], path: str, seen: frozenset[type[BaseModel]]
) -> frozenset[tuple[str, str]]:
    """Return the leaves below a mapping's values or a collection's items.

    :param positional: The candidate types for one JSON position.
    :param path: The dotted path already walked.
    :param seen: Models already expanded.
    :return: The ``(path, kind)`` pairs reachable through a container.
    """
    leaves: set[tuple[str, str]] = set()
    for arg in positional:
        origin = typing.get_origin(arg)
        args = typing.get_args(arg)
        if not isinstance(origin, type) or not args:
            continue
        if issubclass(origin, Mapping):
            leaves |= _derive_shape(args[-1], f"{path}.*", seen)
        elif issubclass(origin, Collection) and not issubclass(origin, str | bytes):
            leaves |= _derive_shape(args[0], f"{path}[]", seen)
    return frozenset(leaves)


def _model_leaves(
    positional: list[Any], path: str, seen: frozenset[type[BaseModel]]
) -> frozenset[tuple[str, str]]:
    """Return the leaves below the models a JSON position may validate as.

    :param positional: The candidate types for one JSON position.
    :param path: The dotted path already walked.
    :param seen: Models already expanded.
    :return: The ``(path, kind)`` pairs reachable through a model's fields.
    """
    leaves: set[tuple[str, str]] = set()
    for model in _candidate_models(positional):
        if model in seen:
            continue
        for name, field_info in model.model_fields.items():
            leaves |= _derive_shape(
                annotated_type(field_info), f"{path}.{name}", seen | {model}
            )
    return frozenset(leaves)


def _pinned_shapes(
    fields: set[tuple[type[BaseYamlSettings], str]],
) -> set[tuple[type[BaseYamlSettings], str, frozenset[tuple[str, str]]]]:
    """Return ``fields`` with each entry's walker-visible shape attached.

    Both producers below enumerate ``model_fields``, so every key here is
    top-level and indexes the class directly.

    :param fields: The ``(settings class, key)`` pairs to describe.
    :return: The same pairs, each carrying its derived shape.
    """
    return {
        (
            settings_cls,
            key,
            _derive_shape(annotated_type(settings_cls.model_fields[key])),
        )
        for settings_cls, key in fields
    }


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
        if meta.is_secret
        and (
            is_hot_reloadable(settings_cls, meta.key)
            or is_nested_overridable_parent(settings_cls, meta.key)
        )
    }


def _frozen_coverage(glob: str) -> set[str]:
    """Return the storage tokens a migration family's replicas declare.

    Membership is deliberately the whole comparison, exactly as it was when the
    revisions held live classes. Tightening it to ``(token, key)`` would leave a
    newly secret-typed field with no reachable remedy: the only ways back to
    green would be editing a shipped replica, which every revision docstring
    forbids, or marking the field non-overridable.
    :func:`test_secret_bearing_overridable_fields_are_pinned` is what carries the
    field-level signal, and a new field there is widened by editing the pin.

    :param glob: The revision-filename glob selecting one family.
    :return: The storage tokens the family's frozen replicas answer for.
    """
    return {
        setting_class_token(frozen_cls)
        for track in _TRACKS
        for frozen_cls in _frozen_classes(glob, track)
    }


def _live_coverage(fields: set[tuple[type[BaseYamlSettings], str]]) -> set[str]:
    """Return the storage tokens of the classes ``fields`` names.

    :param fields: The ``(settings class, key)`` pairs the live classes expose.
    :return: The same coverage expressed the way a stored row identifies itself.
    """
    return {setting_class_token(settings_cls) for settings_cls, _key in fields}


def test_migration_settings_classes_cover_every_secret_bearing_class() -> None:
    """Assert the three migrations' frozen replicas reach every key that can hold a secret.

    A settings class can be declared by an app without touching core or
    migrations at all, so the day one marks a secret-bearing field overridable,
    the write path would encrypt new rows while no migration ever reached the
    existing ones. This test is the only place both sides can be compared: the
    revisions cannot import an app package (doing so pulls a route graph with a
    cycle), while the test can.

    Comparison is by *storage token* rather than by class identity because the
    revisions no longer hold the live classes at all — they hold frozen
    replicas, which are different objects by construction. The token is what a
    stored row actually carries, so it is the right join key, and class
    membership stays the whole of what is compared, as before.

    Only one direction is asserted. ``live ⊆ frozen`` keeps a secret-bearing
    class failing until some revision answers for it. ``frozen ⊆ live`` is
    deliberately **not** asserted: a legitimate rename leaves the shipped
    revisions covering a key the live classes no longer have, which is the whole
    point of freezing them, and
    :func:`test_a_frozen_revision_still_covers_a_renamed_legacy_leaf` pins that
    divergence as intended behaviour.
    """
    covered = _frozen_coverage(_SECRET_REVISION_GLOB)
    needs_migrating = _live_coverage(_secret_bearing_overridable_fields())

    assert needs_migrating, "the check is vacuous if no class can hold a secret"
    assert needs_migrating <= covered


def test_secret_bearing_overridable_fields_are_pinned() -> None:
    """Assert no overridable field turned secret-typed without its own data migration.

    The re-encryption revisions rewrite a database once, the first time it
    reaches them. Retyping an already-overridable field to a secret afterwards
    leaves every row written for it in the clear wherever they have already
    applied, and the class-level check above cannot see it because the class was
    listed all along. Pinning the set is what turns that into a failure here.

    Adding a field that is secret-typed from the start needs no rewrite, because
    no row was ever stored for it, so widening the set below is the whole fix. A
    field that *changed* type needs a data migration shipped alongside it.

    The pin carries each field's *shape* as well as its name, because the
    migrations no longer read the live classes at all: they carry frozen
    replicas of these shapes, and a leaf renamed inside one of them would
    otherwise move silently. A diff here is the signal that the shipped
    revisions have stopped matching the live classes — which is allowed, and is
    what :func:`test_a_frozen_revision_still_covers_a_renamed_legacy_leaf`
    exercises — but it must be a decision rather than an accident.
    """
    assert _pinned_shapes(_secret_bearing_overridable_fields()) == {
        (
            Settings,
            "PMM",
            frozenset(
                {(".api_key", _SECRET_LEAF), (".endpoint", _CREDENTIAL_URL_LEAF)}
            ),
        ),
        (AlertSettings, "PROVIDERS", frozenset({("[].routing_key", _SECRET_LEAF)})),
        (
            SEPSettings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            frozenset(
                {(".endpoint", _CREDENTIAL_URL_LEAF), (".secrets.*", _SECRET_LEAF)}
            ),
        ),
        (
            TasksSettings,
            "NOMAD",
            frozenset(
                {(".api_key", _SECRET_LEAF), (".endpoint", _CREDENTIAL_URL_LEAF)}
            ),
        ),
    }


def _credential_url_bearing_overridable_fields() -> set[
    tuple[type[BaseYamlSettings], str]
]:
    """Return every ``(settings class, key)`` an override row can hold a credential URL at.

    Mirrors :func:`_secret_bearing_overridable_fields` against the credential-URL
    predicate instead of ``is_secret``, so the two migration families are held to
    the same completeness standard.

    :return: The overridable credential-URL-bearing fields of every exposed class.
    """
    exposed = [
        *(settings_cls for _token, settings_cls, _proxy in SEP_ADMIN_SETTINGS_CLASSES),
        *(entry.settings_cls for entry in collect_app_owned_settings_classes()),
        InventorySettings,
        TasksSettings,
        AnonymizerSettings,
    ]
    return {
        (settings_cls, name)
        for settings_cls in exposed
        for name, field_info in settings_cls.model_fields.items()
        if is_credential_url_field(field_info)
        and (
            is_hot_reloadable(settings_cls, name)
            or is_nested_overridable_parent(settings_cls, name)
        )
    }


def test_credential_url_migrations_cover_every_credential_url_bearing_class() -> None:
    """Assert the three credential-URL revisions reach every key that can hold one.

    The sibling of :func:`test_migration_settings_classes_cover_every_secret_bearing_class`,
    and it exists for the same reason and compares the same way: by storage
    token, in the ``live ⊆ frozen`` direction only.

    The glob deliberately does not match the earlier family's
    ``*encrypt_secret_setting_overrides.py`` suffix, which that sibling resolves
    one revision per track over.
    """
    covered = _frozen_coverage(_CREDENTIAL_URL_REVISION_GLOB)
    needs_migrating = _live_coverage(_credential_url_bearing_overridable_fields())

    assert needs_migrating, "the check is vacuous if no class can hold a credential URL"
    assert needs_migrating <= covered


def test_credential_url_overridable_fields_are_pinned() -> None:
    """Assert no overridable field turned credential-URL-typed without a data migration.

    ``Settings.CELERY`` is absent by construction rather than by omission: it is
    a plain field, so ``CeleryOptions.broker_url`` and ``result_backend`` can
    never produce an override row. The predicate is marker-driven, so the day
    ``CELERY`` becomes overridable this set changes and the failure here is what
    forces the accompanying migration.

    Shapes are pinned alongside the names for the reason
    :func:`test_secret_bearing_overridable_fields_are_pinned` gives: the
    revisions carry frozen replicas of these shapes rather than reading the live
    classes, so a leaf renamed inside one must surface here.
    """
    assert _pinned_shapes(_credential_url_bearing_overridable_fields()) == {
        (
            Settings,
            "PMM",
            frozenset(
                {(".api_key", _SECRET_LEAF), (".endpoint", _CREDENTIAL_URL_LEAF)}
            ),
        ),
        (SEPSettings, "INVENTORY_ENDPOINT", frozenset({("", _CREDENTIAL_URL_LEAF)})),
        (SEPSettings, "TASKS_ENDPOINT", frozenset({("", _CREDENTIAL_URL_LEAF)})),
        (
            SEPSettings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            frozenset(
                {(".endpoint", _CREDENTIAL_URL_LEAF), (".secrets.*", _SECRET_LEAF)}
            ),
        ),
        (
            TasksSettings,
            "NOMAD",
            frozenset(
                {(".api_key", _SECRET_LEAF), (".endpoint", _CREDENTIAL_URL_LEAF)}
            ),
        ),
    }


class TestCredentialUrlOverrideValues:
    """Cover the credential-URL-scoped pair the new revisions delegate to."""

    def test_round_trips_a_stored_credential_url(self, engine: Engine) -> None:
        """Encrypt the password, keep the endpoint readable, then restore it exactly."""
        _seed(engine, _CREDENTIAL_URL_ROWS)
        before = _stored(engine)

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _SEP_TRACK_CLASSES,
        )

        stored = _stored(engine)[(SEP_SETTINGS_TOKEN, "INVENTORY_ENDPOINT")]
        parsed = urlparse(stored)
        assert is_encrypted(parsed.password)
        assert parsed.hostname == _CREDENTIAL_HOST
        assert parsed.port == _CREDENTIAL_PORT
        assert parsed.path == _CREDENTIAL_PATH

        _run(
            engine,
            downgrade_decrypt_credential_url_override_values,
            _SEP_TRACK_CLASSES,
        )

        assert _stored(engine) == before

    def test_the_downgrade_leaves_an_earlier_revisions_ciphertext_untouched(
        self, engine: Engine
    ) -> None:
        """Assert the downgrade is its own inverse and not the broad helper's.

        This is the state the earlier secret-encryption revision leaves: a ``PMM``
        row whose ``api_key`` is ciphertext beside a plaintext endpoint. The broad
        ``downgrade_decrypt_secret_override_values`` would return that ``api_key``
        as plaintext while its own revision stays marked applied, so nothing would
        ever re-encrypt it.

        The ``api_key`` is compared byte-for-byte rather than with
        ``is_encrypted``: a re-encryption under a fresh Fernet IV satisfies the
        weaker check while having rewritten exactly the data that must not move.
        """
        seeded_api_key = encrypt(PMM_API_KEY)
        _seed(
            engine,
            [
                (
                    SETTINGS_TOKEN,
                    "PMM",
                    {"endpoint": _CREDENTIAL_URL, "api_key": seeded_api_key},
                )
            ],
        )

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _SEP_TRACK_CLASSES,
        )
        _run(
            engine,
            downgrade_decrypt_credential_url_override_values,
            _SEP_TRACK_CLASSES,
        )

        row = _stored(engine)[(SETTINGS_TOKEN, "PMM")]
        assert row["endpoint"] == _CREDENTIAL_URL
        assert row["api_key"] == seeded_api_key

    def test_the_upgrade_leaves_a_plaintext_secret_in_the_clear(
        self, engine: Engine
    ) -> None:
        """Leave a ``SecretStr`` leaf alone: it belongs to the earlier revision."""
        _seed(
            engine,
            [
                (
                    SETTINGS_TOKEN,
                    "PMM",
                    {"endpoint": _CREDENTIAL_URL, "api_key": PMM_API_KEY},
                )
            ],
        )

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _SEP_TRACK_CLASSES,
        )

        row = _stored(engine)[(SETTINGS_TOKEN, "PMM")]
        assert is_encrypted(urlparse(row["endpoint"]).password)
        assert row["api_key"] == PMM_API_KEY

    def test_a_second_upgrade_run_rewrites_nothing(self, engine: Engine) -> None:
        """Keep one layer of ciphertext when two tracks reach the same shared rows."""
        _seed(engine, _CREDENTIAL_URL_ROWS)
        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _SEP_TRACK_CLASSES,
        )
        after_first = _stored(engine)

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _SEP_TRACK_CLASSES,
        )

        assert _stored(engine) == after_first

    def test_leaves_a_setting_class_this_track_cannot_resolve(
        self, engine: Engine
    ) -> None:
        """Leave a row belonging to another service's chain on a shared database."""
        _seed(engine, _CREDENTIAL_URL_ROWS)
        before = _stored(engine)

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _TASKS_TRACK_CLASSES,
        )

        assert _stored(engine) == before

    def test_the_tasks_track_rewrites_its_nomad_endpoint(self, engine: Engine) -> None:
        """Rewrite ``NOMAD__endpoint``, which is why the tasks revision is not a no-op.

        Its secret-encryption sibling rewrites nothing on a Tasks-only database;
        copying that claim forward would be false.
        """
        _seed(engine, [(TASKS_SETTINGS_TOKEN, "NOMAD__endpoint", _CREDENTIAL_URL)])

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _TASKS_TRACK_CLASSES,
        )

        stored = _stored(engine)[(TASKS_SETTINGS_TOKEN, "NOMAD__endpoint")]
        assert is_encrypted(urlparse(stored).password)
        assert decrypt(urlparse(stored).password) == "hunter2"

    def test_missing_table_is_a_no_op(self) -> None:
        """Return without touching anything when another track already dropped the table."""
        engine = create_engine("sqlite://", json_serializer=json_serializer)
        try:
            _run(
                engine,
                upgrade_encrypt_credential_url_override_values,
                _SEP_TRACK_CLASSES,
            )

            assert not inspect(engine).has_table("settingoverride")
        finally:
            engine.dispose()


def _models_in_annotation(annotation: Any) -> set[type[BaseModel]]:
    """Return every model mentioned anywhere inside ``annotation``.

    Descends through ``Annotated``, unions and container parameters alike, so a
    replica named only as ``list[_FrozenAlertProvider] | None`` is still found.

    :param annotation: The annotation to search.
    :return: The models it mentions.
    """
    found: set[type[BaseModel]] = set()
    stack = [annotation]
    while stack:
        current = stack.pop()
        if isinstance(current, type) and issubclass(current, BaseModel):
            found.add(current)
            continue
        stack.extend(typing.get_args(current))
    return found


def _replica_classes(glob: str, track: str) -> set[type[BaseModel]]:
    """Return every replica model one revision's coverage reaches.

    Wider than :func:`_frozen_classes`, which yields only the classes named in
    ``SETTINGS_CLASSES``: the models those declare for their nested leaves are
    replicas too, and are the ones that could plausibly join a subclass walk.

    :param glob: The revision-filename glob selecting one family.
    :param track: The Alembic track owning the revision.
    :return: The declared classes plus every model reachable from their fields.
    """
    discovered: set[type[BaseModel]] = set()
    queue = list(_frozen_classes(glob, track))
    while queue:
        current = queue.pop()
        if current in discovered:
            continue
        discovered.add(current)
        for field_info in current.model_fields.values():
            queue.extend(_models_in_annotation(field_info.annotation))
    return discovered


#: One stored row per scalar credential leaf the replicas declare, as
#: ``(track, token, key, seeded value, leaf kind)``. Every leaf a ``__``-key can
#: address appears here, across all three tracks, because nothing else guards a
#: transcription typo in one: the pinned-shape tests read the *live* classes and
#: the coverage tests compare class membership, so a replica leaf misspelled at
#: authoring time would otherwise stop being encrypted in silence. The container
#: shapes — ``PMM``, ``PROVIDERS``, ``DIAGNOSTICS_DELIVERY_INPUTS`` — are not
#: ``__``-addressable and are covered by the cases around this table.
_FROZEN_LEAF_CASES: list[tuple[str, str, str, Any, str]] = [
    ("sep", SETTINGS_TOKEN, "SECRET_KEY", "settings-secret-key", _SECRET_LEAF),
    ("sep", SETTINGS_TOKEN, "SEP_INTERNAL_TOKEN", "internal-token", _SECRET_LEAF),
    ("sep", SETTINGS_TOKEN, "ENCRYPTION_KEY", "encryption-key", _SECRET_LEAF),
    ("sep", SETTINGS_TOKEN, "PMM__api_key", PMM_API_KEY, _SECRET_LEAF),
    ("sep", SETTINGS_TOKEN, "PMM__endpoint", _CREDENTIAL_URL, _CREDENTIAL_URL_LEAF),
    (
        "sep",
        SETTINGS_TOKEN,
        "CELERY__broker_url",
        _CREDENTIAL_URL,
        _CREDENTIAL_URL_LEAF,
    ),
    (
        "sep",
        SETTINGS_TOKEN,
        "CELERY__result_backend",
        _CREDENTIAL_URL,
        _CREDENTIAL_URL_LEAF,
    ),
    ("sep", SEP_SETTINGS_TOKEN, "DATABASE__PASSWORD", "sep-db-password", _SECRET_LEAF),
    (
        "sep",
        SEP_SETTINGS_TOKEN,
        "INVENTORY_ENDPOINT",
        _CREDENTIAL_URL,
        _CREDENTIAL_URL_LEAF,
    ),
    (
        "sep",
        SEP_SETTINGS_TOKEN,
        "TASKS_ENDPOINT",
        _CREDENTIAL_URL,
        _CREDENTIAL_URL_LEAF,
    ),
    (
        "sep",
        SEP_SETTINGS_TOKEN,
        "DIAGNOSTICS_DELIVERY__endpoint",
        _CREDENTIAL_URL,
        _CREDENTIAL_URL_LEAF,
    ),
    (
        "sep",
        SEP_SETTINGS_TOKEN,
        "DIAGNOSTICS_DELIVERY_INPUTS__endpoint",
        _CREDENTIAL_URL,
        _CREDENTIAL_URL_LEAF,
    ),
    ("tasks", TASKS_SETTINGS_TOKEN, "NOMAD__api_key", "nomad-api-key", _SECRET_LEAF),
    (
        "tasks",
        TASKS_SETTINGS_TOKEN,
        "NOMAD__endpoint",
        _CREDENTIAL_URL,
        _CREDENTIAL_URL_LEAF,
    ),
    (
        "tasks",
        TASKS_SETTINGS_TOKEN,
        "DATABASE__PASSWORD",
        "tasks-db-password",
        _SECRET_LEAF,
    ),
    (
        "inventory",
        INVENTORY_SETTINGS_TOKEN,
        "DATABASE__PASSWORD",
        "inventory-db-password",
        _SECRET_LEAF,
    ),
]


class TestFrozenSecretRevisionOutcomes:
    """Cover the secret family driven by the revisions' own frozen declarations.

    Every expectation below is written out rather than derived from a live
    settings class, so these cases keep asserting the same historical outcomes
    after the live classes drift — which is the divergence the freeze exists to
    allow, and which any live-versus-frozen equality check would forbid.
    """

    @pytest.mark.parametrize(
        ("track", "token", "key", "seeded", "kind"), _FROZEN_LEAF_CASES
    )
    def test_rewrites_every_declared_leaf(
        self, engine: Engine, track: str, token: str, key: str, seeded: Any, kind: str
    ) -> None:
        """Rewrite each leaf the track's replicas declare, one stored row at a time.

        This family covers both leaf kinds, so every row in the table is
        rewritten whichever kind it carries.
        """
        _seed(engine, [(token, key, seeded)])

        _run(
            engine,
            upgrade_encrypt_secret_override_values,
            _frozen_classes(_SECRET_REVISION_GLOB, track),
        )

        stored = _stored(engine)[(token, key)]
        if kind == _SECRET_LEAF:
            assert decrypt(stored) == seeded
        else:
            parsed = urlparse(stored)
            assert decrypt(parsed.password) == _CREDENTIAL_PASSWORD
            assert parsed.hostname == _CREDENTIAL_HOST
            assert parsed.port == _CREDENTIAL_PORT

    def test_encrypts_every_secret_shape(self, engine: Engine) -> None:
        """Encrypt each stored shape's secret leaf exactly as the live classes did."""
        _seed(engine, _SECRET_ROWS)

        _run(
            engine,
            upgrade_encrypt_secret_override_values,
            _frozen_classes(_SECRET_REVISION_GLOB, "sep"),
        )

        stored = _stored(engine)
        pmm = stored[(SETTINGS_TOKEN, "PMM")]
        assert decrypt(pmm["api_key"]) == PMM_API_KEY
        assert pmm["endpoint"] == PMM_ENDPOINT
        assert decrypt(stored[(SETTINGS_TOKEN, "PMM__api_key")]) == PMM_API_KEY
        provider = stored[(ALERT_SETTINGS_TOKEN, "PROVIDERS")][0]
        assert decrypt(provider["routing_key"]) == ROUTING_KEY
        assert provider["PROVIDER"] == "pagerduty"
        inputs = stored[(SEP_SETTINGS_TOKEN, "DIAGNOSTICS_DELIVERY_INPUTS")]
        assert {
            name: decrypt(value) for name, value in inputs["secrets"].items()
        } == _DELIVERY_SECRETS
        assert inputs["endpoint"] == "https://intake.example.com/"

    def test_leaves_a_row_the_replicas_do_not_declare_byte_identical(
        self, engine: Engine
    ) -> None:
        """Leave a row no replica field names exactly as it was.

        Every replica field is credential-bearing by construction, so under a
        frozen declaration the "resolves but reaches no credential" branch the
        live classes exercise is unreachable: these keys resolve to no field at
        all and :func:`_annotation_for_key` returns ``None``.
        """
        _seed(engine, _NON_SECRET_ROWS)
        before = _stored(engine)

        _run(
            engine,
            upgrade_encrypt_secret_override_values,
            _frozen_classes(_SECRET_REVISION_GLOB, "sep"),
        )

        assert _stored(engine) == before

    def test_encrypts_the_password_of_a_credential_url_leaf(
        self, engine: Engine
    ) -> None:
        """Rewrite ``PMM__endpoint``'s password: this family covers both leaf kinds.

        A replica declaring only the ``SecretStr`` fields would silently narrow
        the revision here and break its downgrade's symmetry with
        :func:`downgrade_decrypt_secret_override_values`.
        """
        _seed(engine, [(SETTINGS_TOKEN, "PMM__endpoint", _CREDENTIAL_URL)])

        _run(
            engine,
            upgrade_encrypt_secret_override_values,
            _frozen_classes(_SECRET_REVISION_GLOB, "sep"),
        )

        parsed = urlparse(_stored(engine)[(SETTINGS_TOKEN, "PMM__endpoint")])
        assert decrypt(parsed.password) == _CREDENTIAL_PASSWORD
        assert parsed.hostname == _CREDENTIAL_HOST
        assert parsed.port == _CREDENTIAL_PORT

    def test_resolves_every_nested_key_shape(self, engine: Engine) -> None:
        """Resolve each ``__``-delimited row the frozen replicas declare a leaf for."""
        _seed(
            engine,
            [
                (SETTINGS_TOKEN, "PMM__api_key", PMM_API_KEY),
                (
                    SEP_SETTINGS_TOKEN,
                    "DIAGNOSTICS_DELIVERY_INPUTS__secrets",
                    dict(_DELIVERY_SECRETS),
                ),
            ],
        )

        _run(
            engine,
            upgrade_encrypt_secret_override_values,
            _frozen_classes(_SECRET_REVISION_GLOB, "sep"),
        )

        stored = _stored(engine)
        assert decrypt(stored[(SETTINGS_TOKEN, "PMM__api_key")]) == PMM_API_KEY
        secrets = stored[(SEP_SETTINGS_TOKEN, "DIAGNOSTICS_DELIVERY_INPUTS__secrets")]
        assert {
            name: decrypt(value) for name, value in secrets.items()
        } == _DELIVERY_SECRETS

    def test_the_tasks_track_encrypts_its_nomad_leaves(self, engine: Engine) -> None:
        """Rewrite ``NOMAD__api_key`` and ``NOMAD__endpoint`` under the tasks replicas."""
        _seed(
            engine,
            [
                (TASKS_SETTINGS_TOKEN, "NOMAD__api_key", PMM_API_KEY),
                (TASKS_SETTINGS_TOKEN, "NOMAD__endpoint", _CREDENTIAL_URL),
            ],
        )

        _run(
            engine,
            upgrade_encrypt_secret_override_values,
            _frozen_classes(_SECRET_REVISION_GLOB, "tasks"),
        )

        stored = _stored(engine)
        assert decrypt(stored[(TASKS_SETTINGS_TOKEN, "NOMAD__api_key")]) == PMM_API_KEY
        parsed = urlparse(stored[(TASKS_SETTINGS_TOKEN, "NOMAD__endpoint")])
        assert decrypt(parsed.password) == _CREDENTIAL_PASSWORD

    def test_a_class_with_no_covered_keys_still_resolves_its_rows(
        self, engine: Engine, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Count a ``SnippetsSettings`` row as resolved rather than as another track's.

        The field-less replica exists precisely so this row walks to a no-op
        instead of being tallied ``unresolved``, which would change the log line
        an operator reads after the migration.
        """
        caplog.set_level(logging.INFO, logger="app.core.settings_override.alembic_ops")
        _seed(engine, [(SNIPPETS_SETTINGS_TOKEN, "SOME_KEY", "value")])

        _run(
            engine,
            upgrade_encrypt_secret_override_values,
            _frozen_classes(_SECRET_REVISION_GLOB, "sep"),
        )

        assert _stored(engine)[(SNIPPETS_SETTINGS_TOKEN, "SOME_KEY")] == "value"
        assert any(
            "left 0 untouched" in record.getMessage() for record in caplog.records
        )

    def test_a_second_run_rewrites_nothing(self, engine: Engine) -> None:
        """Keep one layer of ciphertext when the frozen classes reach the rows twice."""
        frozen = _frozen_classes(_SECRET_REVISION_GLOB, "sep")
        _seed(engine, _SECRET_ROWS)
        _run(engine, upgrade_encrypt_secret_override_values, frozen)
        after_first = _stored(engine)

        _run(engine, upgrade_encrypt_secret_override_values, frozen)

        assert _stored(engine) == after_first

    def test_round_trips_back_to_the_seeded_plaintext(self, engine: Engine) -> None:
        """Restore every seeded shape byte-identically through the frozen downgrade."""
        frozen = _frozen_classes(_SECRET_REVISION_GLOB, "sep")
        _seed(engine, _SECRET_ROWS)
        before = _stored(engine)
        _run(engine, upgrade_encrypt_secret_override_values, frozen)

        _run(engine, downgrade_decrypt_secret_override_values, frozen)

        assert _stored(engine) == before


class TestFrozenCredentialUrlRevisionOutcomes:
    """Cover the credential-URL family driven by its own frozen declarations."""

    @pytest.mark.parametrize(
        ("track", "token", "key", "seeded", "kind"), _FROZEN_LEAF_CASES
    )
    def test_rewrites_every_declared_url_leaf_and_only_those(
        self, engine: Engine, track: str, token: str, key: str, seeded: Any, kind: str
    ) -> None:
        """Rewrite each declared URL leaf and leave each declared secret leaf alone.

        The replicas declare both kinds, so running the same table through this
        family is what shows the narrowing comes from the entry point's ``kinds``
        rather than from a replica that omitted the fields it must not rewrite.
        """
        _seed(engine, [(token, key, seeded)])

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _frozen_classes(_CREDENTIAL_URL_REVISION_GLOB, track),
        )

        stored = _stored(engine)[(token, key)]
        if kind == _CREDENTIAL_URL_LEAF:
            parsed = urlparse(stored)
            assert decrypt(parsed.password) == _CREDENTIAL_PASSWORD
            assert parsed.hostname == _CREDENTIAL_HOST
        else:
            assert stored == seeded

    def test_encrypts_passwords_and_keeps_endpoints_legible(
        self, engine: Engine
    ) -> None:
        """Rewrite only the userinfo password of each stored credential URL."""
        _seed(engine, _CREDENTIAL_URL_ROWS)

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _frozen_classes(_CREDENTIAL_URL_REVISION_GLOB, "sep"),
        )

        stored = _stored(engine)
        for key in ("INVENTORY_ENDPOINT", "TASKS_ENDPOINT"):
            parsed = urlparse(stored[(SEP_SETTINGS_TOKEN, key)])
            assert decrypt(parsed.password) == _CREDENTIAL_PASSWORD
            assert parsed.hostname == _CREDENTIAL_HOST
            assert parsed.port == _CREDENTIAL_PORT
            assert parsed.path == _CREDENTIAL_PATH
        nested = urlparse(stored[(SETTINGS_TOKEN, "PMM__endpoint")])
        assert decrypt(nested.password) == _CREDENTIAL_PASSWORD

    def test_leaves_a_secret_leaf_byte_identical(self, engine: Engine) -> None:
        """Leave a ``SecretStr`` leaf alone: it belongs to the earlier revision.

        The frozen replicas declare those fields, so this also proves the
        scoping comes from the entry point rather than from a narrowed replica.
        """
        _seed(
            engine,
            [
                (
                    SETTINGS_TOKEN,
                    "PMM",
                    {"endpoint": _CREDENTIAL_URL, "api_key": PMM_API_KEY},
                )
            ],
        )

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _frozen_classes(_CREDENTIAL_URL_REVISION_GLOB, "sep"),
        )

        row = _stored(engine)[(SETTINGS_TOKEN, "PMM")]
        assert is_encrypted(urlparse(row["endpoint"]).password)
        assert row["api_key"] == PMM_API_KEY

    def test_round_trips_back_to_the_seeded_plaintext(self, engine: Engine) -> None:
        """Restore every seeded credential URL byte-identically."""
        frozen = _frozen_classes(_CREDENTIAL_URL_REVISION_GLOB, "sep")
        _seed(engine, _CREDENTIAL_URL_ROWS)
        before = _stored(engine)
        _run(engine, upgrade_encrypt_credential_url_override_values, frozen)

        _run(engine, downgrade_decrypt_credential_url_override_values, frozen)

        assert _stored(engine) == before

    def test_the_tasks_track_rewrites_its_nomad_endpoint(self, engine: Engine) -> None:
        """Rewrite ``NOMAD__endpoint``, which is why the tasks revision is not a no-op."""
        _seed(engine, [(TASKS_SETTINGS_TOKEN, "NOMAD__endpoint", _CREDENTIAL_URL)])

        _run(
            engine,
            upgrade_encrypt_credential_url_override_values,
            _frozen_classes(_CREDENTIAL_URL_REVISION_GLOB, "tasks"),
        )

        parsed = urlparse(_stored(engine)[(TASKS_SETTINGS_TOKEN, "NOMAD__endpoint")])
        assert decrypt(parsed.password) == _CREDENTIAL_PASSWORD


class _DriftedPMM(BaseModel):
    """Stand in for a ``PMMSettings`` whose ``api_key`` was later renamed."""

    endpoint: StrCredentialHttpUrl | None = None
    token: SecretStr | None = None


class _DriftedSettings(BaseModel):
    """Stand in for a released ``Settings`` the shipped revisions predate."""

    __setting_class_token__ = "SETTINGS"

    PMM: _DriftedPMM | None = None


def test_every_revision_declares_replicas_rather_than_live_settings_classes() -> None:
    """Assert no re-encryption revision reaches a live settings class.

    This is the invariant the whole ticket rests on, and the only check that
    distinguishes a frozen revision from the importing one it replaced: reaching
    a live class is exactly what makes coverage depend on the release the
    revision executes against rather than the one it was authored for.

    The token must come from the ``__setting_class_token__`` escape hatch
    because a replica's ``__name__`` is its own, not the live class's, so
    nothing else would make it answer for the stored rows.
    """
    assert issubclass(Settings, BaseYamlSettings), (
        "the check is vacuous unless a live settings class would fail it"
    )

    for glob in (_SECRET_REVISION_GLOB, _CREDENTIAL_URL_REVISION_GLOB):
        for track in _TRACKS:
            frozen_classes = _frozen_classes(glob, track)
            assert frozen_classes, f"{track} ships no coverage declarations"
            for frozen_cls in frozen_classes:
                assert not issubclass(frozen_cls, BaseYamlSettings), (
                    f"{track} reaches the live class {frozen_cls.__name__}"
                )
                assert "__setting_class_token__" in vars(frozen_cls), (
                    f"{frozen_cls.__name__} pins no storage token"
                )


def test_a_frozen_revision_still_covers_a_renamed_legacy_leaf(engine: Engine) -> None:
    """Assert a shipped revision keeps rewriting a leaf the live classes renamed away.

    This is the scenario the whole freeze is for, and the only case that
    exercises a revision *after* its live counterpart has drifted. A deployment
    that skipped the release carrying the rename still holds rows written under
    the old name; resolving coverage from the renamed class at migration time
    would walk straight past them and leave the credential in the clear.

    The two runs assert opposite outcomes on the same row on purpose. The
    divergence is the feature, so it is pinned rather than forbidden — an
    equality check between the frozen declaration and the live class would
    outlaw exactly this.
    """
    _seed(engine, [(SETTINGS_TOKEN, "PMM", {"api_key": PMM_API_KEY})])

    _run(engine, upgrade_encrypt_secret_override_values, (_DriftedSettings,))

    assert _stored(engine)[(SETTINGS_TOKEN, "PMM")]["api_key"] == PMM_API_KEY

    _run(
        engine,
        upgrade_encrypt_secret_override_values,
        _frozen_classes(_SECRET_REVISION_GLOB, "sep"),
    )

    assert decrypt(_stored(engine)[(SETTINGS_TOKEN, "PMM")]["api_key"]) == PMM_API_KEY


def test_frozen_replicas_never_enter_live_subclass_discovery() -> None:
    """Assert importing every revision leaves ``_candidate_models`` unaffected.

    Loading a revision executes it, which is what makes the risk real: the
    replicas are created at import time, and the walker resolves a polymorphic
    position such as ``set[BaseAlertProvider]`` by recursing through
    ``__subclasses__()``. A replica that inherited a live provider would join
    that walk and could answer for a stored key the live models do not declare.
    Subclassing :class:`~pydantic.BaseModel` directly is what prevents it, so
    that is what is asserted — the base list, not merely its consequence for one
    polymorphic position. A replica spelled ``class _FrozenPMM(PMMSettings)``
    would satisfy the ``BaseAlertProvider`` check below while joining the walk
    for ``Settings.PMM``.
    """
    replicas = {
        replica
        for glob in (_SECRET_REVISION_GLOB, _CREDENTIAL_URL_REVISION_GLOB)
        for track in _TRACKS
        for replica in _replica_classes(glob, track)
    }

    reached = _candidate_models([BaseAlertProvider])

    assert replicas, "the check is vacuous if no revision defines a replica"
    assert reached, "the check is vacuous if the base reaches no provider model"
    for replica in replicas:
        assert replica.__bases__ == (BaseModel,), (
            f"{replica.__name__} inherits a live model and would join its subclass walk"
        )
    assert not replicas.intersection(reached)
