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

"""Tests for the backup_mongo response models rebased onto BaseTaskResponse."""

import pytest
from pydantic import ValidationError

from app.sep.apps.backup_mongo.models import (
    BackupCreate,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    BackupTaskWrite,
    BackupType,
    parse_backup_priority,
)
from app.sep.apps.framework import BaseTaskResponse
from app.tasks.models import TaskBackendEnum, TaskOwner

# A well-formed multi-line block mapping of node -> priority.
_VALID_PRIORITY_YAML = '"h1:27018": 2\n"h2:27018": 1'
# The reporter's repro: every mapping crammed onto a single line (invalid YAML).
_SINGLE_LINE_PRIORITY_YAML = '"h1:27018": 2 "h2:27018": 2'


def _backup_create(**overrides: object) -> BackupCreate:
    """Build a minimal valid BackupCreate with the given field overrides."""
    return BackupCreate(
        task_name="mongo-backup-task",
        hostname="mongo-host",
        service_id=1,
        backup_type=BackupType.PBM_CONFIG,
        storage_type="filesystem",
        storage_filesystem_path="/var/backups/mongo",
        pitr_compression="snappy",
        **overrides,
    )


def _backup_write(**overrides: object) -> BackupTaskWrite:
    """Build a minimal valid BackupTaskWrite with the given field overrides."""
    return BackupTaskWrite(
        task_name="mongo-backup-task",
        hostname="mongo-host",
        service_id=1,
        storage_type="filesystem",
        storage_filesystem_path="/var/backups/mongo",
        pitr_compression="snappy",
        **overrides,
    )


class TestParseBackupPriority:
    """Cover the shared ``parse_backup_priority`` helper."""

    def test_parses_block_mapping_to_floats(self) -> None:
        """Return a node -> float mapping from a valid block mapping."""
        assert parse_backup_priority(_VALID_PRIORITY_YAML) == {
            "h1:27018": 2.0,
            "h2:27018": 1.0,
        }

    def test_parses_flow_mapping(self) -> None:
        """Accept a YAML flow mapping."""
        assert parse_backup_priority('{"h1:27018": 2}') == {"h1:27018": 2.0}

    def test_rejects_invalid_yaml(self) -> None:
        """Raise ValueError on the single-line repro (invalid YAML)."""
        with pytest.raises(ValueError, match="valid YAML"):
            parse_backup_priority(_SINGLE_LINE_PRIORITY_YAML)

    @pytest.mark.parametrize("value", ["just text", "42", "- a\n- b"])
    def test_rejects_non_mapping(self, value: str) -> None:
        """Raise ValueError when the YAML is not a mapping."""
        with pytest.raises(ValueError, match="mapping"):
            parse_backup_priority(value)

    def test_rejects_non_numeric_value(self) -> None:
        """Raise ValueError when a priority value is not numeric."""
        with pytest.raises(ValueError, match="number"):
            parse_backup_priority('"h1:27018": high')

    def test_accepts_float_value(self) -> None:
        """Preserve a fractional priority as a float."""
        assert parse_backup_priority('"h1:27018": 2.5') == {"h1:27018": 2.5}

    def test_rejects_null_value(self) -> None:
        """Raise ValueError on a YAML null priority value."""
        with pytest.raises(ValueError, match="number"):
            parse_backup_priority('"h1:27018": null')

    @pytest.mark.parametrize("value", ['"h1:27018": {"a": 1}', '"h1:27018": [1, 2]'])
    def test_rejects_collection_value(self, value: str) -> None:
        """Raise ValueError when a priority value is a mapping or list."""
        with pytest.raises(ValueError, match="number"):
            parse_backup_priority(value)

    @pytest.mark.parametrize("value", ["{}", "  "])
    def test_rejects_empty_mapping(self, value: str) -> None:
        """Raise ValueError on a present-but-empty mapping (would be silently dropped)."""
        with pytest.raises(ValueError, match="empty|mapping"):
            parse_backup_priority(value)

    def test_rejects_bool_value(self) -> None:
        """Raise ValueError on a boolean value (float(True) would be 1.0)."""
        with pytest.raises(ValueError, match="number"):
            parse_backup_priority('"h1:27018": true')


