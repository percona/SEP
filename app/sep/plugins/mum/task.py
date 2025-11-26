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

"""Define the default MUM task specification."""

from pathlib import Path

from app.tasks.models import Task, TaskBackendEnum, TaskOwner

TASK_NAME = "mum-users"
PAYLOAD_PATH = Path(__file__).parent / "mum_payload"
PYTHON_REQUIREMENTS = "PyMongo"


def get_default_mum_task() -> Task:
    """Return the default MUM task specification.
    
    This task is a PROXY task that references the 'run-python' system task.
    It uses the mum_payload file and is configured for MongoDB user management.
    
    Returns:
        Task: The task specification for the default MUM task
    """
    return Task(
        name=TASK_NAME,
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
