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

"""Freeze the byte-identity guardrail for the backups ``run-python`` payload.

Capture the full ``TaskWrite`` envelope produced by the model-first spec path
(``build_backup_spec`` + ``assemble_envelope``) across the three backup types and
their per-type host logic, and compare each against a committed golden. The
migration-era goldens were captured from the now-removed
``build_backup_task_payload_from_model`` and are cross-implementation evidence
the spec path reproduces the old builder byte-for-byte; later additions (the
encryption-mode cases) are self-captures of the code under test via
``assert_or_update`` — regression guards going forward, not cross-implementation
checks. The ``file://`` payload path is normalized to the package-relative anchor
so the golden is machine-independent (both the old builder and the new spec
compute the same ``Path(__file__).parent`` within the package).
"""

import pytest
import yaml

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.spec import assemble_envelope, ResolvedEntities
from app.sep.apps.mysql_backups.forms import BackupCreate
from app.sep.apps.mysql_backups.spec import build_backup_spec
from app.sep.inventory import CreatedService
from tests.app.factories import CreatedNodeFactory, CreatedServiceFactory
from tests.app.sep.snapshot_utils import assert_or_update, canonical_json, SNAPSHOTS_DIR

PAYLOAD_DIR = SNAPSHOTS_DIR / "payload"

_TASK_NAME = "backups-golden"
_HOSTNAME = "executor-host"
_PAYLOAD_ANCHOR = "app/sep/apps/mysql_backups/"

# Each case names a slug and the backups field values; the cases cover the three
# backup types, their per-type server host (M → service address, X → localhost,
# B → alternative host or service address), the requirements / payload-file
# selection, and every encryption format: GPG in its three timings (tmpdir,
# post-run with in-place on, post-run standalone with in-place off), AES-256, and
# the combined AES-256-plus-GPG selection.
_CASES = [
    {
        "slug": "mydumper_rsync",
        "form": {
            "backup_type": "M",
            "upload": ["RSYNC"],
            "rsync_path": "/data/rsync",
            "compression_algorithm": "gzip",
            "mydumper_verbose": 2,
            "alias": "primary",
        },
        "alert_on_fail": True,
    },
    {
        "slug": "xtrabackup_s3_encrypt",
        "form": {
            "backup_type": "X",
            "upload": ["S3"],
            "s3_bucket": "my-s3-bucket",
            "s3_storage_class": "STANDARD",
            "encryption_format": "gpg",
            "encrypt": True,
            "encryption_recipient": "ops@example.com",
            "compression_algorithm": "zstd",
            "xtrabackup_prepare": True,
        },
        "alert_on_fail": False,
    },
    {
        "slug": "mydumper_s3_encrypt_tmpdir",
        "form": {
            "backup_type": "M",
            "upload": ["S3"],
            "s3_bucket": "my-s3-bucket",
            "encryption_format": "gpg",
            "encrypt": True,
            "encrypt_using_tmpdir": True,
            "encryption_recipient": "ops@example.com",
        },
        "alert_on_fail": False,
    },
    {
        "slug": "mydumper_s3_encrypt_post_run",
        "form": {
            "backup_type": "M",
            "upload": ["S3"],
            "s3_bucket": "my-s3-bucket",
            "encryption_format": "gpg",
            "encrypt": True,
            "post_run_encrypt": True,
            "encryption_recipient": "ops@example.com",
        },
        "alert_on_fail": False,
    },
    {
        "slug": "mydumper_s3_post_run_only",
        "form": {
            "backup_type": "M",
            "upload": ["S3"],
            "s3_bucket": "my-s3-bucket",
            "encryption_format": "gpg",
            "post_run_encrypt": True,
            "encryption_recipient": "ops@example.com",
        },
        "alert_on_fail": False,
    },
    {
        "slug": "xtrabackup_s3_aes256",
        "form": {
            "backup_type": "X",
            "upload": ["S3"],
            "s3_bucket": "my-s3-bucket",
            "encryption_format": "aes256",
            "xtrabackup_aes256_keyfile": "/etc/percona/aes.key",
        },
        "alert_on_fail": False,
    },
    {
        "slug": "xtrabackup_s3_dual",
        "form": {
            "backup_type": "X",
            "upload": ["S3"],
            "s3_bucket": "my-s3-bucket",
            "encryption_format": "dual",
            "xtrabackup_aes256_keyfile": "/etc/percona/aes.key",
            "post_run_encrypt": True,
            "encryption_recipient": "ops@example.com",
        },
        "alert_on_fail": False,
    },
    {
        "slug": "binlog_gsutil_alt_host",
        "form": {
            "backup_type": "B",
            "upload": ["GSUTIL"],
            "gs_bucket": "my-gcs-bucket",
            "binlog_alternative_host": "binlog.internal",
            "compression_algorithm": "gzip",
        },
        "alert_on_fail": False,
    },
    {
        "slug": "binlog_rsync_no_alt",
        "form": {
            "backup_type": "B",
            "upload": ["RSYNC"],
            "rsync_path": "/data/binlog",
        },
        "alert_on_fail": False,
    },
]


