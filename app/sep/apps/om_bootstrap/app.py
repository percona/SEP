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

"""Register OpenManager Bootstrap as a ``BaseApp``.

Owns MongoDB provisioning execution: pre-flight checks, install/configure/
`rs.initiate`, and the persisted run/state-machine history for it -- the write
side `om_inventory` deliberately stays out of (PMM-15347/plan.md §4 item 5).
`om_inventory` keeps owning general, read-only host facts; this app owns
everything specific to *running a bootstrap*, including checks that are
read-only in effect but bootstrap-specific in scope (disk space, path, OS
version).

``sidebar=False`` and ``custom_ui=False``: there is nothing to navigate to here.
The wizard lives in PMM's own UI (PMM-15347/plan.md §4 item 4 / questions.md
Q4) -- the consumer is PMM's ``om`` managed service driving this app's API to
trigger and poll bootstraps, the same "consumer drives/polls, no SEP-native
page" shape `om_inventory` established.
"""

from app.sep.apps.framework.base import BaseApp
from app.sep.apps.om_bootstrap.api_routes import router as api_router
from app.sep.apps.om_bootstrap.schema import om_bootstrap_schema

app = BaseApp(
    name="om_bootstrap",
    display_name="OpenManager Bootstrap",
    uri_path="/om_bootstrap",
    css_class="om_bootstrap",
    sidebar=False,
    api_router=api_router,
    schema=om_bootstrap_schema,
    custom_ui=False,
)
