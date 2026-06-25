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

"""Wire the Checksums plugin as a declarative ``TaskExecutionApp``.

This definition replaces the hand-written JSON API router and schema: the
registry discovers the exported ``app`` and mounts its derived router, which
serves the byte-identical schema, list, detail, create, update, execute, and
delete surfaces. Create and update are derived from the model-first
:class:`~app.sep.plugins.checksums.models.ChecksumsForm` through the
``pt-table-checksum`` spec builder; delete is the framework's plain default; the
checksums-specific protected-task + running-conflict guards ride on the derived
PUT via ``update_guard``. The Jinja UI router is threaded explicitly (the
registry does not).
"""

from fastapi import Depends

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import get_username_mapping, HasNoConflictedRunningTasks
from app.sep.plugins.checksums.deps import get_unprotected_checksums_task
from app.sep.plugins.checksums.models import ChecksumsForm
from app.sep.plugins.checksums.routes import router as jinja_router
from app.sep.plugins.checksums.spec import build_checksums_spec
from app.sep.plugins.checksums.views import checksums_views
from app.sep.plugins.framework.apps import AppCapabilities, TaskExecutionApp
from app.tasks.models import TaskOwner

app = TaskExecutionApp(
    name="checksums",
    display_name="Checksums",
    uri_path="/checksums",
    nav_order=7,
    description="Run pt-table-checksum to verify MySQL replication consistency.",
    owner=TaskOwner.CHECKSUMS,
    create_model=ChecksumsForm,
    views=checksums_views,
    task_spec_builder=build_checksums_spec,
    capabilities=AppCapabilities(create=True, execute=True, update=True, delete=True),
    service_type=ServiceTypeEnum.MYSQL,
    list_status_filter=True,
    list_service_type_filter=True,
    response_context_provider=get_username_mapping,
    update_guard=(Depends(get_unprotected_checksums_task), HasNoConflictedRunningTasks),
    jinja_router=jinja_router,
)