def _service() -> CreatedService:
    """Return the deterministic inventory service the cases resolve against."""
    node = CreatedNodeFactory.build(address="db.internal", node_name="db-node")
    return CreatedServiceFactory.build(
        node=node,
        type=ServiceTypeEnum.MYSQL,
        name="svc-backups",
        port=3306,
    )


def _normalize(envelope: dict) -> dict:
    """Rewrite the absolute ``file://`` payload to the package-relative anchor."""
    payload = envelope["data"]["payload"]
    suffix = payload.split(_PAYLOAD_ANCHOR)[-1]
    envelope["data"]["payload"] = f"file://{_PAYLOAD_ANCHOR}{suffix}"
    return envelope


def _spec_envelope(service: CreatedService, case: dict) -> dict:
    """Return the model-first ``TaskWrite`` dump for ``case``."""
    resolved = ResolvedEntities(
        service=service,
        entities={"service_id": service},
        executor_host=_HOSTNAME,
    )
    form = BackupCreate(
        task_name=_TASK_NAME,
        hostname=_HOSTNAME,
        service_id=service.id,
        alert_on_fail=case["alert_on_fail"],
        **case["form"],
    )
    task = assemble_envelope(
        build_backup_spec(form, resolved),
        resolved,
        name=_TASK_NAME,
        owner="BACKUPS",
        alert_on_fail=case["alert_on_fail"],
    )
    return _normalize(task.model_dump())


def test_spec_path_payload_matrix_matches_golden():
    """Assert the model-first spec path reproduces the frozen envelope matrix."""
    service = _service()
    payloads = {case["slug"]: _spec_envelope(service, case) for case in _CASES}
    assert_or_update(
        PAYLOAD_DIR / "mysql_backups__spec_path.json", canonical_json(payloads)
    )


def _all_servers_config(
    backup_type: str, encryption: dict[str, object]
) -> dict[str, object]:
    """Return the ``ALL_SERVERS`` block of the YAML config ``build_backup_spec`` emits.

    :param backup_type: The ``BackupType`` code (``M``/``X``/``B``).
    :param encryption: The encryption fields to pass to the form, if any.
    """
    service = _service()
    resolved = ResolvedEntities(
        service=service,
        entities={"service_id": service},
        executor_host=_HOSTNAME,
    )
    form = BackupCreate(
        task_name=_TASK_NAME,
        hostname=_HOSTNAME,
        service_id=service.id,
        backup_type=backup_type,
        **encryption,
    )
    return yaml.safe_load(build_backup_spec(form, resolved).config)["ALL_SERVERS"]


@pytest.mark.parametrize("backup_type", ["M", "X", "B"])
@pytest.mark.parametrize(
    "encryption",
    [
        pytest.param(
            {
                "encryption_format": "gpg",
                "encrypt": True,
                "encryption_recipient": "ops@example.com",
            },
            id="encrypt_true",
        ),
        pytest.param({"encrypt": False}, id="encrypt_false"),
        pytest.param({}, id="encrypt_omitted"),
    ],
)
def test_build_backup_spec_always_emits_encrypt_key(backup_type: str, encryption: dict):
    """Pin that every generated config carries an explicit ``ENCRYPT`` key.

    Drives ``build_backup_spec`` directly for each backup type and for an
    ``encrypt=True`` form, an ``encrypt=False`` form, and a form built without any
    encryption fields, then asserts the serialised YAML always names ``ENCRYPT``
    with the form's value. This is the producer-side invariant the payload scripts
    rely on: they read ``settings.get("ENCRYPT", True)``, so a config that ever
    omitted the key would flip a stored backup from unencrypted to encrypted. The
    assertion fails if ``exclude_unset``/``exclude_defaults`` (which would drop the
    ``False`` default) is ever introduced into the builder.
    """
    all_servers = _all_servers_config(backup_type, encryption)
    assert "ENCRYPT" in all_servers
    assert all_servers["ENCRYPT"] is encryption.get("encrypt", False)
    assert all_servers["ENCRYPTION_FORMAT"] == encryption.get(
        "encryption_format", "none"
    )
