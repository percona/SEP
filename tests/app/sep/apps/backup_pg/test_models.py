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

"""Tests for the backup_pg create form and JSON API Pydantic models."""

import pytest
from pydantic import ValidationError

from app.sep.apps.backup_pg.models import (
    BackupPgForm,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    PgBackRestBackupType,
)
from app.sep.apps.framework import BaseTaskResponse
from app.tasks.models import TaskBackendEnum, TaskOwner

DEFAULT_PG_PORT = 5432
SAMPLE_BACKUP_DIR = "/var/lib/pgbackrest"


def test_backup_pg_form_accepts_minimal_payload() -> None:
    """Accept the minimal required fields."""
    body = BackupPgForm(
        task_name="pg-task",
        hostname="pg-host",
        service_id=1,
        backup_dir=SAMPLE_BACKUP_DIR,
        stanza="sep-test",
    )

    assert body.task_name == "pg-task"
    assert body.alert_on_fail is False


def test_backup_pg_form_rejects_missing_backup_dir() -> None:
    """``backup_dir`` is required: omitting it fails Pydantic validation."""
    with pytest.raises(ValidationError):
        BackupPgForm(
            task_name="pg-task",
            hostname="pg-host",
            service_id=1,
            stanza="sep-test",
        )


def test_backup_pg_form_rejects_empty_backup_dir() -> None:
    """``backup_dir`` is ``NonEmptyStr``; an empty string fails validation."""
    with pytest.raises(ValidationError):
        BackupPgForm(
            task_name="pg-task",
            hostname="pg-host",
            service_id=1,
            stanza="sep-test",
            backup_dir="",
        )


def test_backup_pg_form_rejects_extra_host_port_fields() -> None:
    """Reject ``host``/``port`` so silent drops surface as 422.

    The payload pins ``host="localhost"`` and uses ``service.port`` from the
    inventory lookup; accepting these fields would let a stale FE caller
    submit values that vanish.
    """
    with pytest.raises(ValidationError):
        BackupPgForm(
            task_name="pg-task",
            hostname="pg-host",
            service_id=1,
            backup_dir=SAMPLE_BACKUP_DIR,
            stanza="sep-test",
            host="x",
        )
    with pytest.raises(ValidationError):
        BackupPgForm(
            task_name="pg-task",
            hostname="pg-host",
            service_id=1,
            backup_dir=SAMPLE_BACKUP_DIR,
            stanza="sep-test",
            port=DEFAULT_PG_PORT,
        )


def test_backup_pg_form_rejects_empty_task_name() -> None:
    """Empty task_name fails Pydantic validation."""
    with pytest.raises(ValidationError):
        BackupPgForm(
            task_name="",
            hostname="pg-host",
            service_id=1,
            backup_dir=SAMPLE_BACKUP_DIR,
            stanza="sep-test",
        )


def test_backup_pg_form_accepts_pgbackrest_backup_type() -> None:
    """pgbackrest_backup_type accepts INCR or DIFF enum values."""
    body = BackupPgForm(
        task_name="pg-task",
        hostname="pg-host",
        service_id=1,
        backup_dir=SAMPLE_BACKUP_DIR,
        stanza="sep-test",
        pgbackrest_backup_type=PgBackRestBackupType.DIFF,
    )

    assert body.pgbackrest_backup_type is PgBackRestBackupType.DIFF


def test_backup_pg_form_coerces_blank_optionals_to_none() -> None:
    """Coerce empty-string optional fields to None (the HTML form path)."""
    body = BackupPgForm(
        task_name="pg-task",
        hostname="pg-host",
        service_id=1,
        backup_dir=SAMPLE_BACKUP_DIR,
        stanza="sep-test",
        pgbackrest_bin="",
        pgbackrest_backup_type="",
        pgbackrest_retention_full="",
    )

    assert body.pgbackrest_bin is None
    assert body.pgbackrest_backup_type is None
    assert body.pgbackrest_retention_full is None


def test_backup_pg_form_strips_stanza_whitespace() -> None:
    """Stanza trims surrounding whitespace."""
    body = BackupPgForm(
        task_name="pg-task",
        hostname="pg-host",
        service_id=1,
        backup_dir=SAMPLE_BACKUP_DIR,
        stanza="  sep-test  ",
    )

    assert body.stanza == "sep-test"


@pytest.mark.parametrize("invalid_stanza", ["../sep", "sep/test", "sep.test", "_sep"])
def test_backup_pg_form_rejects_unsafe_stanza(invalid_stanza: str) -> None:
    """Stanza only allows [A-Za-z0-9][A-Za-z0-9_-]*."""
    with pytest.raises(ValidationError):
        BackupPgForm(
            task_name="pg-task",
            hostname="pg-host",
            service_id=1,
            backup_dir=SAMPLE_BACKUP_DIR,
            stanza=invalid_stanza,
        )


def test_backup_pg_form_rejects_unknown_pgbackrest_backup_type() -> None:
    """Non-enum pgbackrest_backup_type values are rejected."""
    with pytest.raises(ValidationError):
        BackupPgForm(
            task_name="pg-task",
            hostname="pg-host",
            service_id=1,
            backup_dir=SAMPLE_BACKUP_DIR,
            stanza="sep-test",
            pgbackrest_backup_type="full",
        )


def test_backup_pg_form_rejects_negative_retention() -> None:
    """Reject a negative retention count (the fields are ``ge=0``)."""
    with pytest.raises(ValidationError):
        BackupPgForm(
            task_name="pg-task",
            hostname="pg-host",
            service_id=1,
            backup_dir=SAMPLE_BACKUP_DIR,
            stanza="sep-test",
            pgbackrest_retention_full=-1,
        )


def test_backup_task_response_roundtrips_owner_and_backup_type() -> None:
    """BackupTaskResponse serializes owner and backup_type cleanly."""
    response = BackupTaskResponse(
        name="pg-task",
        owner=TaskOwner.BACKUP_PG,
        hostname="pg-host",
        backend=TaskBackendEnum.PROXY,
        backup_type="P",
        data={"meta": {"target": "pg-host"}},
        protected=False,
        alert_on_fail=False,
    )

    dumped = response.model_dump(mode="json")

    assert isinstance(response, BaseTaskResponse)
    assert dumped["owner"] == TaskOwner.BACKUP_PG.value
    assert dumped["backup_type"] == "P"
    assert dumped["service_type"] is None
    assert "anonymize_mask" in dumped
    assert "anonymized_entities" in dumped
    assert "connectivity_warning" in dumped


def test_backup_task_detail_response_inherits_response_fields() -> None:
    """Carry host/port on the detail response beyond the list response."""
    detail = BackupTaskDetailResponse(
        name="pg-task",
        owner=TaskOwner.BACKUP_PG,
        backend=TaskBackendEnum.PROXY,
        backup_type="P",
        data={},
        protected=False,
        alert_on_fail=False,
    )

    assert detail.status is None
    assert detail.created_at is None
    assert detail.host is None
    assert detail.port is None
