# Copyright 2026 Percona LLC
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

"""Define fixtures for plugins tests."""

import pytest

from app.sep.deps import check_for_conflicted_running_tasks
from app.sep.main import sep_app
from app.tasks.models import TaskBackendEnum, TaskWrite
from tests.app.factories import GeneratedTaskFactory


@pytest.fixture
def generated_task() -> TaskWrite:
    """Return a fake generated task while creating alters."""
    mock_data = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--alter=ADD COLUMN new_column INT --execute",
            "target": "localhost",
            "_schema_name": "public",
            "_table_name": "example_table",
        },
    }
    return GeneratedTaskFactory.build(data=mock_data, backend=TaskBackendEnum.PROXY)


@pytest.fixture
def _mock_check_for_conflicted_running_tasks() -> None:
    """Mock check_for_conflicted_running_tasks."""
    sep_app.dependency_overrides[check_for_conflicted_running_tasks] = lambda: None
    yield
    sep_app.dependency_overrides = {}
