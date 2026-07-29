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

"""Unit tests for the pure restore spec builders (no API mocks)."""

import yaml

from app.sep.apps.backup_mongo.models import BackupType
from app.sep.apps.backup_mongo.restore.models import RestoreCreate
from app.sep.apps.backup_mongo.restore.spec import (
    build_restore_payloads,
    RESTORE_CONFIG_PAYLOAD_MARKER,
)

PARENT_NAME = "mongo-restore"


def _form(
    backup_type: BackupType = BackupType.PBM_LOGICAL, **overrides: object
) -> RestoreCreate:
    """Build a RestoreCreate for the given backup type with field overrides."""
    return RestoreCreate(
        task_name=PARENT_NAME,
        hostname="mongo-host",
        backup_type=backup_type,
        backup_source="2025-12-15T19:04:05Z",
        **overrides,
    )


def test_logical_restore_builds_three_legs_without_force_resync():
    """Build config, restore, and pbm-list legs for a logical restore without force-resync."""
    payloads = build_restore_payloads(_form(), service_name=None)

    assert payloads.config_task.name == PARENT_NAME
    assert payloads.restore_task.name == f"{PARENT_NAME}-{BackupType.PBM_LOGICAL.value}"
    assert payloads.pbm_list_task.name == f"{PARENT_NAME}-pbm-list"
    assert payloads.force_resync_task is None


def test_physical_restore_adds_force_resync_leg():
    """Add the force-resync child leg for a physical restore."""
    payloads = build_restore_payloads(_form(BackupType.PBM_PHYSICAL), service_name=None)

    assert payloads.force_resync_task is not None
    assert payloads.force_resync_task.name == f"{PARENT_NAME}-pbm-force-resync"
    assert (
        payloads.restore_task.name == f"{PARENT_NAME}-{BackupType.PBM_PHYSICAL.value}"
    )


def test_logical_restore_threads_namespace_to_execution_leg():
    """Serialize a namespace filter into the logical restore execution leg."""
    payloads = build_restore_payloads(
        _form(restore_namespace_filter="db1.*,db2.collection"),
        service_name=None,
    )

    assert yaml.safe_load(payloads.restore_task.data["meta"]["config"]) == {
        "backupSource": "2025-12-15T19:04:05Z",
        "backupType": "pbm_logical",
        "namespace": "db1.*,db2.collection",
    }
    assert "namespace" not in yaml.safe_load(
        payloads.config_task.data["meta"]["config"]
    )


def test_empty_namespace_keeps_execution_leg_config_unchanged():
    """Keep the bare logical restore execution YAML byte-identical."""
    payloads = build_restore_payloads(
        _form(restore_namespace_filter=""),
        service_name=None,
    )

    assert (
        payloads.restore_task.data["meta"]["config"]
        == "backupSource: '2025-12-15T19:04:05Z'\nbackupType: pbm_logical\n"
    )


def test_child_legs_carry_parent_and_config_leg_does_not():
    """Carry data['parent'] on each child leg but not on the parent config leg."""
    payloads = build_restore_payloads(_form(BackupType.PBM_PHYSICAL), service_name=None)

    assert "parent" not in payloads.config_task.data
    assert payloads.restore_task.data["parent"] == PARENT_NAME
    assert payloads.pbm_list_task.data["parent"] == PARENT_NAME
    assert payloads.force_resync_task.data["parent"] == PARENT_NAME


def test_config_leg_uses_marker_payload_and_restore_owner():
    """Use the restore-config payload marker and RESTORE_MONGO owner on the config leg."""
    payloads = build_restore_payloads(_form(), service_name=None)

    assert payloads.config_task.data["payload"].endswith(RESTORE_CONFIG_PAYLOAD_MARKER)
    assert payloads.config_task.owner == "RESTORE_MONGO"


def test_service_name_is_threaded_to_every_leg():
    """Add a resolved service name to every leg's meta as _service_name."""
    payloads = build_restore_payloads(
        _form(BackupType.PBM_PHYSICAL), service_name="mongo-svc"
    )

    for task in (
        payloads.config_task,
        payloads.restore_task,
        payloads.pbm_list_task,
        payloads.force_resync_task,
    ):
        assert task.data["meta"]["_service_name"] == "mongo-svc"
        assert list(task.data["meta"].keys()) == [
            "config",
            "target",
            "requirements",
            "_service_name",
        ]


def test_no_service_name_when_unresolved():
    """Omit the _service_name meta key from every leg when no service resolved."""
    payloads = build_restore_payloads(_form(), service_name=None)

    assert "_service_name" not in payloads.config_task.data["meta"]
    assert "_service_name" not in payloads.restore_task.data["meta"]
    assert list(payloads.config_task.data["meta"].keys()) == [
        "config",
        "target",
        "requirements",
    ]
