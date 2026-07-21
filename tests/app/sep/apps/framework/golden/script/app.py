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

"""Wire the Golden Script plugin as a script-backed ``TaskExecutionApp``.

A script-flavored app derives its surface from the ``script_source`` seam: the
listing, the per-script ``GET /snippet/schema``, the ``POST /snippet/execute``
delegation, and ``GET /snippet/history``. It declares no model-first CRUD.
"""

from app.sep.apps.framework.apps import TaskExecutionApp
from app.sep.apps.golden_script.source import golden_script_source
from app.tasks.models import ANY_OWNER

app = TaskExecutionApp(
    name="golden_script",
    display_name="Golden Script",
    uri_path="/golden_script",
    description="TODO: describe what the Golden Script scripts do.",
    owner=ANY_OWNER,
    script_source=golden_script_source,
)
