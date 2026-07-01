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

"""Define the plugin schema for the Alert Troubleshooting plugin."""

from app.sep.apps.framework.schema import (
    AppSchema,
    Column,
    DetailView,
    ListView,
)

ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA = AppSchema(
    name="alert_troubleshooting",
    display_name="Alert Troubleshooting",
    description=(
        "Browse alerts grouped by service type and run diagnostic snippets "
        "against registered executor hosts."
    ),
    forms=[],
    # list_view reflects the AlertGroup response shape (service_type, label).
    # This plugin uses a custom grouped page — the generic list renderer is
    # not wired up for this plugin.
    list_view=ListView(
        columns=[
            Column(key="service_type", label="Service Type", sortable=True),
            Column(key="label", label="Label", sortable=True),
        ],
        default_sort="service_type",
    ),
    detail_view=DetailView(sections=[]),
)
