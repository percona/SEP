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

import logging
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.sep.plugins.checksums.app import app as checksums_app
from app.sep.plugins.framework.form_backfill import (
    _backfill_app,
    _BackfillApp,
    _persist_stamped_form,
    _rollback_backfill_session,
    _TaskBackfillOutcome,
    FormBackfillContext,
)
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


@pytest.mark.asyncio
async def test_rollback_backfill_session_swallows_rollback_failure():
    """A failed rollback must be logged without re-raising."""
    session = MagicMock()
    session.rollback = AsyncMock(side_effect=RuntimeError("broken session"))
    ctx = FormBackfillContext(log=logging.getLogger("test"))

    await _rollback_backfill_session(
        session,
        ctx,
        app_name="checksums",
        task_name="task-fail",
    )


@pytest.mark.asyncio
async def test_backfill_app_continues_when_persist_and_rollback_fail():
    """One task's persist and rollback failures must not abort the batch."""
    task_fail = _minimal_task(data={"meta": {}})
    task_fail.name = "task-fail"
    task_ok = _minimal_task(data={"meta": {}})
    task_ok.name = "task-ok"
    stamped_payload = {"meta": {}, RESERVED_FORM_KEY: {"task_name": "x"}}

    session = MagicMock()
    session.commit = AsyncMock(side_effect=[RuntimeError("commit failed"), None])
    session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed"))
    session.flush = AsyncMock()

    entry = _BackfillApp(app=checksums_app, reconstructor=lambda _t, _c: None)
    ctx = FormBackfillContext(log=logging.getLogger("test"))
    outcomes = [
        _TaskBackfillOutcome("stamped", stamped_payload),
        _TaskBackfillOutcome("stamped", stamped_payload),
    ]
    expected_commit_attempts = len(outcomes)

    with (
        patch(
            "app.sep.plugins.framework.form_backfill.TaskManager.list_active",
            new_callable=AsyncMock,
            return_value=[task_fail, task_ok],
        ),
        patch(
            "app.sep.plugins.framework.form_backfill._backfill_single_task",
            side_effect=outcomes,
        ),
    ):
        stats = await _backfill_app(session, entry, ctx)

    assert stats.skipped_error == 1
    assert stats.stamped == 1
    assert session.commit.await_count == expected_commit_attempts
    session.rollback.assert_awaited_once()
