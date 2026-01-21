# Copyright (C) 2025 Percona LLC
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

"""Define the MUM task specifications."""

from pathlib import Path

from app.tasks.models import Task, TaskBackendEnum, TaskOwner

LEGACY_TASK_NAME = "mum-users"
MUM_TASK_NAME_BY_ACTION = {
    "list_users": "mum-user-list",
    "create_user": "mum-user-create",
    "update_user": "mum-user-update",
    "delete_user": "mum-user-delete",
}
MUM_TASK_NAMES = tuple(MUM_TASK_NAME_BY_ACTION.values())
PAYLOAD_PATH = Path(__file__).parent / "mum_payload"
PYTHON_REQUIREMENTS = "PyMongo"


def _build_mum_task(task_name: str) -> Task:
    """Return a MUM task specification for the provided task name."""
    return Task(
        name=task_name,
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.MUM,
        protected=True,
        alert_on_fail=False,
        data={
            "task": "run-python",
            "meta": {
                "requirements": PYTHON_REQUIREMENTS,
            },
            "payload": f"file://{PAYLOAD_PATH}",
        },
    )


def get_default_mum_task() -> Task:
    """Return the legacy MUM task specification."""
    return _build_mum_task(LEGACY_TASK_NAME)


def get_mum_task(task_name: str) -> Task:
    """Return a MUM task specification for a supported task name."""
    if task_name not in MUM_TASK_NAMES and task_name != LEGACY_TASK_NAME:
        raise ValueError(f"Unsupported MUM task name: {task_name}")
    return _build_mum_task(task_name)


def get_mum_tasks(*, include_legacy: bool = True) -> list[Task]:
    """Return the MUM tasks for supported actions."""
    tasks = [_build_mum_task(task_name) for task_name in MUM_TASK_NAMES]
    if include_legacy:
        tasks.append(_build_mum_task(LEGACY_TASK_NAME))
    return tasks
