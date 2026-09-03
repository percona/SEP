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

"""Tests for the mysql_backups legacy form reconstructor."""

from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_backfill import _backfill_single_task
from app.sep.apps.framework.form_backfill_inventory import ServiceIdLookup
from app.sep.apps.framework.form_backfill_registry import FormBackfillContext
from app.sep.apps.framework.spec import RESERVED_FORM_KEY
from app.sep.apps.mysql_backups.form_backfill import (
    _extract_upload_from_meta,
    FORM_BACKFILL_ENTRIES,
    reconstruct_mysql_backups_form,
    repair_mysql_backups_stamp,
)
from app.sep.apps.mysql_backups.forms import BackupCreate, EncryptionFormat
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.payload_variants import PROVIDERS
from app.sep.connectivity import CONNECTIVITY_META_HOST_KEY, CONNECTIVITY_META_PORT_KEY
from app.tasks.models import Task, TaskBackendEnum


def _service(
    service_id: int,
    *,
    name: str,
    address: str,
    port: int | None,
) -> SimpleNamespace:
    """Build a minimal inventory service record for lookup tests."""
    return SimpleNamespace(
        id=service_id,
        type=ServiceTypeEnum.MYSQL,
        name=name,
        port=port,
        node=SimpleNamespace(address=address),
    )


def _lookup(*services: SimpleNamespace) -> ServiceIdLookup:
    """Build a lookup table from the supplied service records."""
    return ServiceIdLookup.from_services(services)


def _ctx(lookup: ServiceIdLookup) -> FormBackfillContext:
    """Return a backfill context wired to ``lookup``."""
    return FormBackfillContext(
        log=__import__("logging").getLogger("test"), service_lookup=lookup
    )


# The stamp repairer derives everything from the stamp itself, so neither of these
# is read; they exist only to satisfy its signature.
_TASK = None
_CTX = None


def _legacy_mysql_backup_task(
    *,
    name: str = "mysql-backup-legacy",
    target: str = "executor-1",
    alias: str = "db1-mysql",
    service_host: str = "10.0.0.5",
    service_port: int = 3306,
    service_name: str = "mysql-prod",
    backup_type: BackupType = BackupType.XTRABACKUP,
    upload: list[str] | None = None,
    all_servers: dict[str, object] | None = None,
    server_extra: dict[str, object] | None = None,
    alert_on_fail: bool = False,
) -> Task:
    """Build a legacy mysql_backups task row without ``data['_form']``."""
    server_list_entry: dict[str, object] = {
        "ALIAS": alias,
        "HOST": service_host,
        "PORT": service_port,
        "BACKUP_TYPE": backup_type.value,
        **(server_extra or {}),
    }
    if upload is not None:
        server_list_entry["UPLOAD"] = upload
    all_servers_config = all_servers or {}
    return Task(
        name=name,
        data={
            "task": "run-python",
            "meta": {
                "target": target,
                CONNECTIVITY_META_HOST_KEY: service_host,
                CONNECTIVITY_META_PORT_KEY: service_port,
                "_service_name": service_name,
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [server_list_entry],
                        "ALL_SERVERS": all_servers_config,
                    }
                ),
            },
            "payload": "file://app/sep/apps/mysql_backups/payload",
        },
        backend=TaskBackendEnum.PROXY,
        owner="BACKUPS",
        alert_on_fail=alert_on_fail,
    )


def test_extract_upload_from_meta_normalizes_providers():
    """Normalize mixed-case upload provider names from persisted YAML."""
    meta = {
        "config": yaml.dump(
            {
                "SERVER_LIST": [
                    {
                        "HOST": "10.0.0.5",
                        "BACKUP_TYPE": BackupType.BINLOG.value,
                        "UPLOAD": ["gsutil", "S3"],
                    }
                ]
            }
        )
    }

    assert _extract_upload_from_meta(meta) == ["gsutil", "s3"]


