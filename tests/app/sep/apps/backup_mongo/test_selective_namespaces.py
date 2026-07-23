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

"""Tests for selective backup namespace parsing and validation."""

import pytest
from pydantic import ValidationError

from app.sep.apps.backup_mongo.models import (
    BackupTaskWrite,
    parse_backup_namespaces,
    validate_selective_users_and_roles,
)


class TestParseBackupNamespaces:
    """Exercise ``parse_backup_namespaces`` shape rules."""

    def test_normalizes_whitespace(self) -> None:
        """Trim tokens and rejoin with commas."""
        assert parse_backup_namespaces(" db1.* , db2.coll ") == ["db1.*", "db2.coll"]

    def test_rejects_invalid_token(self) -> None:
        """Reject tokens that are not ``db.collection`` / ``db.*``."""
        with pytest.raises(ValueError, match="invalid"):
            parse_backup_namespaces("db1,db2.coll")


class TestUsersAndRolesGate:
    """Exercise ``--with-users-and-roles`` database-level gating."""

    def test_rejects_collection_level(self) -> None:
        """Reject users/roles when any namespace is a single collection."""
        with pytest.raises(ValueError, match="database-level"):
            validate_selective_users_and_roles("mydb.coll", with_users_and_roles=True)

    def test_accepts_database_level(self) -> None:
        """Allow users/roles when every namespace is ``db.*``."""
        validate_selective_users_and_roles("mydb.*,other.*", with_users_and_roles=True)


class TestBackupTaskWriteSelectiveValidation:
    """Assert create/edit request bodies reject invalid selective pairings."""

    def _body(self, **overrides: object) -> dict:
        base = {
            "task_name": "mongo-backup",
            "hostname": "mongo-host",
            "service_id": 1,
            "storage_type": "filesystem",
            "storage_filesystem_path": "/var/backups",
        }
        base.update(overrides)
        return base

    def test_accepts_db_level_with_users_and_roles(self) -> None:
        """Accept database-level namespaces with users/roles enabled."""
        body = BackupTaskWrite.model_validate(
            self._body(
                backup_namespaces="mydb.*",
                backup_with_users_and_roles=True,
            )
        )
        assert body.backup_namespaces == "mydb.*"
        assert body.backup_with_users_and_roles is True

    def test_rejects_collection_with_users_and_roles(self) -> None:
        """Reject users/roles when a collection-level namespace is present."""
        with pytest.raises(ValidationError):
            BackupTaskWrite.model_validate(
                self._body(
                    backup_namespaces="mydb.coll",
                    backup_with_users_and_roles=True,
                )
            )