class TestBackupPriorityValidation:
    """Validate that both create models enforce Node Priority YAML checks."""

    @pytest.mark.parametrize("factory", [_backup_create, _backup_write])
    def test_accepts_valid_block_mapping(self, factory) -> None:
        """Construct with a valid mapping and preserve the raw string."""
        model = factory(backup_priority=_VALID_PRIORITY_YAML)
        assert model.backup_priority == _VALID_PRIORITY_YAML

    @pytest.mark.parametrize("factory", [_backup_create, _backup_write])
    def test_accepts_flow_mapping(self, factory) -> None:
        """Accept a YAML flow mapping."""
        model = factory(backup_priority='{"h1:27018": 2}')
        assert model.backup_priority == '{"h1:27018": 2}'

    @pytest.mark.parametrize("factory", [_backup_create, _backup_write])
    def test_rejects_single_line_repro(self, factory) -> None:
        """Reject the single-line repro with a validation error."""
        with pytest.raises(ValidationError):
            factory(backup_priority=_SINGLE_LINE_PRIORITY_YAML)

    @pytest.mark.parametrize("factory", [_backup_create, _backup_write])
    @pytest.mark.parametrize("value", ["just text", "- a\n- b"])
    def test_rejects_non_mapping(self, factory, value: str) -> None:
        """Reject non-mapping YAML with a validation error."""
        with pytest.raises(ValidationError):
            factory(backup_priority=value)

    @pytest.mark.parametrize("factory", [_backup_create, _backup_write])
    def test_rejects_non_numeric_value(self, factory) -> None:
        """Reject a non-numeric priority value with a validation error."""
        with pytest.raises(ValidationError):
            factory(backup_priority='"h1:27018": high')

    @pytest.mark.parametrize("factory", [_backup_create, _backup_write])
    def test_rejects_bool_value(self, factory) -> None:
        """Reject a boolean priority value with a validation error."""
        with pytest.raises(ValidationError):
            factory(backup_priority='"h1:27018": true')

    @pytest.mark.parametrize("factory", [_backup_create, _backup_write])
    def test_rejects_empty_mapping(self, factory) -> None:
        """Reject a present-but-empty mapping so it is never silently dropped."""
        with pytest.raises(ValidationError):
            factory(backup_priority="{}")

    @pytest.mark.parametrize("factory", [_backup_create, _backup_write])
    def test_empty_string_becomes_none(self, factory) -> None:
        """Treat an empty string as no priority (None), never validated."""
        model = factory(backup_priority="")
        assert model.backup_priority is None


class TestBackupMongoResponseModels:
    """Tests for the backup_mongo response models inheriting ``BaseTaskResponse``."""

    def test_response_exposes_inherited_task_response_surface(self) -> None:
        """Carry the shared anonymization and connectivity surface from the base."""
        response = BackupTaskResponse(
            name="mongo-backup",
            owner=TaskOwner.BACKUP_MONGO,
            hostname="mongo-host",
            backend=TaskBackendEnum.PROXY,
            backup_type=BackupType.PBM_LOGICAL.value,
            data={"meta": {"target": "mongo-host"}},
            protected=False,
            alert_on_fail=False,
        )

        dumped = response.model_dump(mode="json")

        assert isinstance(response, BaseTaskResponse)
        assert dumped["backup_type"] == BackupType.PBM_LOGICAL.value
        assert dumped["hostname"] == "mongo-host"
        assert dumped["service_type"] is None
        assert "anonymize_mask" in dumped
        assert "anonymized_entities" in dumped
        assert "connectivity_warning" in dumped

    def test_detail_response_inherits_surface_and_keeps_extras(self) -> None:
        """Keep the derived-task extras while inheriting the base response surface."""
        detail = BackupTaskDetailResponse(
            name="mongo-backup",
            owner=TaskOwner.BACKUP_MONGO,
            backend=TaskBackendEnum.PROXY,
            backup_type=BackupType.PBM_CONFIG.value,
            data={},
            protected=False,
            alert_on_fail=False,
        )

        dumped = detail.model_dump(mode="json")

        assert isinstance(detail, BaseTaskResponse)
        assert detail.derived_tasks == []
        assert detail.latest_pbm_status is None
        assert dumped["connectivity_warning"] is None
        assert "anonymize_mask" in dumped
        assert "anonymized_entities" in dumped
