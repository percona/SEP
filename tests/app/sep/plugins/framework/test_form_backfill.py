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

"""Tests for the legacy form backfill orchestrator."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.sep.plugins.framework.form_backfill import _persist_stamped_form
from app.sep.plugins.framework.spec import RESERVED_FORM_KEY
from app.tasks.models import Task, TaskBackendEnum, TaskOwner


def _minimal_task(*, data: dict) -> Task:
    """Build a task row with only the fields persistence touches."""
    return Task(
        name="legacy-task",
        data=data,
        backend=TaskBackendEnum.NOMAD,
        owner=TaskOwner.CHECKSUMS,
        last_updated_by="original-user",
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_persist_stamped_form_assigns_data_and_preserves_audit_fields():
    """Stamped ``data`` is written directly without touching audit columns."""
    task = _minimal_task(data={"meta": {}})
    stamped_data = {
        "meta": {},
        RESERVED_FORM_KEY: {"task_name": "legacy-task"},
    }
    session = MagicMock()
    session.flush = AsyncMock()

    await _persist_stamped_form(session, task, stamped_data, dry_run=False)

    assert task.data[RESERVED_FORM_KEY] == {"task_name": "legacy-task"}
    assert task.last_updated_by == "original-user"
    assert task.updated_at == datetime(2024, 1, 1, tzinfo=UTC)
    session.add.assert_called_once_with(task)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_stamped_form_dry_run_is_noop():
    """Dry-run mode must not mutate the task or touch the session."""
    original_data = {"meta": {}}
    task = _minimal_task(data=original_data)
    session = MagicMock()
    session.flush = AsyncMock()

    await _persist_stamped_form(
        session,
        task,
        {**original_data, RESERVED_FORM_KEY: {"task_name": "legacy-task"}},
        dry_run=True,
    )

    assert task.data == original_data
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
