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

"""Cover the beat-row task-name resolution shared by the periodic-task helpers."""

import json

import pytest
from sqlalchemy_celery_beat import PeriodicTask

from app.tasks.periodic.utils import resolve_schedule_task_name


def _row(args: str | None = None, kwargs: str | None = None) -> PeriodicTask:
    """Build an unpersisted beat row carrying the given raw argument columns."""
    return PeriodicTask(
        name="row",
        task="app.tasks.celery.execute_task_by_name",
        args=args,
        kwargs=kwargs,
    )


class TestResolveScheduleTaskName:
    """Cover every shape of ``args``/``kwargs`` the beat store can hold."""

    def test_kwargs_task_name_is_resolved(self) -> None:
        """Return the name ``kwargs.task_name`` carries, the form every writer uses."""
        assert (
            resolve_schedule_task_name(_row(kwargs=json.dumps({"task_name": "r1"})))
            == "r1"
        )

    def test_positional_args_are_resolved(self) -> None:
        """Return ``args[0]`` for the positional encoding the model still reads."""
        assert resolve_schedule_task_name(_row(args=json.dumps(["r1"]))) == "r1"

    def test_kwargs_override_positional_args(self) -> None:
        """Prefer ``kwargs.task_name`` when a row carries both encodings."""
        row = _row(
            args=json.dumps(["positional"]), kwargs=json.dumps({"task_name": "r1"})
        )

        assert resolve_schedule_task_name(row) == "r1"

    @pytest.mark.parametrize(
        ("args", "kwargs"),
        [
            pytest.param("not json", None, id="args-not-json"),
            pytest.param(None, "not json", id="kwargs-not-json"),
            pytest.param(json.dumps({"a": 1}), None, id="args-not-a-list"),
            pytest.param(None, json.dumps(["a"]), id="kwargs-not-a-mapping"),
        ],
    )
    def test_unreadable_arguments_resolve_to_none(
        self, args: str | None, kwargs: str | None
    ) -> None:
        """Resolve an unreadable row to ``None`` rather than raising.

        A caller iterating the whole beat store must not fail on one row, so a
        hand-edited or foreign-written row is reported as nameless instead of
        raising :exc:`json.JSONDecodeError` or :exc:`AttributeError` out of the walk.
        """
        assert resolve_schedule_task_name(_row(args=args, kwargs=kwargs)) is None

    @pytest.mark.parametrize(
        "task_name", [None, 5, "", [], {}], ids=["none", "int", "empty", "list", "dict"]
    )
    def test_a_name_that_is_not_a_non_empty_string_resolves_to_none(
        self, task_name: object
    ) -> None:
        """Resolve to ``None`` when the derived name is not a usable task name."""
        row = _row(kwargs=json.dumps({"task_name": task_name}))

        assert resolve_schedule_task_name(row) is None

    def test_a_row_carrying_no_arguments_resolves_to_none(self) -> None:
        """Resolve to ``None`` when neither column names a task."""
        assert resolve_schedule_task_name(_row()) is None
