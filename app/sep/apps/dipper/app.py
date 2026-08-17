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

"""Wire the Dipper plugin as a declarative ``BaseApp``.

dipper resolves its collector script from ``(service_id, collector_type)`` and
exposes a service-keyed JSON surface (history listing, dynamic form schema, script
preview, execute) plus a static plugin schema — none of which map onto the
framework's filename-keyed ``ScriptSource`` derived routes — so it is exported as a
plain :class:`BaseApp` carrying its hand-written ``api_router`` unchanged, the same
shape as ``backup_mongo`` and the bespoke ``inventory``/``report`` apps.
"""

from app.sep.apps.dipper.api_routes import router as api_router
from app.sep.apps.dipper.constants import ARTIFACT_TYPE_DIPPER, DIPPER_PAYLOADS_DIR
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.nav_icons import NavIcon

app = BaseApp(
    name="dipper",
    display_name="Dipper Data Collection",
    uri_path="/dipper",
    css_class="dipper",
    group="diagnostics",
    nav_order=12,
    react_route="/dipper",
    nav_icon=NavIcon.SCIENCE,
    api_router=api_router,
    artifact_base_dirs={ARTIFACT_TYPE_DIPPER: lambda: DIPPER_PAYLOADS_DIR},
    uses_task_data=True,
)
