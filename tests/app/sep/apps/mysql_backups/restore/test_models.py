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

"""Define tests for the app.sep.apps.mysql_backups.restore.models module."""

import pytest
from pydantic import ValidationError

from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.models import RestoreConfigServer, RestoreCreate


def _minimal_restore_create_body(**overrides: object) -> dict:
    """Return a minimal valid :class:`RestoreCreate` payload."""
    body = {
        "task_name": "restore-1",
        "hostname": "executor-1",
        "backup_type": BackupType.MYDUMPER,
        "backup_source": "/var/backups/latest",
    }
    body.update(overrides)
    return body


def test_restore_create_coerces_int_reference_ids_to_str() -> None:
    """Accept JSON inventory ids as ints (React schema form) by stringifying."""
    model = RestoreCreate.model_validate(
        _minimal_restore_create_body(service_id=4, schema_id=11)
    )
    assert model.service_id == "4"
    assert model.schema_id == "11"


def test_restore_create_preserves_str_reference_ids() -> None:
    """Leave str-typed reference ids unchanged (Jinja / legacy form path)."""
    model = RestoreCreate.model_validate(
        _minimal_restore_create_body(service_id="4", schema_id="11")
    )
    assert model.service_id == "4"
    assert model.schema_id == "11"


def _server_with_backup_source(backup_source: str) -> dict:
    return {
        "alias": "a",
        "backup_type": BackupType.MYDUMPER,
        "backup_source": backup_source,
        "datadir": "/var/lib/mysql",
    }


@pytest.mark.parametrize(
    "backup_source",
    [
        "host:/backups/foo/latest",
        "/var/backups/latest",
        "10.0.0.1:/data/mysql_backup/latest",
    ],
)
def test_validate_backup_source_accepts_safe_paths(backup_source: str) -> None:
    """Accept typical host:path and local paths without shell metacharacters."""
    RestoreConfigServer.model_validate(_server_with_backup_source(backup_source))


@pytest.mark.parametrize(
    ("backup_source", "error_match"),
    [
        # Advisory PoC: host looks like latest symlink path; $(...) was evaluated by bash.
        ("$(id>/tmp/pwned):foo/latest", "shell metacharacters"),
        ("$(id)", "shell metacharacters"),
        ("`id`", "shell metacharacters"),
        ("host:/path;rm -rf /", "shell metacharacters"),
        ("a|b", "shell metacharacters"),
        ("a&b", "shell metacharacters"),
        ("a;b", "shell metacharacters"),
        ("foo$(bar)", "shell metacharacters"),
        ("bad\nline", "newline"),
        ("bad\rline", "newline"),
    ],
)
def test_validate_backup_source_rejects_unsafe_input(
    backup_source: str,
    error_match: str,
) -> None:
    """Reject newlines and shell metacharacters per field validator.

    Includes the documented restore-form PoC (``$(id>/tmp/pwned):foo/latest``), which
    previously led to command substitution in a shell-wrapped ``ssh`` invocation.
    """
    with pytest.raises(ValidationError, match=error_match):
        RestoreConfigServer.model_validate(_server_with_backup_source(backup_source))
