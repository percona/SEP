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

"""Define the read-only plugin schema for Tasks."""

from app.sep.apps.framework.schema import (
    AppSchema,
    Column,
    ColumnFormat,
    ListView,
)

TASKS_PLUGIN_SCHEMA = AppSchema(
    name="tasks",
    display_name="Task Manager",
    description=(
        "View task definitions, execution history, and running task logs in one place. "
        "Task creation and execution remain on the owning plugins."
    ),
    forms=[],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="backend", label="Backend", sortable=True),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(key="created_by", label="Created By"),
            Column(key="last_updated_by", label="Last Updated By"),
        ],
        default_sort="name",
    ),
)
