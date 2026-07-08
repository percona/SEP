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

from app.sep.apps.backup_mongo.models import (
    BackupTaskDetailResponse,
    BackupTaskResponse,
    BackupType,
)
from app.sep.apps.framework import BaseTaskResponse
from app.tasks.models import TaskBackendEnum


class TestBackupMongoResponseModels:
    """Tests for the backup_mongo response models inheriting ``BaseTaskResponse``."""

    def test_response_exposes_inherited_task_response_surface(self) -> None:
        """Carry the shared anonymization and connectivity surface from the base."""
        response = BackupTaskResponse(
            name="mongo-backup",
            owner="BACKUP_MONGO",
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
            owner="BACKUP_MONGO",
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
