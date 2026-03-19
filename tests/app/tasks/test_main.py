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

"""Define tests for the app.tasks.main module."""

from app.tasks.main import lifespan as tasks_module_lifespan
from app.tasks.main import tasks_lifespan


def test_tasks_app_lifespan_is_always_set():
    """Assert ``tasks_lifespan`` is always assigned at module level.

    The lifespan must not be gated behind a ``__name__`` check, because uvicorn
    re-imports the module with ``__name__ == "app.tasks.main"`` rather than
    ``"__main__"``, which would leave the lifespan as ``None``.
    """
    assert tasks_module_lifespan is tasks_lifespan
