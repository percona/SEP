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

"""Define tests for the pure restore spec builder."""

import pytest
import yaml

from app.core.utils.path import resolve_payload_reference
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.payload_variants import (
    CANONICAL_PAYLOAD_NAME,
    selections,
    variant_name,
)
from app.sep.apps.mysql_backups.restore.models import RestoreCreate
from app.sep.apps.mysql_backups.restore.spec import (
    build_restore_spec,
    RestoreResolved,
)
from app.tasks.models import TaskBackendEnum, TaskWrite

_PAYLOAD_DIR_BY_TYPE = {
    BackupType.MYDUMPER: "mydumper_payload",
    BackupType.XTRABACKUP: "xtrabackup_payload",
    BackupType.BINLOG: "binlog_payload",
}


def _form(backup_type: BackupType) -> RestoreCreate:
    return RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        backup_type=backup_type,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )


@pytest.mark.parametrize(
    "backup_type",
    [BackupType.MYDUMPER, BackupType.XTRABACKUP, BackupType.BINLOG],
)
def test_build_restore_spec_selects_payload_and_envelope(backup_type: BackupType):
    """Select the payload dir and a proxy restore envelope per backup type."""
    spec = build_restore_spec(_form(backup_type), RestoreResolved())

    assert isinstance(spec, TaskWrite)
    assert spec.name == "restore-task"
    assert spec.owner == "RESTORES"
    assert spec.backend == TaskBackendEnum.PROXY
    assert spec.data["task"] == "run-python"
    assert spec.data["payload"].endswith(f"/{_PAYLOAD_DIR_BY_TYPE[backup_type]}")
    assert spec.data["meta"]["target"] == "restore-host"
    assert "_service_name" not in spec.data["meta"]
    assert list(spec.data["meta"].keys()) == ["config", "target", "requirements"]


def test_build_restore_spec_xtrabackup_requires_filelock():
    """Append the ``filelock`` requirement only for the XtraBackup payload."""
    xtrabackup = build_restore_spec(_form(BackupType.XTRABACKUP), RestoreResolved())
    mydumper = build_restore_spec(_form(BackupType.MYDUMPER), RestoreResolved())

    assert "filelock" in xtrabackup.data["meta"]["requirements"]
    assert "filelock" not in mydumper.data["meta"]["requirements"]


def test_build_restore_spec_injects_resolved_destination_and_service_name():
    """Apply resolved host/port/database and service name to the config and meta."""
    resolved = RestoreResolved(
        service_name="db-prod",
        dest_host="10.0.0.5",
        dest_port=3307,
        database="shop",
    )
    spec = build_restore_spec(_form(BackupType.MYDUMPER), resolved)

    server = yaml.safe_load(spec.data["meta"]["config"])["SERVER_LIST"][0]
    assert server["DEST_HOST"] == resolved.dest_host
    assert server["DEST_PORT"] == resolved.dest_port
    assert server["DATABASE"] == resolved.database
    assert spec.data["meta"]["_service_name"] == resolved.service_name
    assert list(spec.data["meta"].keys()) == [
        "config",
        "target",
        "requirements",
        "_service_name",
    ]


class TestRestoreUsesTheCanonicalPayload:
    """Assert a restore always dispatches the all-providers payload, by name and on disk.

    A restore may have to reach any provider, so it is deliberately not
    variant-selected. Spelling the filename here as a literal would let a rename of
    the canonical pass every generator test and fail at Nomad dispatch instead, since
    the restore spec does no existence check of its own.
    """

    def test_xtrabackup_restore_names_the_canonical_payload(self) -> None:
        """Assert the mapping reads the shared constant, not a second copy of the name."""
        spec = build_restore_spec(_form(BackupType.XTRABACKUP), RestoreResolved())
        assert spec.data["payload"].endswith(f"/{CANONICAL_PAYLOAD_NAME}")

    @pytest.mark.parametrize(
        "backup_type",
        [BackupType.MYDUMPER, BackupType.XTRABACKUP, BackupType.BINLOG],
    )
    def test_restore_payload_exists_on_disk(self, backup_type: BackupType) -> None:
        """Assert each restore payload reference resolves to a file that ships."""
        spec = build_restore_spec(_form(backup_type), RestoreResolved())
        assert resolve_payload_reference(spec.data["payload"]).is_file()

    def test_restore_is_not_variant_selected(self) -> None:
        """Assert no upload-selection variant is ever dispatched for a restore."""
        spec = build_restore_spec(_form(BackupType.XTRABACKUP), RestoreResolved())
        stripped = {
            variant_name(providers)
            for providers in selections()
            if variant_name(providers) != CANONICAL_PAYLOAD_NAME
        }
        assert spec.data["payload"].rsplit("/", 1)[-1] not in stripped