def test_reconstruct_mysql_backups_form_happy_path():
    """Rebuild a create body and omit parse-only keys."""
    expected_service_id = 7
    lookup = _lookup(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_mysql_backup_task(
        upload=["S3"],
        all_servers={
            "S3_BUCKET": "my-bucket",
            "XTRABACKUP_QUIET": True,
            "BACKUP_DIR": "/backup",
        },
        alert_on_fail=True,
    )

    body = reconstruct_mysql_backups_form(task, _ctx(lookup))

    assert body is not None
    assert body["task_name"] == "mysql-backup-legacy"
    assert body["hostname"] == "executor-1"
    assert body["service_id"] == expected_service_id
    assert body["backup_type"] == BackupType.XTRABACKUP.value
    assert body["alias"] == "db1-mysql"
    assert body["upload"] == ["s3"]
    assert body["s3_bucket"] == "my-bucket"
    assert body["xtrabackup_quiet"] is True
    assert body["backup_dir"] == "/backup"
    assert body["alert_on_fail"] is True
    assert "host" not in body
    assert "port" not in body
    assert "name" not in body
    BackupCreate.model_validate(body)


def test_reconstruct_mysql_backups_form_binlog_alternative_host():
    """Round-trip binlog-specific fields from persisted YAML."""
    expected_service_id = 2
    lookup = _lookup(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_mysql_backup_task(
        backup_type=BackupType.BINLOG,
        upload=["GSUTIL"],
        all_servers={
            "BINLOG_ALTERNATIVE_HOST": "10.0.0.9",
            "BINLOG_PREFIX": "binlog",
            "GS_BUCKET": "gs-bucket",
        },
    )

    body = reconstruct_mysql_backups_form(task, _ctx(lookup))

    assert body is not None
    assert body["backup_type"] == BackupType.BINLOG.value
    assert body["binlog_alternative_host"] == "10.0.0.9"
    assert body["binlog_prefix"] == "binlog"
    assert body["gs_bucket"] == "gs-bucket"
    assert body["upload"] == ["gsutil"]
    BackupCreate.model_validate(body)


def test_reconstruct_mysql_backups_form_mydumper_happy_path():
    """Round-trip mydumper-specific fields from persisted YAML."""
    expected_service_id = 3
    lookup = _lookup(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_mysql_backup_task(
        backup_type=BackupType.MYDUMPER,
        upload=["GSUTIL"],
        all_servers={
            "MYDUMPER_VERBOSE": 1,
            "MYDUMPER_EXTRA_ARGS": "--foo",
            "GS_BUCKET": "gs-bucket",
        },
    )

    body = reconstruct_mysql_backups_form(task, _ctx(lookup))

    assert body is not None
    assert body["backup_type"] == BackupType.MYDUMPER.value
    assert body["mydumper_verbose"] == 1
    assert body["mydumper_extra_args"] == "--foo"
    assert body["gs_bucket"] == "gs-bucket"
    assert body["upload"] == ["gsutil"]
    BackupCreate.model_validate(body)


def test_reconstruct_mysql_backups_form_returns_none_when_not_run_python():
    """Skip tasks that are not ``run-python`` backup rows."""
    lookup = _lookup(
        _service(1, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_mysql_backup_task()
    task.data["task"] = "run-command"

    assert reconstruct_mysql_backups_form(task, _ctx(lookup)) is None


def test_reconstruct_mysql_backups_form_returns_none_when_service_unresolved():
    """Skip tasks whose database host cannot be matched in inventory."""
    lookup = _lookup(
        _service(1, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_mysql_backup_task(
        service_host="10.0.0.9",
        service_name="unknown-service",
        upload=["S3"],
        all_servers={"S3_BUCKET": "bucket"},
    )

    assert reconstruct_mysql_backups_form(task, _ctx(lookup)) is None


def test_backfill_single_task_stamps_mysql_backups_form():
    """Run the orchestrator pipeline for a reconstructable mysql_backups task."""
    expected_service_id = 9
    lookup = _lookup(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_mysql_backup_task(
        name="mysql-stamp",
        upload=["RSYNC"],
        all_servers={"RSYNC_PATH": "/remote/backups"},
    )
    entry = FORM_BACKFILL_ENTRIES[0]
    ctx = FormBackfillContext(
        log=__import__("logging").getLogger("test"),
        service_lookup=lookup,
    )

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "stamped"
    assert outcome.stamped_data is not None
    stamped_form = outcome.stamped_data[RESERVED_FORM_KEY]
    assert stamped_form["task_name"] == "mysql-stamp"
    assert stamped_form["service_id"] == expected_service_id
    assert stamped_form["backup_type"] == BackupType.XTRABACKUP.value
    assert stamped_form["upload"] == ["rsync"]
    assert stamped_form["rsync_path"] == "/remote/backups"


class TestUploadBackfillDropsNothingSilently:
    """Assert reconstruction never narrows a legacy task's upload selection unnoticed.

    The reconstructed ``upload`` list chooses which payload variant a backfilled
    task dispatches. A provider spelling the alias map does not know is dropped, so
    the task would silently dispatch a variant that cannot reach it.
    """

    @staticmethod
    def _meta(upload: list[str]) -> dict[str, str]:
        """Return a task meta carrying ``upload`` in its persisted config.

        :param upload: The provider spellings the stored config records.
        :return: The meta dict the extractor reads.
        """
        return {
            "config": yaml.dump(
                {
                    "SERVER_LIST": [
                        {
                            "HOST": "10.0.0.5",
                            "BACKUP_TYPE": BackupType.XTRABACKUP.value,
                            "UPLOAD": upload,
                        }
                    ]
                }
            )
        }

    def test_every_canonical_spelling_survives(self) -> None:
        """Assert the provider names the dispatcher writes all round-trip."""
        extracted = _extract_upload_from_meta(self._meta(list(PROVIDERS)))
        assert sorted(extracted) == sorted(PROVIDERS)

    def test_the_documented_legacy_alias_is_not_dropped(self) -> None:
        """Assert ``GS``, the spelling the payload's own docstring documents, maps through.

        Dropping it reconstructs an empty selection, which dispatches the no-upload
        variant for a task that was uploading to Google Cloud Storage.
        """
        assert _extract_upload_from_meta(self._meta(["GS"])) == ["gsutil"]

    def test_an_unknown_provider_is_not_dropped(self) -> None:
        """Assert an unmapped spelling does not quietly narrow the selection."""
        stored = ["rsync", "azure"]
        extracted = _extract_upload_from_meta(self._meta(stored))
        assert "rsync" in extracted
        assert len(extracted) == len(stored), extracted

    def test_an_unknown_provider_fails_form_validation(self) -> None:
        """Assert the form rejects the passed-through spelling rather than accepting it.

        Passing an unmapped spelling through is only an improvement on dropping it if
        something downstream refuses it: ``_run_task_backfill`` logs the errors and
        reports the task as ``skipped_invalid``, so it stays legacy instead of being
        stamped with a selection that dispatches a variant it cannot reach. Pinning
        the error location to the offending element keeps a missing provider gate
        from passing this test for the wrong reason.
        """
        extracted = _extract_upload_from_meta(self._meta(["rsync", "azure"]))
        with pytest.raises(ValidationError) as excinfo:
            BackupCreate.model_validate(
                {
                    "task_name": "backups-legacy",
                    "hostname": "executor-host",
                    "service_id": 1,
                    "backup_type": BackupType.XTRABACKUP.value,
                    "upload": extracted,
                    "rsync_path": "/data/rsync",
                }
            )
        assert [error["loc"] for error in excinfo.value.errors()] == [
            ("upload", extracted.index("azure"))
        ]


class TestEncryptionFormatBackfill:
    """Reconstruct the encryption format of tasks stamped before it existed.

    A legacy task's encryption lived only in the fields the payload happened to
    read. Stamping a form that lost that state would let the next save turn an
    encrypted backup into a plaintext one, so each state has to survive the round
    trip — or be refused outright when it cannot.
    """

    # The shape the create path actually stores: ``BackupConfigServer`` uppercases
    # the outer key and ``DirEncryptConfig`` renames the recipient to the spelling
    # the directory encryptor reads.
    _RECIPIENT_BLOCK = {
        "DIR_ENCRYPT_CONFIG": {"encryption recipient": "ops@example.com"}
    }

    @staticmethod
    def _backfill(
        all_servers: dict[str, object],
        server_extra: dict[str, object] | None = None,
    ):
        service_id = 9
        lookup = _lookup(
            _service(service_id, name="mysql-prod", address="10.0.0.5", port=3306),
        )
        task = _legacy_mysql_backup_task(
            name="mysql-encrypted",
            upload=["RSYNC"],
            all_servers={"RSYNC_PATH": "/remote/backups", **all_servers},
            server_extra=server_extra,
        )
        return _backfill_single_task(task, FORM_BACKFILL_ENTRIES[0], _ctx(lookup))

    def _stamped_form(
        self, *args: dict[str, object] | None, **kwargs: dict[str, object] | None
    ) -> dict:
        outcome = self._backfill(*args, **kwargs)
        assert outcome.label == "stamped"
        return outcome.stamped_data[RESERVED_FORM_KEY]

    def test_unencrypted_task_stamps_no_encryption(self):
        """Stamp an unencrypted task as ``none`` rather than inventing a format."""
        stamped_form = self._stamped_form({"ENCRYPT": False})
        assert stamped_form["encryption_format"] == EncryptionFormat.NONE

    def test_aes256_task_stamps_the_aes256_format(self):
        """Stamp an AES-256 task as ``aes256`` and keep its key file."""
        stamped_form = self._stamped_form(
            {"ENCRYPT": False, "XTRABACKUP_AES256_KEYFILE": "/keys/aes.key"}
        )
        assert stamped_form["encryption_format"] == EncryptionFormat.AES256
        assert stamped_form["xtrabackup_aes256_keyfile"] == "/keys/aes.key"

    def test_post_run_gpg_task_stamps_the_gpg_format(self):
        """Stamp a post-run GPG task as ``gpg`` with its timing intact."""
        stamped_form = self._stamped_form(
            {"ENCRYPT": False, "POST_RUN_ENCRYPT": True}, self._RECIPIENT_BLOCK
        )
        assert stamped_form["encryption_format"] == EncryptionFormat.GPG
        assert stamped_form["post_run_encrypt"] is True
        assert stamped_form["encryption_recipient"] == "ops@example.com"

    def test_dual_task_stamps_the_dual_format(self):
        """Stamp a task carrying both an AES-256 key file and GPG as ``dual``."""
        stamped_form = self._stamped_form(
            {
                "ENCRYPT": False,
                "POST_RUN_ENCRYPT": True,
                "XTRABACKUP_AES256_KEYFILE": "/keys/aes.key",
            },
            self._RECIPIENT_BLOCK,
        )
        assert stamped_form["encryption_format"] == EncryptionFormat.DUAL

    def test_gpg_task_without_a_recoverable_recipient_is_refused(self):
        """Refuse to stamp a GPG task whose recipient cannot be read back.

        The recipient is required by a GPG format, so a reconstruction that lost
        it is invalid. Being counted invalid leaves the task un-stamped and its
        encryption untouched, where stamping the form without the recipient — or
        with no format at all — would let the next save drop the encryption.
        """
        outcome = self._backfill({"ENCRYPT": False, "POST_RUN_ENCRYPT": True})
        assert outcome.label == "skipped_invalid"


class TestEncryptionFormatStampRepair:
    """Fill ``encryption_format`` into stamps written before the selector existed.

    These tasks were created through the schema form, so they already carry a
    ``_form`` and the legacy reconstruction never looks at them. Their stamp names
    the GPG timings and the key file but not the format, and the edit form fills
    that gap from the schema default — ``none`` — so an encrypted task reloads
    looking unencrypted.
    """

    @staticmethod
    def _stamp(**overrides: object) -> dict[str, object]:
        """Return a stamped create body with no ``encryption_format`` key."""
        return {
            "task_name": "mysql-encrypted",
            "hostname": "executor-1",
            "service_id": 9,
            "backup_type": BackupType.XTRABACKUP.value,
            "alias": "db1-mysql",
            "alert_on_fail": False,
            **overrides,
        }

    def _repair(self, **overrides: object) -> dict[str, object] | None:
        return repair_mysql_backups_stamp(self._stamp(**overrides), _TASK, _CTX)

    def _repaired_format(self, **overrides: object) -> EncryptionFormat:
        repaired = self._repair(**overrides)
        assert repaired is not None
        return repaired["encryption_format"]

    @pytest.mark.parametrize(
        ("stamped_fields", "expected"),
        [
            ({}, EncryptionFormat.NONE),
            ({"encrypt": True}, EncryptionFormat.GPG),
            ({"post_run_encrypt": True}, EncryptionFormat.GPG),
            (
                {"xtrabackup_aes256_keyfile": "/keys/aes.key"},
                EncryptionFormat.AES256,
            ),
            (
                {"encrypt": True, "xtrabackup_aes256_keyfile": "/keys/aes.key"},
                EncryptionFormat.DUAL,
            ),
        ],
    )
    def test_derives_the_format_the_stamp_already_implies(
        self, stamped_fields: dict[str, object], expected: EncryptionFormat
    ):
        """Derive each format from the fields the older stamp does carry."""
        assert self._repaired_format(**stamped_fields) == expected

    def test_a_key_file_off_xtrabackup_adds_no_aes_pass(self):
        """Ignore a key file on an engine with no AES-256 path.

        Deriving ``aes256`` there would write a format the task's own backup type
        rejects, so the repair could never validate and the stamp would stay
        broken.
        """
        assert (
            self._repaired_format(
                backup_type=BackupType.MYDUMPER.value,
                xtrabackup_aes256_keyfile="/keys/aes.key",
            )
            == EncryptionFormat.NONE
        )

    @pytest.mark.parametrize(
        "stored_format", [EncryptionFormat.NONE.value, EncryptionFormat.DUAL.value]
    )
    def test_a_stamp_naming_a_format_is_left_alone(self, stored_format: str):
        """Report nothing to repair once the stamp names a format.

        Including ``none``: an operator who chose it must not have it re-derived
        from a field an earlier config left behind.
        """
        assert (
            self._repair(
                encryption_format=stored_format,
                encrypt=True,
                xtrabackup_aes256_keyfile="/keys/aes.key",
            )
            is None
        )

    def test_the_repaired_stamp_validates_and_replaces_the_stored_one(self):
        """Run the repair through the orchestrator, not just the derivation.

        The derived format has to satisfy the form's own gates against the rest of
        the stored body — a format is only a repair if the create model accepts it.
        The body encrypts in place with no upload provider, the shape most of these
        stamps carry, so a gate demanding a target would leave them un-repaired.
        """
        task = _legacy_mysql_backup_task(name="mysql-encrypted")
        task.data[RESERVED_FORM_KEY] = self._stamp(
            encrypt=True, encryption_recipient="ops@example.com"
        )
        lookup = _lookup(
            _service(9, name="mysql-prod", address="10.0.0.5", port=3306),
        )

        outcome = _backfill_single_task(task, FORM_BACKFILL_ENTRIES[0], _ctx(lookup))

        assert outcome.label == "repaired"
        assert (
            outcome.stamped_data[RESERVED_FORM_KEY]["encryption_format"]
            == EncryptionFormat.GPG
        )
