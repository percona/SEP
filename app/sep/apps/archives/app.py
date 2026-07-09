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

"""Wire the Archives plugin as a declarative ``TaskExecutionApp``.

This definition replaces the hand-written JSON API router and schema: the
registry discovers the exported ``app`` and mounts its derived router, which
serves the schema, list, detail, create, execute, update, and delete surfaces.
Create and update are derived from the model-first
:class:`~app.sep.apps.archives.models.ArchivesCreate` through the
``run-python`` pt-archiver spec builder; the connectivity probe and the source
service selection ride on the source ``ServiceRef(check_connectivity=True)``, and
the archiver failure-alert builder is stamped via ``alert_detail_builder``. The
deprecated Jinja UI router is threaded as ``jinja_router``; its flat form body is
folded into the one-of model in ``deps``.
"""

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.archives.alerts import ALERT_DETAIL_BUILDER
from app.sep.apps.archives.models import ArchivesCreate, OWNER
from app.sep.apps.archives.routes import router as jinja_router
from app.sep.apps.archives.spec import build_archives_spec
from app.sep.apps.archives.views import archives_views
from app.sep.apps.framework.apps import (
    AppCapabilities,
    ListFilterConfig,
    TaskExecutionApp,
)

app = TaskExecutionApp(
    name="archives",
    display_name="Archives",
    uri_path="/archives",
    css_class="archive",
    nav_order=11,
    description="Run pt-archiver to purge or archive rows from a MySQL table.",
    owner=OWNER,
    create_model=ArchivesCreate,
    views=archives_views,
    task_spec_builder=build_archives_spec,
    alert_detail_builder=ALERT_DETAIL_BUILDER,
    capabilities=AppCapabilities(update=True, delete=True),
    service_type=ServiceTypeEnum.MYSQL,
    list_filter=ListFilterConfig(status=True),
    jinja_router=jinja_router,
)
