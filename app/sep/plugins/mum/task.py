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

MUM_TASK_NAME_BY_ACTION = {
    "list_users": "mum-user-list",
    "create_user": "mum-user-create",
    "update_user": "mum-user-update",
    "delete_user": "mum-user-delete",
    "list_roles": "mum-role-list",
    "create_role": "mum-role-create",
    "update_role": "mum-role-update",
    "delete_role": "mum-role-delete",
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


def get_mum_task(task_name: str) -> Task:
    """Return a MUM task specification for a supported task name."""
    if task_name not in MUM_TASK_NAMES:
        raise ValueError(f"Unsupported MUM task name: {task_name}")
    return _build_mum_task(task_name)


def get_mum_tasks() -> list[Task]:
    """Return the MUM tasks for supported actions."""
    return [_build_mum_task(task_name) for task_name in MUM_TASK_NAMES]
