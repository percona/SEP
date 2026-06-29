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
    _backfill_single_task,
    _BackfillApp,
    _persist_stamped_form,
    _rollback_backfill_session,
    _TaskBackfillOutcome,
    FormBackfillContext,
    main,
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


def _reconstructor_must_not_run(_task: Task, _ctx: FormBackfillContext) -> dict:
    """Fail fast when the orchestrator invokes a reconstructor unexpectedly."""
    raise AssertionError("reconstructor must not run")


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


def test_backfill_single_task_skips_existing_form_stamp():
    """Re-running the pipeline must not overwrite an existing ``data['_form']`` stamp."""
    task = _minimal_task(
        data={"meta": {}, RESERVED_FORM_KEY: {"task_name": "already-stamped"}},
    )
    entry = _BackfillApp(app=checksums_app, reconstructor=_reconstructor_must_not_run)
    ctx = FormBackfillContext(log=logging.getLogger("test"))

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "skipped_existing"
    assert outcome.stamped_data is None
    assert task.data[RESERVED_FORM_KEY] == {"task_name": "already-stamped"}


def test_backfill_single_task_skips_invalid_reconstructed_form():
    """A reconstructed body that fails ``create_model`` validation is not stamped."""
    task = _minimal_task(data={"meta": {}})

    def _invalid_body(_task: Task, _ctx: FormBackfillContext) -> dict:
        return {
            "task_name": "",
            "hostname": "executor-1",
            "service_id": 1,
        }

    entry = _BackfillApp(app=checksums_app, reconstructor=_invalid_body)
    ctx = FormBackfillContext(log=logging.getLogger("test"))

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "skipped_invalid"
    assert outcome.stamped_data is None
    assert RESERVED_FORM_KEY not in task.data


@pytest.mark.asyncio
async def test_backfill_single_task_stamp_preserves_audit_fields_on_persist():
    """A successful stamp plus persist must leave audit attribution untouched."""
    task = _minimal_task(data={"meta": {"command": "pt-table-checksum"}})

    def _valid_body(_task: Task, _ctx: FormBackfillContext) -> dict:
        return {
            "task_name": _task.name,
            "hostname": "executor-1",
            "service_id": 1,
            "recursion_method": "processlist",
        }

    entry = _BackfillApp(app=checksums_app, reconstructor=_valid_body)
    ctx = FormBackfillContext(log=logging.getLogger("test"))
    session = MagicMock()
    session.flush = AsyncMock()

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "stamped"
    assert outcome.stamped_data is not None
    await _persist_stamped_form(session, task, outcome.stamped_data, dry_run=False)

    assert task.data[RESERVED_FORM_KEY]["task_name"] == "legacy-task"
    assert task.last_updated_by == "original-user"
    assert task.updated_at == datetime(2024, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_backfill_app_records_mixed_outcomes_without_aborting():
    """Mixed per-task outcomes in one batch must all be counted independently."""
    stamped_payload = {"meta": {}, RESERVED_FORM_KEY: {"task_name": "stamped"}}
    session = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    entry = _BackfillApp(app=checksums_app, reconstructor=lambda _t, _c: None)
    ctx = FormBackfillContext(log=logging.getLogger("test"))
    outcomes = [
        _TaskBackfillOutcome("skipped_existing"),
        _TaskBackfillOutcome("skipped_unreconstructable"),
        _TaskBackfillOutcome("skipped_invalid"),
        _TaskBackfillOutcome("skipped_error"),
        _TaskBackfillOutcome("stamped", stamped_payload),
    ]

    with (
        patch(
            "app.sep.plugins.framework.form_backfill.TaskManager.list_active",
            new_callable=AsyncMock,
            return_value=[_minimal_task(data={"meta": {}}) for _ in outcomes],
        ),
        patch(
            "app.sep.plugins.framework.form_backfill._backfill_single_task",
            side_effect=outcomes,
        ),
    ):
        stats = await _backfill_app(session, entry, ctx)

    assert stats.skipped_existing == 1
    assert stats.skipped_unreconstructable == 1
    assert stats.skipped_invalid == 1
    assert stats.skipped_error == 1
    assert stats.stamped == 1
    assert stats.processed == len(outcomes)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_app_dry_run_never_commits():
    """Dry-run mode must not commit even when tasks are stamped in memory."""
    stamped_payload = {"meta": {}, RESERVED_FORM_KEY: {"task_name": "dry-run"}}
    session = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    entry = _BackfillApp(app=checksums_app, reconstructor=lambda _t, _c: None)
    ctx = FormBackfillContext(log=logging.getLogger("test"), dry_run=True)

    with (
        patch(
            "app.sep.plugins.framework.form_backfill.TaskManager.list_active",
            new_callable=AsyncMock,
            return_value=[_minimal_task(data={"meta": {}})],
        ),
        patch(
            "app.sep.plugins.framework.form_backfill._backfill_single_task",
            return_value=_TaskBackfillOutcome("stamped", stamped_payload),
        ),
    ):
        stats = await _backfill_app(session, entry, ctx)

    assert stats.stamped == 1
    session.commit.assert_not_awaited()
    session.flush.assert_not_awaited()


def test_main_cli_help_exits_zero(capsys):
    """The module entry point exposes the documented CLI flags."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--dry-run" in help_text
    assert "--owner" in help_text
    assert "--verbose" in help_text
